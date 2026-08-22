"""把 LLM 提出的因子假设接进挖掘流水线。

分工是刻意的：
  LLM 负责  —— 提出假设、写清经济逻辑、给出计算方式的自然语言描述
  人负责    —— 把描述翻译成代码（或审核 LLM 写的代码）
  数据负责  —— 裁决

为什么不让 LLM 直接生成可执行代码然后自动跑：
因子代码里最容易出的错是**未来函数**，而它不会报错。让 LLM 生成的代码
不经审核就进流水线，等于把最危险的一类 bug 交给一个看不见结果的环节。
所以这里的桥只做到"结构化的因子规格 + 人工实现清单"，
最后一步的翻译必须有人看过。

研究日志会记录 source="llm"，几个月后你就能回答一个很实际的问题：
LLM 提的假设，命中率到底比我自己拍脑袋高吗？
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from ..alpha.mining import FactorSpec
from ..alpha.research_log import ResearchLog


@dataclass
class HypothesisCard:
    """一条待实现的因子假设。LLM 产出这个，人把它翻译成代码。"""

    name: str
    economic_rationale: str
    formula_description: str
    required_data: list[str]
    expected_decay_days: int
    known_failure_mode: str
    crowding_risk: str

    def to_checklist(self) -> str:
        """给实现者看的清单。每一项都是常见的翻车点。"""
        return "\n".join([
            f"因子名     : {self.name}",
            f"经济逻辑   : {self.economic_rationale}",
            f"计算方式   : {self.formula_description}",
            f"所需数据   : {', '.join(self.required_data)}",
            f"预期半衰期 : {self.expected_decay_days} 天  → 调仓频率不应快于此",
            f"失效场景   : {self.known_failure_mode}",
            f"拥挤风险   : {self.crowding_risk}",
            "",
            "实现前逐条确认：",
            "  [ ] 所有输入都只用 <= T 日收盘的数据（财务数据按公告日，不是报告期）",
            "  [ ] rolling 窗口没有用到 center=True 或负向 shift",
            "  [ ] 方向已统一为「数值越大越该买」",
            "  [ ] 除权除息不会造成假信号（价格用后复权，涨跌停判定用不复权）",
            "  [ ] 极端值和缺失值的处理不会引入横截面偏差",
        ])


def cards_from_llm_response(payload: dict) -> list[HypothesisCard]:
    """把 copilot.agent.generate_hypotheses() 的返回转成卡片。"""
    out = []
    for h in payload.get("hypotheses", []):
        try:
            out.append(HypothesisCard(
                name=h["name"],
                economic_rationale=h["economic_rationale"],
                formula_description=h["formula_description"],
                required_data=list(h.get("required_data", [])),
                expected_decay_days=int(h.get("expected_decay_days", 20)),
                known_failure_mode=h.get("known_failure_mode", "未说明"),
                crowding_risk=h.get("crowding_risk", "未知"),
            ))
        except (KeyError, TypeError, ValueError) as e:
            print(f"  [跳过一条格式不合法的假设] {e}")
    return out


def spec_from_card(
    card: HypothesisCard, fn: Callable[[pd.DataFrame], pd.Series]
) -> FactorSpec:
    """人工实现完成后，把卡片 + 实现函数封成可进流水线的规格。"""
    return FactorSpec(
        name=card.name,
        hypothesis=card.economic_rationale,
        formula=card.formula_description,
        fn=fn,
        source="llm",
    )


def llm_hit_rate(log: ResearchLog) -> pd.DataFrame:
    """LLM 假设 vs 人工假设的命中率对比。

    几个月后这张表会告诉你，AI 在你的研究流程里到底值不值这份 token 钱。
    诚实的答案可能是"不值" —— 那也是有价值的结论。
    """
    return log.by_source()
