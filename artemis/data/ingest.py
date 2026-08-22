"""真实数据的规模化落地。

朴素的"for code in codes: fetch(code)"在真实规模下不可用：
5000 只股票 × 10 年日线，串行拉取要跑十几个小时，中途被限频掐断一次
就得从头再来。这个模块解决三件事：

1. **增量**   —— 已经落地的日期不再重拉，每天只补新增的部分
2. **并发限流** —— AkShare 走公开网页接口，并发太高会被封 IP。
                   这里用令牌桶控制真实速率，而不是简单的 sleep
3. **断点续传** —— 每只股票拉完就落地并更新清单，任何时候中断都能续上

首次全量建议过夜跑；之后每天收盘后增量更新只需几分钟。
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from .store import BarStore
from .schema import validate_bars


class RateLimiter:
    """令牌桶限流。控制的是真实请求速率，不是每次调用后傻等。"""

    def __init__(self, rate_per_sec: float = 4.0, burst: int = 4):
        self.rate = rate_per_sec
        self.capacity = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.rate
            else:
                wait = 0.0
                self._tokens -= 1.0
        if wait > 0:
            time.sleep(wait)
            self.acquire()


@dataclass
class Manifest:
    """落地清单：记录每只股票已覆盖的日期范围与最后更新时间。"""

    path: Path
    entries: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Manifest":
        p = Path(path)
        if p.exists():
            return cls(path=p, entries=json.loads(p.read_text(encoding="utf-8")))
        return cls(path=p, entries={})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1), encoding="utf-8")

    def covered_end(self, code: str) -> pd.Timestamp | None:
        e = self.entries.get(code)
        return pd.Timestamp(e["end"]) if e and e.get("end") else None

    def update(self, code: str, start: str, end: str, rows: int) -> None:
        prev = self.entries.get(code, {})
        self.entries[code] = {
            "start": min(prev.get("start", start), start),
            "end": max(prev.get("end", end), end),
            "rows": prev.get("rows", 0) + rows,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def mark_failed(self, code: str, reason: str) -> None:
        e = self.entries.setdefault(code, {})
        e["last_error"] = reason[:120]
        e["failed_at"] = datetime.now().isoformat(timespec="seconds")

    def failures(self) -> list[str]:
        return [c for c, e in self.entries.items() if e.get("last_error")]


class Ingestor:
    """增量、并发、可续传的行情落地器。

    source 需实现 daily_bars_one(code, start, end) -> DataFrame（契约格式）。
    AkshareSource 已满足；换 Tushare 只需实现同一个方法。
    """

    def __init__(
        self,
        source,
        store: BarStore,
        manifest_path: str | Path | None = None,
        max_workers: int = 4,
        rate_per_sec: float = 4.0,
        flush_every: int = 100,
    ):
        self.source = source
        self.store = store
        self.manifest = Manifest.load(
            manifest_path or Path(store.root) / "manifest.json"
        )
        self.max_workers = max_workers
        self.limiter = RateLimiter(rate_per_sec, burst=max(2, max_workers))
        self.flush_every = flush_every
        self._lock = threading.Lock()

    def _fetch_one(self, code: str, start: str, end: str) -> tuple[str, pd.DataFrame | None, str | None]:
        self.limiter.acquire()
        try:
            df = self.source.daily_bars_one(code, start, end)
            return code, df, None
        except Exception as e:  # noqa: BLE001 - 上游异常类型不稳定
            return code, None, str(e)

    def _effective_end(self, end: str, calendar: pd.DatetimeIndex | None) -> pd.Timestamp:
        """把日历日 end 折算成"最后一个可能有数据的交易日"。

        为什么必须做这件事：end 常常落在周末或假期上（比如季末 3/31 是周日）。
        直接拿日历日比较的话，manifest 里记录的最后交易日永远 < end，
        于是每只股票每天都会被重新请求一次 —— 5000 只股票就是 5000 次
        无效请求，正好撞在限频上，还会把真正需要增量的请求挤掉。
        """
        end_ts = pd.Timestamp(end)
        if calendar is None:
            try:
                calendar = self.source.trade_calendar("2000-01-01", end)
            except Exception:  # noqa: BLE001 - 数据源可能不提供日历
                calendar = None
        if calendar is not None and len(calendar):
            valid = calendar[calendar <= end_ts]
            if len(valid):
                return pd.Timestamp(valid.max())
        # 没有交易日历时退化为"最后一个工作日"，至少能挡掉周末
        return pd.Timestamp(pd.bdate_range(end_ts - pd.Timedelta(days=7), end_ts).max())

    def run(
        self,
        codes: list[str],
        start: str,
        end: str,
        incremental: bool = True,
        retry_failed: bool = True,
        verbose: bool = True,
        calendar: pd.DatetimeIndex | None = None,
    ) -> pd.DataFrame:
        """落地行情。返回本次落地情况的汇总表。

        incremental=True 时，已覆盖到最后交易日的股票会被跳过；
        部分覆盖的股票只拉缺失的尾部区间。

        calendar: 交易日历。不传则尝试从数据源获取，再退化为工作日。
        """
        end_ts = self._effective_end(end, calendar)
        if verbose and end_ts != pd.Timestamp(end):
            print(f"增量基准日：{end_ts.date()}（{end} 非交易日）")
        todo: list[tuple[str, str, str]] = []
        skipped = 0

        for c in codes:
            s = start
            if incremental:
                cov = self.manifest.covered_end(c)
                if cov is not None:
                    if cov >= end_ts:
                        skipped += 1
                        continue
                    # 从已覆盖的次日开始补
                    s = (cov + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            todo.append((c, s, end))

        if retry_failed:
            failed = set(self.manifest.failures())
            for c in failed:
                if c in codes and not any(t[0] == c for t in todo):
                    todo.append((c, start, end))

        if verbose:
            print(f"待拉取 {len(todo)} 只，跳过（已最新）{skipped} 只，"
                  f"并发 {self.max_workers}，限速 {self.limiter.rate}/秒")

        buffer: list[pd.DataFrame] = []
        ok = failed_n = empty = 0
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = {ex.submit(self._fetch_one, c, s, e): c for c, s, e in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                code, df, err = fut.result()
                with self._lock:
                    if err:
                        self.manifest.mark_failed(code, err)
                        failed_n += 1
                    elif df is None or df.empty:
                        empty += 1
                    else:
                        buffer.append(df)
                        d = df.index.get_level_values("date")
                        self.manifest.update(code, str(d.min().date()), str(d.max().date()), len(df))
                        self.manifest.entries[code].pop("last_error", None)
                        ok += 1

                    if len(buffer) >= self.flush_every:
                        self._flush(buffer)
                        buffer = []
                        self.manifest.save()

                if verbose and i % 200 == 0:
                    rate = i / max(time.time() - t0, 1e-9)
                    eta = (len(todo) - i) / max(rate, 1e-9)
                    print(f"  {i}/{len(todo)}  成功 {ok} 失败 {failed_n}  "
                          f"{rate:.1f} 只/秒  预计剩余 {eta/60:.0f} 分钟")

        if buffer:
            self._flush(buffer)
        self.manifest.save()

        summary = pd.DataFrame([{
            "计划拉取": len(todo), "跳过(已最新)": skipped, "成功": ok,
            "无数据": empty, "失败": failed_n, "耗时(分钟)": round((time.time() - t0) / 60, 1),
        }])
        if verbose:
            print(summary.to_string(index=False))
            if failed_n:
                print(f"  失败的股票已记入清单，下次运行会自动重试："
                      f"{self.manifest.failures()[:5]}{' ...' if failed_n > 5 else ''}")
        return summary

    def _flush(self, frames: list[pd.DataFrame]) -> None:
        if not frames:
            return
        df = pd.concat(frames).sort_index()
        self.store.write(validate_bars(df, strict=False))

    def coverage_report(self) -> pd.DataFrame:
        """落地覆盖情况。用来判断数据是否可以开始研究。"""
        if not self.manifest.entries:
            return pd.DataFrame()
        rows = [{"code": c, **e} for c, e in self.manifest.entries.items()]
        df = pd.DataFrame(rows)
        for col in ("start", "end"):
            if col in df:
                df[col] = pd.to_datetime(df[col])
        return df
