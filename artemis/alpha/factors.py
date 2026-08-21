"""因子库。

关于因子的两个立场：
1. 因子不是越多越好。20 个高度相关的量价因子，有效自由度可能只有 2 个，
   但过拟合的自由度是 20 个。宁可要 5 个逻辑独立、经济含义清楚的因子。
2. 每个因子必须能用一句话说清"为什么它该有超额收益"。说不清的，
   大概率是在拟合噪音 —— 哪怕回测很好看。

所有因子的约定：
- 输入 bars（契约格式），输出 Series，index 与 bars 对齐
- 数值越大代表"越该买"（已统一方向）
- 严格因果：T 日的因子值只用 <= T 日收盘的数据
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

_FACTORS: dict[str, dict] = {}


def factor(name: str, why: str, needs: str = "ohlcv"):
    """注册因子。why 是强制的 —— 说不出经济逻辑的因子不允许进库。"""
    def deco(fn: Callable) -> Callable:
        _FACTORS[name] = {"fn": fn, "why": why, "needs": needs}
        return fn
    return deco


def _px(bars: pd.DataFrame, col: str = "close") -> pd.DataFrame:
    return bars[col].unstack("code")


def _back(wide: pd.DataFrame, index: pd.MultiIndex) -> pd.Series:
    return wide.stack(future_stack=True).reindex(index)


# ---------------------------------------------------------------- 量价类
@factor("reversal_20", "A 股散户占比高、情绪驱动强，短期超涨超跌的均值回复是最稳健的异象之一")
def reversal_20(bars: pd.DataFrame) -> pd.Series:
    px = _px(bars)
    return _back(-(px / px.shift(20) - 1), bars.index)


@factor("momentum_120_20", "中期趋势延续：基本面改善需要时间被市场逐步定价，跳过最近 20 日以避开短期反转")
def momentum_120_20(bars: pd.DataFrame) -> pd.Series:
    px = _px(bars)
    return _back(px.shift(20) / px.shift(120) - 1, bars.index)


@factor("low_vol_60", "低波动异象：高波动股票吸引博彩型资金，被系统性高估，长期跑输")
def low_vol_60(bars: pd.DataFrame) -> pd.Series:
    px = _px(bars)
    vol = px.pct_change().rolling(60, min_periods=30).std()
    return _back(-vol, bars.index)


@factor("turnover_20", "换手率高 = 分歧大 + 投机成分重；低换手股票的持有者更稳定，抛压更小")
def turnover_20(bars: pd.DataFrame) -> pd.Series:
    to = (bars["amount"] / bars["float_mv"].replace(0, np.nan))
    wide = to.unstack("code").rolling(20, min_periods=10).mean()
    return _back(-wide, bars.index)


@factor("illiq_amihud", "Amihud 非流动性：单位成交额推动的价格变动。适度非流动性有溢价，但极端值已被排雷层拦掉")
def illiq_amihud(bars: pd.DataFrame) -> pd.Series:
    ret = (bars["close"] / bars["prev_close"] - 1).abs()
    illiq = (ret / bars["amount"].replace(0, np.nan)).unstack("code")
    wide = illiq.rolling(20, min_periods=10).mean()
    return _back(np.log1p(wide * 1e10), bars.index)


@factor("vol_price_corr", "量价背离：价涨量缩说明上涨缺乏承接，是典型的顶部特征")
def vol_price_corr(bars: pd.DataFrame) -> pd.Series:
    px = _px(bars).pct_change()
    vol = _px(bars, "volume").pct_change()
    corr = px.rolling(20, min_periods=15).corr(vol)
    return _back(corr, bars.index)


@factor("max_ret_5", "彩票效应：近期有过极端单日大涨的股票被博彩型资金追捧，随后系统性跑输")
def max_ret_5(bars: pd.DataFrame) -> pd.Series:
    ret = (bars["close"] / bars["prev_close"] - 1).unstack("code")
    return _back(-ret.rolling(20, min_periods=10).max(), bars.index)


@factor("size", "小市值溢价。注意：注册制+严退市后壳价值消失，这个因子的逻辑基础正在削弱，需持续监控衰减")
def size(bars: pd.DataFrame) -> pd.Series:
    return -np.log(bars["total_mv"].replace(0, np.nan))


# ---------------------------------------------------------------- 需要真实数据的因子（在你本机启用）
@factor("ep_ttm", "盈利收益率（E/P）：最经典的价值因子，估值均值回复", needs="fundamental")
def ep_ttm(bars: pd.DataFrame) -> pd.Series:
    if "net_profit_ttm" not in bars.columns:
        raise KeyError("ep_ttm 需要 net_profit_ttm 列（财务数据）。请接入 Tushare/AkShare 财务接口后启用。")
    return bars["net_profit_ttm"] / bars["total_mv"].replace(0, np.nan)


@factor("roe_ttm", "质量因子：高 ROE 反映持续的竞争优势，长期是股价的锚", needs="fundamental")
def roe_ttm(bars: pd.DataFrame) -> pd.Series:
    if "roe_ttm" not in bars.columns:
        raise KeyError("roe_ttm 需要财务数据。请接入财务接口后启用。")
    return bars["roe_ttm"]


def available_factors(needs: str | None = None) -> list[str]:
    if needs is None:
        return list(_FACTORS)
    return [k for k, v in _FACTORS.items() if v["needs"] == needs]


def factor_doc() -> pd.DataFrame:
    return pd.DataFrame(
        [{"factor": k, "needs": v["needs"], "why": v["why"]} for k, v in _FACTORS.items()]
    )


def compute(bars: pd.DataFrame, names: list[str] | None = None) -> pd.DataFrame:
    """批量计算因子。失败的因子会被跳过并告警，而不是让整个流程崩掉。"""
    names = names or available_factors("ohlcv")
    out = {}
    for n in names:
        try:
            out[n] = _FACTORS[n]["fn"](bars)
        except KeyError as e:
            print(f"  [skip factor] {n}: {e}")
    return pd.DataFrame(out, index=bars.index)


# ---------------------------------------------------------------- 预处理
def winsorize(s: pd.Series, n_mad: float = 5.0) -> pd.Series:
    """按日截面 MAD 去极值。用 MAD 而非标准差，因为 A 股截面厚尾严重。"""
    def _w(x: pd.Series) -> pd.Series:
        med = x.median()
        mad = (x - med).abs().median()
        if mad == 0 or np.isnan(mad):
            return x
        lo, hi = med - n_mad * 1.4826 * mad, med + n_mad * 1.4826 * mad
        return x.clip(lo, hi)
    return s.groupby(level="date", group_keys=False).apply(_w)


def zscore(s: pd.Series) -> pd.Series:
    """按日截面标准化。"""
    g = s.groupby(level="date")
    return (s - g.transform("mean")) / g.transform("std").replace(0, np.nan)


def neutralize(s: pd.Series, bars: pd.DataFrame, by_industry: bool = True,
               by_size: bool = True) -> pd.Series:
    """行业 + 市值中性化。

    不做中性化的后果：你以为自己找到了 alpha，其实只是买了一堆小盘股或
    重仓了某个行业。2024 年 1 月的教训就是"以为在做 alpha，实际在做 beta"。
    """
    df = pd.DataFrame({"y": s})
    if by_size:
        df["logmv"] = np.log(bars["total_mv"].replace(0, np.nan))
    if by_industry:
        df["industry"] = bars["industry"]

    def _resid(block: pd.DataFrame) -> pd.Series:
        b = block.dropna(subset=["y"])
        if len(b) < 20:
            return block["y"]
        X_parts = [np.ones((len(b), 1))]
        if by_size and "logmv" in b:
            lv = b["logmv"].fillna(b["logmv"].median()).values.reshape(-1, 1)
            X_parts.append((lv - lv.mean()) / (lv.std() or 1))
        if by_industry and "industry" in b:
            d = pd.get_dummies(b["industry"], drop_first=True).astype(float).values
            if d.size:
                X_parts.append(d)
        X = np.hstack(X_parts)
        y = b["y"].values
        try:
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ coef
        except np.linalg.LinAlgError:
            return block["y"]
        return pd.Series(resid, index=b.index).reindex(block.index)

    return df.groupby(level="date", group_keys=False).apply(_resid)


def prepare(s: pd.Series, bars: pd.DataFrame, neutral: bool = True) -> pd.Series:
    """标准预处理管线：去极值 -> 中性化 -> 标准化。"""
    out = winsorize(s)
    if neutral:
        out = neutralize(out, bars)
    return zscore(out)
