"""质检评审 Critic（蓝图第六部分）—— 独立于生产 Agent 的交叉复核。

用"看空"视角挑毛病：数据自洽性、合规、幻觉迹象、卖点覆盖度。
给质量分并决定放行/打回。**独立性**通过不同 prompt/规则实现。
"""
from __future__ import annotations

from ..models import Product, ScoreCard, ContentPack, CriticVerdict


def review_score(p: Product, card: ScoreCard) -> CriticVerdict:
    issues: list[str] = []
    q = 100.0

    # 1) 自洽性：总分应落在各维加权范围
    if not (0 <= card.total <= 1):
        issues.append("总分越界，评分引擎异常")
        q -= 40
    # 2) 反幻觉：标签与维度是否矛盾
    if "高利润" in card.tags and card.dims.get("margin", 0) < 0.6:
        issues.append("标注高利润但毛利维度分不足，疑似标签幻觉")
        q -= 25
    if "蓝海" in card.tags and card.dims.get("competition", 0) < 0.6:
        issues.append("标注蓝海但竞争维度不宽松，矛盾")
        q -= 25
    # 3) 风险完整性
    if p.return_rate > 0.20 and not any("退货" in r for r in card.risks):
        issues.append("高退货率未在风险中体现")
        q -= 15
    # 4) 理由存在性
    if not card.rationale or len(card.rationale) < 10:
        issues.append("缺少可解释理由")
        q -= 10

    q = max(0.0, q)
    return CriticVerdict(target="score", spu_id=card.spu_id, quality=q,
                         approved=q >= 60 and not any("越界" in i for i in issues),
                         issues=issues)


def review_content(p: Product, pack: ContentPack) -> CriticVerdict:
    issues: list[str] = []
    q = 100.0

    if not pack.compliance_passed:
        issues.append(f"合规未通过: {pack.compliance_hits}")
        q -= 60
    if len(pack.selling_points) < 3:
        issues.append("卖点不足 3 条")
        q -= 20
    if p.pain_points and not any(
        any(pt[:2] in sp for sp in pack.selling_points + [pack.video_script])
        for pt in p.pain_points
    ):
        issues.append("卖点未覆盖已知用户痛点")
        q -= 15
    if len(pack.titles) < 2:
        issues.append("标题版本不足，无法 A/B")
        q -= 10

    q = max(0.0, q)
    # 合规是硬否决
    return CriticVerdict(target="content", spu_id=pack.spu_id, quality=q,
                         approved=q >= 60 and pack.compliance_passed, issues=issues)
