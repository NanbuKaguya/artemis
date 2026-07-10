"""Mock 数据源 —— 离线开发/测试/演示的兜底源（永远保留，不要删除）。"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Product
from .base import DataSource

_MOCK = Path(__file__).resolve().parent.parent.parent / "data" / "mock_products.json"


class MockSource(DataSource):
    name = "mock"

    def fetch_raw(self, category: str, limit: int) -> list[dict]:
        rows = json.loads(_MOCK.read_text(encoding="utf-8"))
        if category:
            rows = [r for r in rows if category in r.get("category", "")]
        return rows[:limit]

    def normalize(self, raw: dict) -> Product | None:
        try:
            return Product(**raw)
        except TypeError:
            return None
