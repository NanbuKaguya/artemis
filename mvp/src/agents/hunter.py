"""① 爆品发现 Hunter（蓝图 3.2）。

职责：在选定赛道内挖候选商品（SPU），做硬门槛过滤 + 去重。
输入：数据源注册表 datasources（真实源不可用时自动回退 mock）。
输出：通过硬门槛的候选 Product 列表。
"""
from __future__ import annotations

from ..models import Product
from .. import datasources

# 禁售/高危类目关键词（硬门槛直接淘汰）
FORBIDDEN = ["处方药", "烟草", "医疗器械三类", "隐形眼镜"]


def _load_candidates() -> list[Product]:
    return datasources.fetch_all_candidates()


def hard_filter(p: Product) -> tuple[bool, str]:
    """硬门槛：货源可得 / 非禁售 / 毛利为正的粗筛。"""
    if any(f in p.category or f in p.title for f in FORBIDDEN):
        return False, "禁售/高危类目"
    if p.supply_price <= 0:
        return False, "供货价缺失（待 1688 源补齐），宁缺毋假"
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
