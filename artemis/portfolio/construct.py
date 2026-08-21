"""组合构建：把因子分数变成目标权重。

这一层最容易被轻视，但它决定了两件事：
1. 你的收益到底来自 alpha 还是来自集中押注（后者只是运气的放大器）
2. 单个错误判断能伤你多深

默认走等权 + 硬约束，而不是均值方差优化。原因很实际：
MVO 对协方差矩阵的估计误差极度敏感，散户拿到的数据质量撑不起它，
优化出来的权重通常是在放大估计噪音。等权是更诚实的先验。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PortfolioConfig


def _rebalance_dates(dates: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    if freq.upper() == "D":
        return dates
    s = pd.Series(1, index=dates)
    rule = {"W": "W", "M": "ME"}.get(freq.upper(), "W")
    return pd.DatetimeIndex(s.resample(rule).apply(lambda x: x.index[-1] if len(x) else None).dropna().values)


def build_weights(
    score: pd.Series,
    bars: pd.DataFrame,
    mask: pd.Series | None = None,
    cfg: PortfolioConfig | None = None,
) -> pd.DataFrame:
    """由因子综合分构建目标权重表 (date x code)。

    score 越大越买。返回的每一行权重和 <= 1（剩余为现金，由择时层的
    position_scale 再做一次总仓位缩放）。
    """
    cfg = cfg or PortfolioConfig()
    s = score.copy()
    if mask is not None:
        s = s.where(mask.reindex(s.index).fillna(False))

    dates = bars.index.get_level_values("date").unique().sort_values()
    rb_dates = set(_rebalance_dates(dates, cfg.rebalance_freq))

    vol = None
    if cfg.weighting == "inv_vol":
        px = bars["close"].unstack("code")
        vol = px.pct_change().rolling(60, min_periods=30).std()

    industry = bars["industry"]
    rows: dict[pd.Timestamp, pd.Series] = {}
    last: pd.Series | None = None

    for d in dates:
        if d not in rb_dates and last is not None:
            rows[d] = last            # 非调仓日沿用上期权重
            continue
        try:
            day = s.loc[d].dropna()
        except KeyError:
            day = pd.Series(dtype=float)
        if day.empty:
            rows[d] = last if last is not None else pd.Series(dtype=float)
            continue

        # --- 行业约束下的贪心选股：按分数排序，逐个纳入直到行业超限 ---
        try:
            ind_d = industry.loc[d]
        except KeyError:
            ind_d = pd.Series("未知", index=day.index)
        ranked = day.sort_values(ascending=False)
        max_per_ind = max(1, int(np.floor(cfg.max_industry_weight * cfg.n_holdings)))

        # 缓冲带：已持仓且排名仍在前 n*buffer 名内的，优先保留。
        # 目的不是提高收益，是砍掉"边缘名次反复换手"带来的纯成本损耗。
        held = list(last.index) if last is not None else []
        keep_cut = int(cfg.n_holdings * cfg.hold_buffer)
        rank_pos = {c: i for i, c in enumerate(ranked.index)}
        survivors = [c for c in held if rank_pos.get(c, 10**9) < keep_cut]

        picked, ind_count = [], {}
        for code in survivors:
            ind = ind_d.get(code, "未知")
            if ind_count.get(ind, 0) >= max_per_ind:
                continue
            picked.append(code)
            ind_count[ind] = ind_count.get(ind, 0) + 1
            if len(picked) >= cfg.n_holdings:
                break
        # 再用新信号补足剩余名额
        for code in ranked.index:
            if len(picked) >= cfg.n_holdings:
                break
            if code in picked:
                continue
            ind = ind_d.get(code, "未知")
            if ind_count.get(ind, 0) >= max_per_ind:
                continue
            picked.append(code)
            ind_count[ind] = ind_count.get(ind, 0) + 1
        if not picked:
            rows[d] = last if last is not None else pd.Series(dtype=float)
            continue

        # --- 定权重 ---
        if cfg.weighting == "equal":
            w = pd.Series(1.0 / len(picked), index=picked)
        elif cfg.weighting == "inv_vol" and vol is not None:
            v = vol.loc[d, picked].replace(0, np.nan)
            iv = (1 / v).fillna(0)
            w = iv / iv.sum() if iv.sum() > 0 else pd.Series(1.0 / len(picked), index=picked)
        else:  # score 加权
            sc = ranked.loc[picked]
            sc = (sc - sc.min() + 1e-6)
            w = sc / sc.sum()

        w = w.clip(upper=cfg.max_weight)
        w = w[w >= cfg.min_weight]
        if w.empty:
            w = pd.Series(1.0 / len(picked), index=picked)
        w = w / w.sum()
        rows[d] = w
        last = w

    out = pd.DataFrame(rows).T.fillna(0.0)
    out.index.name = "date"
    return out.reindex(columns=bars.index.get_level_values("code").unique().sort_values(), fill_value=0.0)


def combine_factors(
    factors: pd.DataFrame, weights: dict[str, float] | None = None
) -> pd.Series:
    """多因子合成。

    默认等权合成，而不是按 IC 加权。理由：IC 加权是在用样本内表现分配权重，
    这是过拟合的常见入口。等权在样本外通常更稳，除非你有很强的先验。
    """
    if weights is None:
        return factors.mean(axis=1)
    cols = [c for c in weights if c in factors.columns]
    w = pd.Series({c: weights[c] for c in cols})
    w = w / w.abs().sum()
    return (factors[cols] * w).sum(axis=1)
