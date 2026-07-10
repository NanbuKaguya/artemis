"""① 爆品发现 Hunter（蓝图 3.2）。

职责：在选定赛道内挖候选商品（SPU），做硬门槛过滤 + 去重。
输入：数据源候选池（本 MVP 从 mock 数据/第三方 API 拉取）。
输出：通过硬门槛的候选 Product 列表。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Product

MOCK = Path(__file__).resolve().parent.parent.parent / "data" / "mock_products.json"

# 禁售/高危类目关键词（硬门槛直接淘汰）
FORBIDDEN = ["处方药", "烟草", "医疗器械三类", "隐形眼镜"]


def _load_candidates() -> list[Product]:
    """生产：接蝉妈妈/飞瓜带货榜 + 抖音商城热销榜 API。MVP：读 mock。"""
    rows = json.loads(MOCK.read_text(encoding="utf-8"))
    return [Product(**r) for r in rows]


def hard_filter(p: Product) -> tuple[bool, str]:
    """硬门槛：货源可得 / 非禁售 / 毛利为正的粗筛。"""
    if any(f in p.category or f in p.title for f in FORBIDDEN):
        return False, "禁售/高危类目"
    if p.supply_price >= p.sale_price:
        return False, "供货价≥售价，无毛利空间"
    if p.growth_rate_4w < 0:
        return False, "品类负增长"
    return True, ""


def run(min_growth: float = 0.0) -> list[Product]:
    """返回通过硬门槛的候选池。"""
    candidates = _load_candidates()
    passed: list[Product] = []
    seen_titles: set[str] = set()
    for p in candidates:
        # 简单去重（生产用图像相似度 + 标题聚类）
        key = p.title.strip()
        if key in seen_titles:
            continue
        ok, _reason = hard_filter(p)
        if ok and p.growth_rate_4w >= min_growth:
            passed.append(p)
            seen_titles.add(key)
    return passed
