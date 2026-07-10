"""蝉妈妈数据源（付费第三方带货数据）—— 函数级 TODO 桩，Codex 按序填空。

⚠️ 前置条件（人类完成，Codex 不要自行绕过）：
   1. 购买蝉妈妈 API 套餐，拿到 token 放入 .env 的 CHANMAMA_TOKEN
   2. 只用官方 API，禁止逆向/爬取其网页端（合规红线）

字段映射表（normalize 的唯一依据；接口字段名以你购买的 API 文档为准，
下表是常见命名，Codex 实现时逐一核对，缺失字段返回 None 绝不编造）：

    蝉妈妈字段(参考)            → Product 字段
    ─────────────────────────────────────────────
    product_id                 → spu_id (前缀 "cmm-")
    title                      → title
    category_path              → category
    price                      → sale_price
    (无)                       → supply_price   ← 蝉妈妈没有！由 1688 源补齐,
                                                  补齐前该品只进"待补数据"队列
    sales_amount_30d           → gmv_30d
    sales_trend[]              → growth_rate_4w / growth_accel (用 trend.py 计算)
    author_count               → talent_count
    shop_count                 → on_sale_count (近似)
    top10_shop_ratio           → head_concentration
    (无)                       → supplier_rating/ship_hours (由 1688 源补齐)
    bad_review_ratio           → return_rate (近似代理，标注来源)
    (无)                       → lifecycle_stage (用 trend.py 曲线形态判定)
    comment_keywords[]         → pain_points (负面关键词)
"""
from __future__ import annotations

import os
from pathlib import Path

from ..models import Product
from .base import DataSource, RateLimiter, TTLCache

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "chanmama"
API_BASE = "https://api-service.chanmama.com"   # 以购买的 API 文档为准


class ChanmamaSource(DataSource):
    name = "chanmama"

    def __init__(self):
        self.token = os.getenv("CHANMAMA_TOKEN", "")
        self.rl = RateLimiter(rate_per_min=30)          # 按套餐配额调整
        self.cache = TTLCache(_CACHE_DIR, ttl_seconds=6 * 3600)

    @property
    def available(self) -> bool:
        return bool(self.token)

    # ---- TODO(Codex) 按顺序实现，每个函数一个 commit ----

    def _request(self, path: str, params: dict) -> dict:
        """TODO(Codex-1): HTTP GET 封装。
        步骤: cache.get(key) 命中直接返回 → rl.acquire() → 带 token 请求
              → 非 200/业务错误码抛 DataSourceError → cache.set → 返回 json。
        key 规则: f"{path}_{sorted(params)}"。用 urllib 或 httpx 均可。"""
        raise NotImplementedError("见 docstring 步骤")

    def fetch_raw(self, category: str, limit: int) -> list[dict]:
        """TODO(Codex-2): 调商品榜接口（如 /v1/product/rank，以文档为准），
        翻页拉取至 limit 条。每页调用 self._request。"""
        raise NotImplementedError

    def normalize(self, raw: dict) -> Product | None:
        """TODO(Codex-3): 按文件顶部字段映射表逐字段映射。
        规则: 关键字段(spu_id/title/sale_price/gmv_30d)任一缺失 → return None；
              supply_price 等待补字段先填 -1 并把品放入"待补数据"标记
              （supply_price<0 时 hunter.hard_filter 会拦下，不会误入评分）。"""
        raise NotImplementedError
