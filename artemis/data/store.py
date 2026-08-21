"""本地 parquet 数据仓库。

按年分区存储，支持增量更新。目的很实际：AkShare 拉全市场十年日线
要跑几个小时，你不会想每次研究都重拉一遍。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .schema import validate_bars


class BarStore:
    def __init__(self, root: str | Path = "./data_cache"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, year: int) -> Path:
        return self.root / f"bars_{year}.parquet"

    def write(self, bars: pd.DataFrame) -> list[Path]:
        """按年写入/合并。同 (date, code) 以新数据为准。"""
        bars = validate_bars(bars, strict=False)
        written = []
        years = bars.index.get_level_values("date").year
        for y in sorted(set(years)):
            chunk = bars[years == y]
            p = self._path(int(y))
            if p.exists():
                old = pd.read_parquet(p)
                chunk = pd.concat([old[~old.index.isin(chunk.index)], chunk]).sort_index()
            chunk.to_parquet(p)
            written.append(p)
        return written

    def read(self, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        files = sorted(self.root.glob("bars_*.parquet"))
        if not files:
            raise FileNotFoundError(f"{self.root} 下没有数据，请先落地行情")
        if start or end:
            y0 = pd.Timestamp(start).year if start else 0
            y1 = pd.Timestamp(end).year if end else 9999
            files = [f for f in files if y0 <= int(f.stem.split("_")[1]) <= y1]
        df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
        d = df.index.get_level_values("date")
        if start:
            df = df[d >= pd.Timestamp(start)]
            d = df.index.get_level_values("date")
        if end:
            df = df[d <= pd.Timestamp(end)]
        return df

    def coverage(self) -> pd.DataFrame:
        """报告已落地的数据范围，方便判断要不要增量更新。"""
        rows = []
        for f in sorted(self.root.glob("bars_*.parquet")):
            df = pd.read_parquet(f, columns=["close"])
            d = df.index.get_level_values("date")
            rows.append({
                "file": f.name,
                "start": d.min().date(),
                "end": d.max().date(),
                "rows": len(df),
                "codes": df.index.get_level_values("code").nunique(),
                "mb": round(f.stat().st_size / 1e6, 1),
            })
        return pd.DataFrame(rows)
