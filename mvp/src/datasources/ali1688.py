"""1688 开放平台数据源 —— 补齐供应链字段（supply_price/supplier_rating/ship_hours）。

函数级 TODO 桩。⚠️ 前置（人类）：1688 开放平台注册应用拿 appKey/appSecret。
职责：不产生候选品，只**补齐**其他源缺的供应链字段（enrich 模式）。
"""
from __future__ import annotations

import os
from pathlib import Path

from ..models import Product
from .base import RateLimiter, TTLCache

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "ali1688"


class Ali1688Enricher:
    """用法: enriched = Ali1688Enricher().enrich(product)。失败返回原品并打标。"""

    def __init__(self):
        self.app_key = os.getenv("ALI1688_APP_KEY", "")
        self.app_secret = os.getenv("ALI1688_APP_SECRET", "")
        self.rl = RateLimiter(rate_per_min=20)
        self.cache = TTLCache(_CACHE_DIR, ttl_seconds=24 * 3600)

    @property
    def available(self) -> bool:
        return bool(self.app_key and self.app_secret)

    # ---- TODO(Codex) ----

    def search_supply(self, title: str) -> list[dict]:
        """TODO(Codex-4): 调 1688 关键词搜索 API（com.alibaba.product:alibaba.product.search）
        按 title 找同款货源，返回按"成交量×评分"排序的前 5 个 offer。
        走 rl+cache；签名规则按 1688 开放平台文档（HMAC-SHA1）。"""
        raise NotImplementedError

    def enrich(self, p: Product) -> Product:
        """TODO(Codex-5): 取 search_supply 第一名 offer，回填:
             supply_price   ← offer 批发价（取起订量档位价）
             supplier_rating← 综合评分归一 0~1
             ship_hours     ← 承诺发货时效
           找不到货源: 保持原值并在 p.pain_points 外的日志中记录"无货源"，
           （supply_price 保持 -1 会被 hunter 硬门槛拦下，符合宁缺毋假）。"""
        raise NotImplementedError
