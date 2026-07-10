"""七维选品评分引擎 —— 确定性、可解释、可校准。

对应蓝图第四部分 4.2。评分逻辑走代码（防幻觉），LLM 只在 Scorer 里补"理由文本"。
权重可由实盘胜率反向校准（见 memory.py 的 calibrate_weights）。
"""
from __future__ import annotations

import math

from .models import Product, MarginCard, ScoreCard

# 七维初始权重（经验值，Σ=1）。后续由实盘反馈校准。
DEFAULT_WEIGHTS = {
    "demand": 0.18,        # 市场需求
    "growth": 0.22,        # 增长趋势（抖音节奏快，给最高权重）
    "competition": 0.16,   # 竞争程度（取 1-竞争强度）
    "margin": 0.20,        # 毛利空间
    "content": 0.10,       # 内容传播潜力
    "supply": 0.08,        # 供应稳定性
    "lifecycle": 0.06,     # 生命周期健康度
}

_LIFECYCLE_SCORE = {
    "introduction": 0.85,   # 导入期：早鸟红利
    "growth": 1.0,          # 成长期：最佳窗口
    "mature": 0.45,         # 成熟期：内卷
    "decline": 0.10,        # 衰退期：规避
}


def _norm_log(x: float, cap: float) -> float:
    """对数归一到 0~1，cap 为参考上限。"""
    if x <= 0:
        return 0.0
    return min(1.0, math.log1p(x) / math.log1p(cap))


def _demand_score(p: Product) -> float:
    # 用品类 GMV 体量做对数归一（1000 万为参考上限）
    return _norm_log(p.gmv_30d, cap=1e7)


def _growth_score(p: Product) -> float:
    # 增速 + 加速度加成。增速 50% 记满，加速为正额外 +0.15
    base = max(0.0, min(1.0, p.growth_rate_4w / 0.5))
    accel_bonus = 0.15 if p.growth_accel > 0 else -0.10
    return max(0.0, min(1.0, base + accel_bonus))


def _competition_score(p: Product) -> float:
    # 竞争强度 = 在售密度 × 头部集中度，得分取 1 - 强度
    density = _norm_log(p.on_sale_count, cap=5000)
    intensity = 0.6 * density + 0.4 * p.head_concentration
    return max(0.0, 1.0 - intensity)


def _margin_score(m: MarginCard) -> float:
    # 毛利率 40% 记满；并要求盈亏平衡 ROI 可控
    rate_score = max(0.0, min(1.0, m.gross_margin_rate / 0.40))
    roi_penalty = 0.0 if m.breakeven_roi <= 2.5 else 0.2
    return max(0.0, rate_score - roi_penalty)


def _content_score(p: Product) -> float:
    # 有明确痛点 = 有内容钩子；痛点越多传播潜力越高
    return max(0.0, min(1.0, 0.4 + 0.2 * len(p.pain_points)))


def _supply_score(p: Product) -> float:
    ship = 1.0 if p.ship_hours <= 48 else max(0.0, 1 - (p.ship_hours - 48) / 72)
    ret = max(0.0, 1 - p.return_rate / 0.30)   # 退货率 30% 记 0
    return round(0.4 * p.supplier_rating + 0.3 * ship + 0.3 * ret, 4)


def _lifecycle_score(p: Product) -> float:
    return _LIFECYCLE_SCORE.get(p.lifecycle_stage, 0.5)


def score_product(p: Product, m: MarginCard, weights: dict | None = None) -> ScoreCard:
    w = weights or DEFAULT_WEIGHTS
    dims = {
        "demand": round(_demand_score(p), 4),
        "growth": round(_growth_score(p), 4),
        "competition": round(_competition_score(p), 4),
        "margin": round(_margin_score(m), 4),
        "content": round(_content_score(p), 4),
        "supply": round(_supply_score(p), 4),
        "lifecycle": round(_lifecycle_score(p), 4),
    }
    total = round(sum(dims[k] * w[k] for k in dims), 4)

    tags = _classify(dims, m)
    risks = _risks(p, m, dims)
    return ScoreCard(spu_id=p.spu_id, dims=dims, total=total, tags=tags, risks=risks)


def _classify(dims: dict, m: MarginCard) -> list[str]:
    """四类目标判定（在总分之上的过滤器）。"""
    tags = []
    if dims["growth"] >= 0.75 and dims["competition"] >= 0.5 and dims["content"] >= 0.6:
        tags.append("潜力爆品")
    if dims["competition"] >= 0.7 and dims["demand"] >= 0.4 and dims["growth"] >= 0.5:
        tags.append("蓝海")
    if dims["margin"] >= 0.7:
        tags.append("高利润")
    if dims["growth"] >= 0.6 and dims["lifecycle"] >= 0.8:
        tags.append("上升趋势")
    return tags


def _risks(p: Product, m: MarginCard, dims: dict) -> list[str]:
    risks = []
    if m.gross_margin <= 0:
        risks.append("毛利为负")
    if dims["competition"] < 0.3:
        risks.append("红海竞争，新号破局难")
    if p.return_rate > 0.20:
        risks.append(f"退货率高（{p.return_rate:.0%}），售后风险")
    if p.lifecycle_stage == "decline":
        risks.append("品类处于衰退期")
    if p.ship_hours > 72:
        risks.append("发货时效差，影响体验分")
    return risks
