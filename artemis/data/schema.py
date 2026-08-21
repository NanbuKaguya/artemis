"""统一数据契约。

所有数据源（AkShare / Tushare / QMT / 合成）都必须产出这个结构，
上层代码只认契约不认数据源。换数据源时不用改任何策略代码。
"""

from __future__ import annotations

import pandas as pd

# 日频行情：MultiIndex (date, code)
BAR_COLUMNS = {
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",       # 股
    "amount": "float64",       # 元
    "prev_close": "float64",   # 前收盘（用于算涨跌停，必须是除权后的）
    "adj_factor": "float64",   # 后复权因子
    "is_st": "bool",
    "is_suspended": "bool",
    "is_tradable": "bool",     # 当日是否在上市状态（退市后为 False）
    "days_since_ipo": "int64",
    "total_mv": "float64",     # 总市值（元）
    "float_mv": "float64",     # 流通市值（元）
    "industry": "object",      # 行业代码/名称
}

REQUIRED_BAR_COLS = list(BAR_COLUMNS.keys())


class SchemaError(ValueError):
    pass


def validate_bars(df: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    """校验并规范化行情表。

    这个函数是防未来函数的第一道闸门：它检查索引单调、无重复、
    prev_close 与前一日 close 一致。数据错了，后面所有结论都是错的。
    """
    if not isinstance(df.index, pd.MultiIndex) or list(df.index.names) != ["date", "code"]:
        raise SchemaError("行情表索引必须是 MultiIndex(date, code)")

    missing = [c for c in REQUIRED_BAR_COLS if c not in df.columns]
    if missing:
        if strict:
            raise SchemaError(f"缺少必需列: {missing}")
        for c in missing:
            df[c] = pd.NA

    if df.index.duplicated().any():
        dup = df.index[df.index.duplicated()][:5].tolist()
        raise SchemaError(f"存在重复的 (date, code): {dup}")

    df = df.sort_index()

    # 价格合理性：high >= max(open, close) >= min(open, close) >= low
    bad = (df["high"] < df[["open", "close"]].max(axis=1) - 1e-6) | (
        df["low"] > df[["open", "close"]].min(axis=1) + 1e-6
    )
    bad = bad & ~df["is_suspended"].astype(bool)
    if bad.any():
        n = int(bad.sum())
        if strict:
            raise SchemaError(f"{n} 行 OHLC 关系非法（high/low 不包住 open/close）")

    return df


def assert_no_lookahead(signal: pd.Series, bars: pd.DataFrame, lag: int = 1) -> None:
    """断言信号相对行情有足够滞后。

    用法：在生成交易信号后调用。它检查信号的日期集合，确认每个信号
    在使用时至少滞后 lag 个交易日 —— 即 T 日收盘后算出的信号，
    最早只能在 T+1 开盘执行。
    """
    if signal.empty:
        return
    sig_dates = signal.index.get_level_values("date").unique()
    bar_dates = bars.index.get_level_values("date").unique()
    future = sig_dates[sig_dates > bar_dates.max()]
    if len(future) > 0:
        raise SchemaError(f"信号日期超出行情范围，疑似未来函数: {list(future[:3])}")
