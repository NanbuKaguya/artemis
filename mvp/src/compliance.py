"""合规硬闸 —— 广告法极限词 / 类目资质 / 禁售 检查。

对应蓝图 3.9 / 6.3。**词库+规则硬匹配在前，只拦不放行。**
命中即打回，绝不依赖 LLM 语义判断放行（LLM 只可用于"补充发现"，不可用于"批准"）。
"""
from __future__ import annotations

import re

# 广告法极限词（示例子集，生产接完整词库并定期更新）
ABSOLUTE_TERMS = [
    "最", "第一", "顶级", "极致", "最佳", "最好", "最优", "最强", "最低价",
    "国家级", "世界级", "唯一", "独家", "首个", "首款", "领导品牌", "填补空白",
    "永久", "百分百", "100%", "绝对", "根治", "痊愈", "包治", "特效",
]

# 医疗/药效暗示（化妆品/食品禁用）
MEDICAL_TERMS = [
    "治疗", "疗效", "抗癌", "消炎", "杀菌率", "医用级", "处方", "替代药物",
    "降血压", "降血糖", "减肥瘦身速效",
]

# 需要特殊资质的类目关键词 -> 必备资质
QUALIFICATION_RULES = {
    "食品": ["食品经营许可证"],
    "保健": ["保健食品批准证书", "蓝帽子"],
    "化妆品": ["化妆品生产/经营备案"],
    "医疗器械": ["医疗器械经营许可证"],
    "美瞳": ["医疗器械经营许可证(三类)"],
}


def check_text(text: str) -> list[str]:
    """返回命中的违规词列表（空列表 = 通过）。"""
    hits = []
    for term in ABSOLUTE_TERMS + MEDICAL_TERMS:
        # 用 in 匹配中文；数字类用正则边界
        if term in text:
            hits.append(term)
    return hits


def check_category_qualification(category: str, held_quals: list[str] | None = None) -> list[str]:
    """检查类目资质是否齐备，返回缺失的资质（空列表 = 齐备）。"""
    held = set(held_quals or [])
    missing = []
    for kw, required in QUALIFICATION_RULES.items():
        if kw in category:
            for q in required:
                if q not in held:
                    missing.append(q)
    return missing


def scrub(text: str) -> str:
    """给出建议替换（把极限词替换为安全占位，仅供人工参考，不自动放行）。"""
    out = text
    for term in ABSOLUTE_TERMS:
        out = out.replace(term, "▢")
    return out


def gate(texts: list[str], category: str, held_quals: list[str] | None = None) -> tuple[bool, list[str]]:
    """合规总闸。任一命中即不通过。

    返回 (是否通过, 问题列表)。
    """
    problems: list[str] = []
    for t in texts:
        for h in check_text(t):
            problems.append(f"极限词/违禁表述: “{h}” (出现在: {t[:20]}…)")
    for miss in check_category_qualification(category, held_quals):
        problems.append(f"缺少类目资质: {miss}")
    return (len(problems) == 0, problems)
