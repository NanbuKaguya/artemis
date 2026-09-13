"""暴露给本地 LLM 的工具面 —— **只读，且是结构性只读**。

设计立场：agent 只做情报，不碰交易。

这句话如果只写在文档里，等于没写。LLM 会幻觉出不存在的工具名、
会被提示注入诱导、会在长对话里忘记约束。所以约束必须落在代码结构上：

  · 注册表里**只有**只读命令，写操作根本不在里面
  · dispatch() 二次校验命令是否在白名单内
  · 任何不在白名单的调用返回结构化拒绝，而不是"尽力而为"

即使模型输出 `{"name": "place_order"}`，这里也没有 place_order 可调。
这不是靠模型听话，是靠没东西可用。

工具描述用中文写，因为 Hermes 系列对中文指令的遵循度在实测中好于
"英文描述 + 中文对话"的混合模式；而且描述里的口径要和你读到的报告一致。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ..service import COMMANDS, Envelope

# 允许 LLM 调用的命令白名单。写操作（journal-add）刻意不在此列。
READONLY_COMMANDS = frozenset({
    "health", "session", "screen", "review", "preflight",
})

# 明确记录被排除的命令及理由，避免以后有人"顺手加回去"
EXCLUDED: dict[str, str] = {
    "journal-add": "写操作。事前承诺必须由人亲手写，代笔就失去了它全部的意义",
    "calendar-refresh": "写操作且涉及外部请求，应由调度器而非模型触发",
}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    command: str

    def to_json_schema(self) -> dict:
        """Hermes / OpenAI 通用的函数签名格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="check_market_session",
        description=(
            "查询当前是否交易日、处于哪个时段、以及建议动作。"
            "任何其他工具调用之前都应先调它 —— 非交易日的数据是上一交易日的收盘值，"
            "直接拿来当今日情报会误导用户。"
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        command="session",
    ),
    ToolSpec(
        name="screen_stocks",
        description=(
            "对一组股票代码做排雷检查，返回每只票是否踩雷（ST/退市风险、市值过小、"
            "低价股、当日涨停买不进、流动性不足、换手过热）。"
            "结论分三档：❌ 排除（一票否决）、⚠ 注意（仅提示）、✓ 通过。"
            "注意：'通过'只代表没踩这几类雷，**不代表推荐买入**。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "6 位股票代码列表，如 ['600519','000001']",
                },
                "with_history": {
                    "type": "boolean",
                    "description": (
                        "是否拉取近期历史（默认 true，强烈建议保持 true）。"
                        "停牌、昨日涨停、流动性、换手这四类雷全部依赖历史，"
                        "设为 false 时它们会被标为「未检」—— 此时的"
                        "「通过」几乎没有信息量，只说明名称/市值/股价没问题。"
                        "每只约多一次请求。只有在股票数超过 50 只且"
                        "用户明确要求快速粗筛时才设 false，"
                        "并且必须把 caveat 字段原样转达给用户。"
                    ),
                },
            },
            "required": ["codes"],
        },
        command="screen",
    ),
    ToolSpec(
        name="discipline_review",
        description=(
            "读取交易日志，统计临时起意占比、冲动交易占比等纪律指标。"
            "flags 字段里的内容是需要提醒用户的问题。"
            "这是本系统里最该被认真对待的输出 —— 对多数人来说，"
            "执行纪律的改善空间远大于选股能力的改善空间。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "journal_path": {"type": "string",
                                 "description": "日志路径，默认 ./journal.jsonl"},
            },
            "required": [],
        },
        command="review",
    ),
    ToolSpec(
        name="data_health",
        description=(
            "检查本地行情数据的完整性，报告哪些能力已失效或降级。"
            "**在引用任何基于历史数据的结论之前必须先调它** —— "
            "数据缺列造成的失效是静默的，系统会照常出结果但结论是假的。"
            "若返回 dead 非空，相关结论一律不可引用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "data_dir": {"type": "string", "description": "数据目录，默认 ./data_cache"},
            },
            "required": [],
        },
        command="preflight",
    ),
    ToolSpec(
        name="system_health",
        description="检查运行环境：依赖、时区、交易日历新鲜度、数据目录可写性。",
        parameters={"type": "object", "properties": {}, "required": []},
        command="health",
    ),
]

_BY_NAME = {t.name: t for t in TOOLS}


def _assert_readonly() -> None:
    """启动时自检：注册表里绝不能混进写操作。

    这是防止未来的自己手滑 —— 加一个工具很容易，
    加一个会下单的工具也很容易。
    """
    bad = [t.name for t in TOOLS if t.command not in READONLY_COMMANDS]
    if bad:
        raise RuntimeError(
            f"工具注册表包含非只读命令: {bad}。"
            f"本模块的设计前提是 agent 只做情报不碰交易，"
            f"要放开必须显式修改 READONLY_COMMANDS 并重新审视风险。"
        )


_assert_readonly()


# --------------------------------------------------------------------------
# 渲染：不同 LLM 后端要不同格式
# --------------------------------------------------------------------------
HERMES_SYSTEM = """你是一个函数调用 AI 助手，负责为一位 A 股个人投资者生成每日情报。

你可以调用 <tools></tools> 标签内提供的函数。需要调用时，输出一个 JSON 对象，
用 <tool_call></tool_call> 标签包裹，包含 "name" 和 "arguments" 两个键。
函数执行结果会以 <tool_response></tool_response> 返回给你。

<tools>
{tools}
</tools>

工作准则（比工具本身更重要）：
1. 你只提供情报，**绝不给出买卖建议、不预测涨跌、不推荐个股**。
   用户明确要求过：agent 只做情报，不碰交易。
2. 先调 check_market_session。非交易日的数据是上一交易日的，
   把它当成今日情报会误导用户。
3. 引用任何基于历史数据的结论前，先调 data_health。
   若 dead 非空，明确告诉用户"该部分结论不可信"，而不是照常引用。
4. 排雷检查的"✓ 通过"只代表没踩那几类雷，**不代表推荐买入**。
   转述时必须保留这个限定，否则用户会当成买入信号。
5. 不要编造工具没返回的数字。数据缺失就说缺失。
6. 纪律指标（临时起意占比、冲动交易占比）如果超标，直接说，不要为了让人舒服而模糊。

回答用中文，简洁，先说需要注意的问题，再说其余情况。"""


def render_hermes_system() -> str:
    """Hermes 系列的系统提示：工具签名以 JSON 逐行放进 <tools> 标签。"""
    lines = "\n".join(json.dumps(t.to_json_schema(), ensure_ascii=False) for t in TOOLS)
    return HERMES_SYSTEM.format(tools=lines)


def render_openai_tools() -> list[dict]:
    """OpenAI 原生 tools 数组。vLLM 加 --tool-call-parser hermes 后可直接用这个。"""
    return [t.to_json_schema() for t in TOOLS]


# --------------------------------------------------------------------------
# 分发
# --------------------------------------------------------------------------
def dispatch(name: str, arguments: dict | None = None) -> dict:
    """执行一次工具调用。返回可直接放进 <tool_response> 的 dict。

    对未知或被禁用的工具，返回结构化拒绝而不是抛异常 ——
    模型需要看到"这个工具不存在"才能自我纠正，
    抛异常只会让整个对话中断。
    """
    arguments = arguments or {}
    spec = _BY_NAME.get(name)

    if spec is None:
        reason = EXCLUDED.get(name)
        return {
            "ok": False,
            "error": (f"工具 {name} 已被禁用：{reason}" if reason
                      else f"不存在名为 {name} 的工具"),
            "error_type": "tool_not_available",
            "available_tools": list(_BY_NAME),
        }

    # 二次校验：即使注册表被改坏，这里也拦住
    if spec.command not in READONLY_COMMANDS:
        return {"ok": False, "error": f"{name} 不是只读操作，已拒绝",
                "error_type": "write_denied"}

    fn: Callable[[dict], Envelope] = COMMANDS[spec.command]
    try:
        env = fn(dict(arguments))
    except Exception as e:  # noqa: BLE001 - 必须返回结构化错误，不能中断对话
        return {"ok": False, "error": str(e)[:200], "error_type": type(e).__name__}

    out = {"ok": env.ok, "data": env.data}
    if env.error:
        out["error"] = env.error
    if env.warnings:
        out["warnings"] = env.warnings
    if env.freshness:
        out["freshness"] = env.freshness
    return out


def tool_names() -> list[str]:
    return list(_BY_NAME)
