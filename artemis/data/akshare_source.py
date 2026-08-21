"""AkShare 数据适配器（在你本机运行）。

设计要点：
1. AkShare 是爬虫聚合，接口名在版本间会漂移、也会被上游网站限频。
   所以这里不硬编码单一函数名，而是"候选名探测"，并提供 doctor()
   报告你当前装的版本到底有哪些能力。
2. 所有产出统一转成 schema.py 的契约，上层策略代码与数据源解耦。
3. 复权：因子计算和收益计算一律用后复权价；涨跌停判定必须用
   未复权的真实价格和真实 prev_close，两者不能混。

限频提醒：AkShare 走的是公开网页接口，批量拉全市场历史请控制并发
（建议 <= 4 线程 + 每股 0.2s 间隔），否则会被封 IP。首次全量落地
建议分夜间跑完，之后只做增量。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .schema import validate_bars

# 每种能力的候选接口名，按优先级排列。AkShare 改名时只需在这里加一行。
CAPABILITIES: dict[str, list[str]] = {
    "stock_list": ["stock_info_a_code_name", "stock_zh_a_spot_em"],
    "daily_bars": ["stock_zh_a_hist", "stock_zh_a_daily"],
    "spot": ["stock_zh_a_spot_em", "stock_zh_a_spot"],
    "trade_calendar": ["tool_trade_date_hist_sina"],
    "index_daily": ["index_zh_a_hist", "stock_zh_index_daily_em", "stock_zh_index_daily"],
    "st_list": ["stock_zh_a_st_em"],
    "industry_list": ["stock_board_industry_name_em"],
    "industry_members": ["stock_board_industry_cons_em"],
    "earnings_forecast": ["stock_yjyg_em"],
    "pledge_ratio": ["stock_gpzy_pledge_ratio_em"],
    "share_unlock": ["stock_restricted_release_queue_em", "stock_restricted_release_detail_em"],
    "financial_abstract": ["stock_financial_abstract_ths", "stock_financial_abstract"],
    "audit_opinion": ["stock_financial_report_sina"],
}


class DataSourceError(RuntimeError):
    pass


def _ak():
    try:
        import akshare as ak
    except ImportError as e:  # pragma: no cover - 环境相关
        raise DataSourceError(
            "未安装 akshare。请先 `pip install akshare --upgrade`。"
        ) from e
    return ak


def resolve(capability: str) -> Callable:
    """把能力名解析成当前 akshare 版本里真实存在的函数。"""
    ak = _ak()
    for name in CAPABILITIES.get(capability, []):
        fn = getattr(ak, name, None)
        if callable(fn):
            return fn
    raise DataSourceError(
        f"当前 akshare 版本不提供能力 '{capability}'（试过 {CAPABILITIES.get(capability)}）。"
        f" 请升级 akshare，或在 CAPABILITIES 中补充新的接口名。"
    )


def doctor() -> pd.DataFrame:
    """体检：报告当前环境下每种能力是否可用。跑不通的数据源要早发现。"""
    ak = _ak()
    rows = []
    for cap, names in CAPABILITIES.items():
        hit = next((n for n in names if callable(getattr(ak, n, None))), None)
        rows.append({"capability": cap, "resolved": hit or "—", "ok": hit is not None})
    df = pd.DataFrame(rows)
    df.attrs["akshare_version"] = getattr(ak, "__version__", "unknown")
    return df


@dataclass
class AkshareSource:
    """AkShare 数据源。

    sleep_sec: 每次请求之间的间隔，防止被上游限频封 IP。
    """

    sleep_sec: float = 0.20
    max_retry: int = 3

    def _call(self, fn: Callable, **kwargs) -> pd.DataFrame:
        last_err: Exception | None = None
        for attempt in range(self.max_retry):
            try:
                out = fn(**kwargs)
                time.sleep(self.sleep_sec)
                return out
            except Exception as e:  # noqa: BLE001 - 上游异常类型不稳定
                last_err = e
                time.sleep(self.sleep_sec * (2 ** attempt))
        raise DataSourceError(f"{getattr(fn,'__name__','fn')} 调用失败: {last_err}")

    # ---------- 股票池 ----------
    def stock_list(self) -> pd.DataFrame:
        """返回 columns=[code, name]。"""
        fn = resolve("stock_list")
        df = self._call(fn)
        cols = {c: c for c in df.columns}
        code_col = next((c for c in df.columns if "代码" in str(c) or str(c).lower() == "code"), None)
        name_col = next((c for c in df.columns if "名称" in str(c) or str(c).lower() == "name"), None)
        if code_col is None or name_col is None:
            raise DataSourceError(f"无法识别股票列表的代码/名称列: {list(df.columns)}")
        out = df[[code_col, name_col]].copy()
        out.columns = ["code", "name"]
        out["code"] = out["code"].astype(str).str.zfill(6)
        return out.reset_index(drop=True)

    def trade_calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        fn = resolve("trade_calendar")
        df = self._call(fn)
        col = df.columns[0]
        d = pd.to_datetime(df[col])
        return pd.DatetimeIndex(d[(d >= start) & (d <= end)].sort_values().unique())

    # ---------- 行情 ----------
    def daily_bars_one(self, code: str, start: str, end: str) -> pd.DataFrame:
        """拉单只股票的日线。同时取不复权(判涨跌停)和后复权(算收益)。"""
        fn = resolve("daily_bars")
        s, e = start.replace("-", ""), end.replace("-", "")

        raw = self._call(fn, symbol=code, period="daily", start_date=s, end_date=e, adjust="")
        hfq = self._call(fn, symbol=code, period="daily", start_date=s, end_date=e, adjust="hfq")
        if raw is None or raw.empty:
            return pd.DataFrame()

        raw = _normalize_hist(raw)
        hfq = _normalize_hist(hfq)
        # 后复权因子 = 后复权收盘 / 原始收盘
        merged = raw.join(hfq["close"].rename("close_hfq"), how="left")
        merged["adj_factor"] = merged["close_hfq"] / merged["close"]
        merged["adj_factor"] = merged["adj_factor"].ffill().fillna(1.0)
        merged = merged.drop(columns=["close_hfq"])
        merged["code"] = str(code).zfill(6)
        return merged.reset_index().set_index(["date", "code"])

    def daily_bars(
        self, codes: list[str], start: str, end: str, progress: bool = True
    ) -> pd.DataFrame:
        """批量拉日线并拼成契约格式。数量大时请分批过夜跑。"""
        frames = []
        total = len(codes)
        for i, c in enumerate(codes, 1):
            try:
                df = self.daily_bars_one(c, start, end)
                if not df.empty:
                    frames.append(df)
            except DataSourceError as e:
                print(f"  [skip] {c}: {e}")
            if progress and i % 50 == 0:
                print(f"  {i}/{total} ...")
        if not frames:
            raise DataSourceError("没有拉到任何行情数据")
        bars = pd.concat(frames).sort_index()
        return self._finalize(bars)

    def _finalize(self, bars: pd.DataFrame) -> pd.DataFrame:
        """补齐契约要求的派生列。"""
        bars = bars.sort_index()
        g = bars.groupby(level="code", group_keys=False)
        if "prev_close" not in bars.columns:
            bars["prev_close"] = g["close"].shift(1)
        bars["prev_close"] = bars["prev_close"].fillna(bars["open"])

        for col, default in [
            ("is_st", False), ("is_suspended", False), ("is_tradable", True),
            ("days_since_ipo", 9999), ("total_mv", float("nan")),
            ("float_mv", float("nan")), ("industry", "未知"), ("adj_factor", 1.0),
        ]:
            if col not in bars.columns:
                bars[col] = default

        # 成交量为 0 视为停牌（AkShare 的日线通常直接跳过停牌日，这里兜底）
        bars["is_suspended"] = bars["is_suspended"] | (bars["volume"].fillna(0) <= 0)
        return validate_bars(bars, strict=False)

    # ---------- 排雷用的辅助数据 ----------
    def st_codes(self) -> set[str]:
        """当前 ST/*ST 名单。注意：这是"当前"快照，不是历史 PIT 数据。

        用它做实盘排雷没问题；做回测排雷会引入未来函数，
        回测请改用带日期的历史 ST 记录（Tushare 的 namechange 接口更合适）。
        """
        try:
            fn = resolve("st_list")
        except DataSourceError:
            return set()
        df = self._call(fn)
        col = next((c for c in df.columns if "代码" in str(c)), df.columns[0])
        return set(df[col].astype(str).str.zfill(6))

    def industry_map(self) -> dict[str, str]:
        """行业归属映射 {code: industry}。同样是当前快照。"""
        try:
            list_fn = resolve("industry_list")
            cons_fn = resolve("industry_members")
        except DataSourceError:
            return {}
        inds = self._call(list_fn)
        name_col = next((c for c in inds.columns if "板块名称" in str(c) or "名称" in str(c)), inds.columns[0])
        mapping: dict[str, str] = {}
        for ind in inds[name_col].tolist():
            try:
                mem = self._call(cons_fn, symbol=ind)
            except DataSourceError:
                continue
            ccol = next((c for c in mem.columns if "代码" in str(c)), None)
            if ccol is None:
                continue
            for code in mem[ccol].astype(str).str.zfill(6):
                mapping.setdefault(code, ind)
        return mapping


_HIST_RENAME = {
    "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
    "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_chg", "换手率": "turnover_rate",
    "date": "date", "open": "open", "close": "close", "high": "high", "low": "low",
    "volume": "volume", "amount": "amount",
}


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    """把 AkShare 的中文列名日线表转成标准英文列。"""
    d = df.rename(columns=_HIST_RENAME).copy()
    if "date" not in d.columns:
        raise DataSourceError(f"日线表缺少日期列: {list(df.columns)}")
    d["date"] = pd.to_datetime(d["date"])
    keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount"] if c in d.columns]
    d = d[keep].set_index("date").sort_index()
    # AkShare 的成交量单位是"手"，转成"股"
    if "volume" in d.columns:
        d["volume"] = d["volume"].astype(float) * 100
    return d.astype(float, errors="ignore")
