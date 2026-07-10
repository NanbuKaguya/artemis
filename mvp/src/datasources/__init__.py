"""数据源注册表 —— hunter 只认这里，新增源在 SOURCES 注册即接入全链路。

回退策略：真实源不可用（无 token/异常）自动回退 mock，保证系统永远可跑。
"""
from __future__ import annotations

from ..models import Product
from .base import DataSource
from .mock import MockSource


def _real_sources() -> list[DataSource]:
    sources: list[DataSource] = []
    try:
        from .chanmama import ChanmamaSource
        s = ChanmamaSource()
        if s.available:
            sources.append(s)
    except NotImplementedError:
        pass
    # TODO(Codex): 飞瓜/灰豚/巨量算数源按同样模式注册
    return sources


def fetch_all_candidates(category: str = "", limit: int = 100) -> list[Product]:
    """聚合所有可用源的候选品；真实源为空时回退 mock。按 spu_id 去重。"""
    products: list[Product] = []
    for src in _real_sources():
        try:
            products.extend(src.fetch_candidates(category, limit))
        except Exception:   # noqa: BLE001 —— 单源故障不拖垮全链路
            continue

    if not products:
        products = MockSource().fetch_candidates(category, limit)

    seen: set[str] = set()
    unique = []
    for p in products:
        if p.spu_id not in seen:
            unique.append(p)
            seen.add(p.spu_id)
    return unique
