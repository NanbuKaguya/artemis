"""AI 研究助手（Copilot 层）。

关于 LLM 在量化系统里的正确位置 —— 这可能是整份设计里最容易做错的一层。

❌ LLM 不该做的：
   预测明天涨跌、直接输出买卖信号、决定仓位、自动下单。
   语言模型没有价格数据的先验，让它"看图说话"预测行情，
   得到的是流畅的胡说八道 —— 而且因为流畅，你会信。

✅ LLM 擅长且该做的：
   1. 因子假设生成 —— 从研报/公告/财报里提炼"可检验的假设"，
      再交给回测去证伪。假设由 AI 提，裁决权归数据。
   2. 非结构化信息抽取 —— 公告、财报、问询函里的排雷信号，
      这是纯 NLP 任务，也是 A 股散户最难覆盖的信息盲区。
   3. 魔鬼代言人 —— 对每个买入决策做反方辩护。人最缺的是
      主动找反面证据的意愿，这件事外包给 AI 成本极低。
   4. 复盘归因的自然语言解释 —— 把一堆数字翻译成"这周你为什么亏"。
   5. 代码生成与研究流水线自动化 —— 这是它最强的部分。

一句话：让 AI 做研究员和风控质检员，不要让它做交易员。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

MODEL = "claude-opus-5"


def _client():
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("未安装 anthropic SDK。请 `pip install anthropic`。") from e
    return anthropic.Anthropic()


# --------------------------------------------------------------------------
# 1. 魔鬼代言人：对每个买入决策做反方辩护
# --------------------------------------------------------------------------
DEVILS_ADVOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "bear_case": {
            "type": "array",
            "items": {"type": "string"},
            "description": "针对该买入决策的具体反面论据，每条必须可证伪",
        },
        "hidden_risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "决策理由中被忽略的风险，尤其是 A 股特有的（解禁、减持、商誉、问询函、退市）",
        },
        "what_would_make_this_wrong": {
            "type": "string",
            "description": "一句话说明：出现什么情况就该承认判断错了",
        },
        "crowding_concern": {
            "type": "string",
            "description": "这个逻辑是否已经是市场共识/拥挤交易",
        },
        "verdict": {
            "type": "string",
            "enum": ["证据充分", "存疑", "建议放弃"],
        },
    },
    "required": ["bear_case", "hidden_risks", "what_would_make_this_wrong",
                 "crowding_concern", "verdict"],
    "additionalProperties": False,
}

DEVILS_ADVOCATE_SYSTEM = """你是一个 A 股量化团队的风控质检员，职责是对每一笔拟买入决策做反方辩护。

你的立场是刻意的悲观主义。不是为了否定一切，而是因为提出决策的人已经
把多头逻辑想过一遍了，缺的是有人认真去找反面证据。

规则：
- 只基于给定的事实推理，不要编造具体的财务数字、公告内容或新闻事件
- 事实不足以判断时，明确说"信息不足"，而不是编一个理由
- 优先指出 A 股特有的风险：限售解禁、大股东减持与质押、商誉减值、
  监管问询与立案、退市新规指标、行业政策突变、拥挤交易与流动性
- 不要预测股价涨跌，只评估"这个决策理由是否站得住"
- 每条论据必须可证伪：能被后续数据验证或推翻"""


@dataclass
class BuyCandidate:
    code: str
    name: str
    thesis: str
    factor_scores: dict[str, float]
    fundamentals: dict[str, Any] | None = None
    recent_news: list[str] | None = None

    def to_prompt(self) -> str:
        parts = [
            f"标的：{self.code} {self.name}",
            f"买入理由：{self.thesis}",
            f"因子得分：{json.dumps(self.factor_scores, ensure_ascii=False)}",
        ]
        if self.fundamentals:
            parts.append(f"基本面数据：{json.dumps(self.fundamentals, ensure_ascii=False)}")
        if self.recent_news:
            parts.append("近期公告/新闻：\n" + "\n".join(f"- {n}" for n in self.recent_news))
        return "\n".join(parts)


def devils_advocate(candidate: BuyCandidate, model: str = MODEL) -> dict:
    """对一个买入候选做反方辩护。返回结构化的质疑清单。"""
    client = _client()
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=DEVILS_ADVOCATE_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": DEVILS_ADVOCATE_SCHEMA}},
        messages=[{"role": "user", "content": candidate.to_prompt()}],
    )
    if resp.stop_reason == "refusal":
        return {"error": "refusal", "detail": getattr(resp, "stop_details", None)}
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


# --------------------------------------------------------------------------
# 2. 因子假设生成：AI 提假设，回测做裁决
# --------------------------------------------------------------------------
HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "economic_rationale": {
                        "type": "string",
                        "description": "为什么这个因子该有超额收益。说不清机制的不要提。",
                    },
                    "formula_description": {
                        "type": "string",
                        "description": "用可得的日频量价/财务数据如何计算，要具体到列名和窗口",
                    },
                    "required_data": {"type": "array", "items": {"type": "string"}},
                    "expected_decay_days": {
                        "type": "integer",
                        "description": "预期信号半衰期，决定调仓频率和成本预算",
                    },
                    "known_failure_mode": {
                        "type": "string",
                        "description": "这个因子在什么市场环境下会失效",
                    },
                    "crowding_risk": {"type": "string", "enum": ["低", "中", "高"]},
                },
                "required": ["name", "economic_rationale", "formula_description",
                             "required_data", "expected_decay_days",
                             "known_failure_mode", "crowding_risk"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}

HYPOTHESIS_SYSTEM = """你是 A 股量化研究员，负责提出**可检验的**因子假设。

硬性要求：
- 每个假设必须先说清经济机制（谁在犯错？为什么这个错误能持续？），
  再说计算方法。说不清机制的因子不要提 —— 那是在拟合噪音。
- 计算方法必须只用日频量价、市值、行业、常规财务报表数据。
  不要提需要 tick 数据、另类数据、或已停止披露的数据（如北向资金
  实时数据自 2024-08-19 起已改为季度披露）。
- 必须诚实说明失效场景和拥挤风险。
- 不要提你不确定在 A 股成立的美股经验（如 T+0 相关、做空相关策略），
  A 股 T+1、有涨跌停、融券受限。
- 宁可提 3 个逻辑扎实的，不要提 10 个凑数的。

你提出的只是假设。裁决权在回测和样本外验证，不在你。"""


def generate_hypotheses(context: str, n: int = 3, model: str = MODEL) -> dict:
    """让 AI 提出因子假设。context 可以是研报摘要、市场观察、或研究方向。"""
    client = _client()
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        system=HYPOTHESIS_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": HYPOTHESIS_SCHEMA}},
        messages=[{
            "role": "user",
            "content": f"研究背景：\n{context}\n\n请提出 {n} 个可检验的因子假设。",
        }],
    )
    if resp.stop_reason == "refusal":
        return {"error": "refusal"}
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


# --------------------------------------------------------------------------
# 3. 公告排雷：非结构化信息抽取
# --------------------------------------------------------------------------
LANDMINE_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_level": {"type": "string", "enum": ["无风险", "关注", "警告", "立即回避"]},
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["财务造假嫌疑", "商誉减值", "大股东减持", "股权质押",
                                 "监管问询", "立案调查", "审计意见异常", "退市风险",
                                 "业绩暴雷", "限售解禁", "关联交易", "其他"],
                    },
                    "evidence": {"type": "string", "description": "原文中的依据，不要转述成推测"},
                    "severity": {"type": "string", "enum": ["低", "中", "高"]},
                },
                "required": ["category", "evidence", "severity"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["risk_level", "signals", "summary"],
    "additionalProperties": False,
}

LANDMINE_SYSTEM = """你是 A 股公告排雷员。输入是上市公司公告/财报摘要，
输出是结构化的风险信号。

规则：
- 只标注原文中**有明确依据**的风险，evidence 字段必须能在原文找到对应
- 不要脑补。原文没提到的事，不要推测
- 宁可漏报模糊的，不要误报不存在的 —— 误报会让这个工具变成噪音源，
  几次之后你就不看它了
- 严格程度参考 2024 年退市新规：财务类退市（净利润为负且营收 < 3 亿）、
  市值退市、面值退市、重大违法退市"""


def scan_announcement(text: str, model: str = MODEL) -> dict:
    """扫描公告文本，抽取排雷信号。"""
    client = _client()
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=LANDMINE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": LANDMINE_SCHEMA}},
        messages=[{"role": "user", "content": f"公告内容：\n\n{text}"}],
    )
    if resp.stop_reason == "refusal":
        return {"error": "refusal"}
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


# --------------------------------------------------------------------------
# 4. 复盘解释：把数字翻译成人话
# --------------------------------------------------------------------------
REVIEW_SYSTEM = """你是量化交易的复盘助手。输入是本期的绩效数据、归因分解、
纪律评分和风控事件，输出是一份给交易者本人看的复盘。

要求：
- 先说亏损/回撤的原因，再说盈利的原因。人更需要知道自己为什么亏
- 明确区分"策略问题"和"执行问题" —— 两者的修复方式完全不同
- 如果纪律评分低，直说。不要为了让人舒服而模糊
- 不要预测下期行情，不要给出具体买卖建议
- 不要安慰。你的价值是准确，不是让人好受
- 结尾给出 1-3 条**具体可执行**的改进项，不要泛泛而谈"复盘总结经验" """


def explain_review(payload: dict, model: str = MODEL, stream: bool = True) -> str:
    """生成自然语言复盘。payload 应包含绩效、归因、纪律分、风控事件。"""
    client = _client()
    content = f"本期数据：\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n```"
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=REVIEW_SYSTEM,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
    )
    if stream:
        with client.messages.stream(**kwargs) as s:
            resp = s.get_final_message()
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        return "（模型拒绝了本次请求）"
    return "\n".join(b.text for b in resp.content if b.type == "text")


def available() -> bool:
    """检查 Copilot 是否可用（SDK 已装 + 凭证可解析）。"""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.path.exists(os.path.expanduser("~/.config/anthropic"))
    )
