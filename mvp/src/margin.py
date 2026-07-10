"""利润测算引擎 —— 确定性代码，绝不让 LLM 心算金额（防幻觉第一红线）。

对应蓝图 3.4 / 6.3。所有金额相关计算都在这里，LLM 只负责取数与解释。
"""
from __future__ import annotations

from .models import Product, MarginCard

# 类目平台抽佣率（示例，生产接抖店实际类目佣金表）
CATEGORY_COMMISSION = {
    "美妆个护": 0.05,
    "服饰内衣": 0.05,
    "食品饮料": 0.02,
    "家居日用": 0.05,
    "3C数码": 0.02,
    "_default": 0.05,
}


def _commission_rate(category: str) -> float:
    top = category.split("/")[0]
    return CATEGORY_COMMISSION.get(top, CATEGORY_COMMISSION["_default"])


def compute_margin(
    p: Product,
    talent_commission_rate: float = 0.10,   # 达人佣金率
    fulfillment_cost: float = 3.0,           # 履约成本（物流+包装，元/件）
    target_net_margin: float = 0.15,         # 目标净利率
) -> MarginCard:
    """计算真实到手利润。

    毛利 = 售价 − 供货价 − 平台佣金 − 达人佣金 − 履约成本 − 退货损耗
    退货损耗按 退货率 × (履约成本 + 部分不可回收成本) 估算。
    """
    price = p.sale_price
    commission = price * _commission_rate(p.category)
    talent_fee = price * talent_commission_rate
    # 退货损耗：退货件的往返物流 + 折旧，保守取 2× 履约成本 × 退货率
    return_loss = p.return_rate * (2 * fulfillment_cost)

    variable_cost = p.supply_price + commission + talent_fee + fulfillment_cost + return_loss
    gross_margin = price - variable_cost
    gross_margin_rate = gross_margin / price if price > 0 else 0.0

    # 盈亏平衡 ROI（千川口径：广告消耗产生的 GMV 需覆盖变动成本）
    breakeven_roi = price / (price - variable_cost) if (price - variable_cost) > 0 else float("inf")
    # 可承受 CAC：毛利中留出目标净利后可用于获客的部分
    affordable_cac = max(0.0, gross_margin * (1 - target_net_margin))

    notes = []
    if gross_margin <= 0:
        notes.append("毛利为负，直接淘汰")
    elif gross_margin_rate < 0.20:
        notes.append("毛利率偏低，投流容错空间小")
    if breakeven_roi != float("inf") and breakeven_roi > 3:
        notes.append(f"盈亏平衡 ROI 高达 {breakeven_roi:.1f}，投流难盈利")

    return MarginCard(
        spu_id=p.spu_id,
        gross_margin=round(gross_margin, 2),
        gross_margin_rate=round(gross_margin_rate, 4),
        breakeven_roi=round(breakeven_roi, 2) if breakeven_roi != float("inf") else 9999.0,
        affordable_cac=round(affordable_cac, 2),
        notes=notes,
    )
