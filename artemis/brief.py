"""每日情报简报。

架构上的关键决定：**事实层与叙述层分离**。

  build_facts()   纯数据采集，不碰 LLM
  render_text()   把事实排成人能读的报告，不碰 LLM
  narrate()       可选，让本地 Hermes 加一层自然语言叙述

为什么这样分：本地推理会挂 —— 显存不够、服务没起、模型拉取失败、
上下文被截断。如果简报依赖 LLM 才能生成，那你在最需要它的那天
（比如刚重启完机器）恰恰收不到。

事实层永远能出。LLM 是锦上添花，不是承重墙。

另一个好处是可核对：报告里每个数字都来自某次工具调用，
你可以拿 facts 的原始 JSON 去对，而不是相信模型的转述。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .calendar import CN_TZ, TradingCalendar
from .service import COMMANDS


@dataclass
class Brief:
    kind: str                       # 'premarket' | 'postmarket'
    generated_at: str
    facts: dict[str, Any] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    narrative: str | None = None
    llm_error: str | None = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2, default=str)


def _watchlist(path: str | Path = "watchlist.txt") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def build_facts(kind: str = "premarket", watchlist_path: str = "watchlist.txt",
                journal_path: str = "./journal.jsonl") -> Brief:
    """采集事实。每一项失败都被单独捕获 —— 一个数据源挂掉不该让整份简报消失。"""
    b = Brief(kind=kind, generated_at=datetime.now(CN_TZ).isoformat(timespec="seconds"))

    # 1. 市场状态
    env = COMMANDS["session"]({})
    b.facts["session"] = env.data
    if not env.data.get("is_trading_day"):
        b.alerts.append(f"今日非交易日（依据：{env.data.get('basis')}）")
    # 日历本身的告警不在这里报 —— health 检查已经覆盖，
    # 同一个问题换个措辞说两遍，只会让人跳过整段告警

    # 2. 运行环境
    try:
        h = COMMANDS["health"]({})
        b.facts["health"] = {"ok": h.ok, "warnings": h.warnings}
        if not h.ok:
            b.alerts.append("运行环境健康检查未通过，后续结论可能不可靠")
        for w in (h.warnings or []):
            b.alerts.append(w)
    except Exception as e:  # noqa: BLE001
        b.facts["health"] = {"error": str(e)[:150]}
        b.alerts.append(f"健康检查失败：{str(e)[:100]}")

    # 3. 自选股排雷（盘前才需要）
    codes = _watchlist(watchlist_path)
    if kind == "premarket" and codes:
        try:
            s = COMMANDS["screen"]({"codes": codes})
            b.facts["screen"] = s.data
            blocked = s.data.get("blocked", [])
            if blocked:
                b.alerts.append(f"{len(blocked)}/{len(codes)} 只自选股踩雷：{', '.join(blocked)}")
        except Exception as e:  # noqa: BLE001
            b.facts["screen"] = {"error": str(e)[:150]}
            b.alerts.append(f"排雷检查失败（多半是数据源不可达）：{str(e)[:100]}")
    elif kind == "premarket":
        b.alerts.append(f"{watchlist_path} 为空，无自选股可检查")

    # 4. 纪律（盘后才需要）
    if kind == "postmarket":
        try:
            r = COMMANDS["review"]({"journal_path": journal_path})
            b.facts["discipline"] = r.data
            for f in r.data.get("flags", []):
                b.alerts.append(f)
            if r.data.get("n_records", 0) == 0:
                b.alerts.append("交易日志为空 —— 没有事前承诺就没有复盘可言")
        except Exception as e:  # noqa: BLE001
            b.facts["discipline"] = {"error": str(e)[:150]}

    # 5. 数据体检（有本地行情时）
    try:
        p = COMMANDS["preflight"]({})
        b.facts["preflight"] = p.data
        for d in p.data.get("dead", []):
            b.alerts.append(f"数据能力失效 · {d['capability']}：{d['detail']}")
    except Exception:  # noqa: BLE001 - 没落地历史数据是正常状态，不算异常
        b.facts["preflight"] = None

    # 去重但保序：同一个问题从多个检查冒出来是常态（比如日历过期），
    # 重复三遍只会让人跳过整段告警
    seen: set[str] = set()
    b.alerts = [a for a in b.alerts if not (a in seen or seen.add(a))]
    return b


def render_text(b: Brief) -> str:
    """不依赖 LLM 的人类可读版本。LLM 挂了你收到的就是这个。"""
    title = "盘前情报" if b.kind == "premarket" else "盘后复盘"
    L = ["=" * 60, f"  {title}   {b.generated_at[:16]}", "=" * 60, ""]

    s = b.facts.get("session") or {}
    L.append(f"市场状态 : {'交易日' if s.get('is_trading_day') else '非交易日'}"
             f"  时段 {s.get('session', '?')}  建议 {s.get('recommended_action', '?')}")

    if b.alerts:
        L += ["", "【需要注意】"]
        L += [f"  · {a}" for a in b.alerts]

    sc = b.facts.get("screen")
    if sc and "detail" in sc:
        L += ["", f"【自选股排雷】共 {sc['checked']} 只"]
        for r in sc["detail"]:
            mark = r["结论"]
            extra = f"  {r['踩雷']}" if r["踩雷"] != "—" else (
                f"  提示: {r['提示']}" if r["提示"] != "—" else "")
            L.append(f"  {mark} {r['代码']} {r['名称']}{extra}")
        if sc.get("not_found"):
            L.append(f"  未找到（可能已退市或代码有误）: {sc['not_found']}")
        L.append("  注：'✓ 通过'只代表没踩这几类雷，不代表推荐买入。")

    d = b.facts.get("discipline")
    if d and d.get("n_records"):
        L += ["", "【纪律】",
              f"  记录 {d['n_records']} 笔（{d['date_range'][0]} ~ {d['date_range'][1]}）",
              f"  临时起意占比 {d['discretionary_ratio']:.1%}"]
        if d.get("impulsive_ratio") is not None:
            L.append(f"  冲动交易占比 {d['impulsive_ratio']:.1%}")

    if b.narrative:
        L += ["", "【AI 解读】", b.narrative]
    elif b.llm_error:
        L += ["", f"（本地模型未接入或调用失败：{b.llm_error[:120]}）",
              "  以上事实部分不受影响。"]

    L += ["", "-" * 60,
          "本简报只提供情报，不构成投资建议，不含买卖推荐。"]
    return "\n".join(L)


def narrate(b: Brief, llm=None) -> Brief:
    """可选：让本地 Hermes 基于已采集的事实写一段解读。

    注意传给模型的是**已经采集好的事实**，不让它自己去调工具 ——
    简报是定时任务，要的是确定性输出，不是让模型每天自由发挥调用哪些工具。
    工具调用留给交互式问答（copilot.local_llm.run_agent）。
    """
    from .copilot.local_llm import LocalLLM

    llm = llm or LocalLLM()
    payload = json.dumps({"alerts": b.alerts, "facts": b.facts},
                         ensure_ascii=False, default=str)[:4000]
    prompt = (
        "以下是今日 A 股情报的原始事实（JSON）。请用中文写一段 120 字以内的解读。\n\n"
        "规则：\n"
        "1. 只陈述事实中已有的内容，不要补充任何数字或个股信息\n"
        "2. 绝不给出买卖建议、不预测涨跌、不推荐个股\n"
        "3. 先说需要用户注意的问题，再说其余\n"
        "4. 如果 alerts 为空且一切正常，就说'无异常'，不要硬凑内容\n\n"
        f"```json\n{payload}\n```"
    )
    try:
        resp = llm.chat([{"role": "user", "content": prompt}], use_tools=False)
        b.narrative = (resp.get("choices", [{}])[0]
                       .get("message", {}).get("content", "") or "").strip()
    except Exception as e:  # noqa: BLE001 - LLM 挂了不该让简报失败
        b.llm_error = str(e)
    return b


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    kind = argv[0] if argv and argv[0] in ("premarket", "postmarket") else "premarket"
    as_json = "--json" in argv
    use_llm = "--llm" in argv

    b = build_facts(kind)
    if use_llm:
        b = narrate(b)

    print(b.to_json() if as_json else render_text(b))

    # 非交易日返回 3，让调度器区分"跳过"和"故障"
    return 0 if (b.facts.get("session") or {}).get("is_trading_day") else 3


if __name__ == "__main__":
    raise SystemExit(main())
