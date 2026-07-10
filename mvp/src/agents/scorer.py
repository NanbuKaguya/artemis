"""② 选品评分 Scorer（蓝图 3.7 / 第四部分）。

职责：调用确定性利润引擎 + 七维评分引擎，产出可解释评分卡与 Top 榜。
数值全部走代码（margin.py / scoring.py），LLM 只补"理由文本"。
"""
from __future__ import annotations

from ..models import Product, ScoreCard
from ..margin import compute_margin
from ..scoring import score_product
from .. import memory, llm


def _rationale_offline(p: Product, card: ScoreCard) -> str:
    top_dims = sorted(card.dims.items(), key=lambda kv: kv[1], reverse=True)[:3]
    dim_cn = {
        "demand": "市场需求", "growth": "增长趋势", "competition": "竞争宽松",
        "margin": "毛利空间", "content": "内容传播", "supply": "供应稳定", "lifecycle": "生命周期",
    }
    strengths = "、".join(f"{dim_cn[k]}({v:.2f})" for k, v in top_dims)
    tag = "、".join(card.tags) if card.tags else "常规候选"
    return (f"该品综合分 {card.total:.2f}，标签[{tag}]。核心优势：{strengths}。"
            f"{'风险：' + '；'.join(card.risks) if card.risks else '无显著风险。'}")


def _rationale_llm(p: Product, card: ScoreCard) -> str:
    system = ("你是抖音电商选品分析师。基于给定的七维评分与利润数据，"
              "用 2~3 句话给出该品是否值得测试的理由。只解释，不编造新数字。")
    user = f"商品:{p.title}\n评分:{card.dims}\n总分:{card.total}\n标签:{card.tags}\n风险:{card.risks}"
    out = llm.complete(system, user, task="reasoning", temperature=0.4)
    return _rationale_offline(p, card) if llm.is_offline(out) else out


def score_one(p: Product) -> ScoreCard:
    weights = memory.get_weights()          # 用校准后的权重
    margin = compute_margin(p)              # 确定性利润
    card = score_product(p, margin, weights)  # 确定性七维
    card.rationale = _rationale_llm(p, card)  # LLM 仅补理由
    # 把利润关键数字挂到风险/理由，便于人工看
    if margin.gross_margin <= 0:
        card.risks.insert(0, "利润引擎判定毛利为负")
    return card


def run(products: list[Product], top_k: int = 10) -> list[ScoreCard]:
    cards = [score_one(p) for p in products]
    cards.sort(key=lambda c: c.total, reverse=True)
    return cards[:top_k]
