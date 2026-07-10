"""③ 评论洞察 VoC（蓝图 3.3）—— 从差评挖真实痛点，替换模板卖点。

已实现：extract_pain_points() 离线词频版（确定性兜底）。
TODO 桩：评论获取 + 向量聚类升级。
"""
from __future__ import annotations

from collections import Counter

# 差评高频信号词 → 痛点归类（离线兜底词表，生产由聚类替代）
_PAIN_LEXICON = {
    "痛点:质量差": ["坏了", "断了", "开裂", "掉色", "变形", "质量差"],
    "痛点:效果不符": ["没效果", "不明显", "夸大", "货不对板", "色差"],
    "痛点:物流慢": ["发货慢", "物流慢", "迟迟", "不发货"],
    "痛点:气味/刺激": ["刺鼻", "过敏", "刺痛", "味道大"],
    "痛点:难用": ["不好用", "麻烦", "复杂", "说明书"],
}


def extract_pain_points(comments: list[str], top_k: int = 5) -> list[str]:
    """离线确定性版：词表命中计数 → Top K 痛点。生产版见 TODO(Codex-13)。"""
    counter: Counter[str] = Counter()
    for c in comments:
        for pain, kws in _PAIN_LEXICON.items():
            if any(kw in c for kw in kws):
                counter[pain] += 1
    return [p for p, _n in counter.most_common(top_k)]


# ---- TODO(Codex) ----

def fetch_comments(spu_id: str, competitor_urls: list[str]) -> list[str]:
    """TODO(Codex-12): 拉竞品评论。优先第三方合规 API；抓取必须
    RateLimiter 限频 + 只取评论文本（不碰用户个人信息，合规红线）。"""
    raise NotImplementedError


def cluster_pain_points(comments: list[str], top_k: int = 5) -> list[str]:
    """TODO(Codex-13): 生产版 —— embedding + 聚类(HDBSCAN/K-means)
    → 每簇用 LLM 归纳一句痛点（bulk 模型）→ 按簇大小排序取 Top K。
    LLM 只做"归纳文本"，簇大小/排序走代码。失败回退 extract_pain_points。"""
    raise NotImplementedError
