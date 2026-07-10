"""数据源接入层基础设施（P2-数据源，AGENTS.md §3）。

设计要求（蓝图 4.1）：限频、缓存、去重、带时间戳、可回退 mock。
本文件的 RateLimiter / TTLCache / DataSource 契约是**已实现并有测试的**，
新数据源只需继承 DataSource 并实现 fetch_raw + normalize 两个函数。
"""
from __future__ import annotations

import abc
import json
import time
from pathlib import Path

from ..models import Product


class RateLimiter:
    """令牌桶限频器 —— 所有外部 API/抓取必须套上它（合规红线）。

    用法:
        rl = RateLimiter(rate_per_min=30)
        rl.acquire()   # 超速时阻塞等待，绝不突破配额
    """

    def __init__(self, rate_per_min: int, _clock=time.monotonic, _sleep=time.sleep):
        self.interval = 60.0 / max(1, rate_per_min)
        self._clock = _clock
        self._sleep = _sleep
        self._next_ok = 0.0

    def acquire(self) -> float:
        """返回实际等待秒数（测试用注入时钟验证）。"""
        now = self._clock()
        wait = max(0.0, self._next_ok - now)
        if wait > 0:
            self._sleep(wait)
        self._next_ok = max(now, self._next_ok) + self.interval
        return wait


class TTLCache:
    """文件级 TTL 缓存 —— 数据带时间戳，超期作废（防幻觉：过时信息防线）。

    每个 key 存成一个 JSON 文件 {"ts": epoch, "data": ...}。
    """

    def __init__(self, cache_dir: Path, ttl_seconds: float = 6 * 3600, _clock=time.time):
        self.dir = Path(cache_dir)
        self.ttl = ttl_seconds
        self._clock = _clock

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return self.dir / f"{safe}.json"

    def get(self, key: str):
        """命中且未过期返回 data，否则返回 None。"""
        f = self._path(key)
        if not f.exists():
            return None
        try:
            blob = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if self._clock() - blob.get("ts", 0) > self.ttl:
            return None
        return blob.get("data")

    def set(self, key: str, data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(
            json.dumps({"ts": self._clock(), "data": data}, ensure_ascii=False),
            encoding="utf-8",
        )


class DataSource(abc.ABC):
    """数据源契约。新增数据源 = 实现这两个方法 + 在 registry 注册。"""

    name: str = "base"

    @abc.abstractmethod
    def fetch_raw(self, category: str, limit: int) -> list[dict]:
        """拉取原始记录（各源自己的字段名）。必须内部走 RateLimiter+TTLCache。"""

    @abc.abstractmethod
    def normalize(self, raw: dict) -> Product | None:
        """把原始记录映射为统一 Product；缺关键字段返回 None（宁缺毋假——
        绝不为缺失字段编造数值，这是防幻觉红线在数据层的体现）。"""

    def fetch_candidates(self, category: str = "", limit: int = 100) -> list[Product]:
        out: list[Product] = []
        for raw in self.fetch_raw(category, limit):
            p = self.normalize(raw)
            if p is not None:
                out.append(p)
        return out
