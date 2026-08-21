"""合成 A 股市场。

为什么需要它：
1. 真实数据只有一条历史路径，用它调参天然过拟合；合成市场可以生成
   成百上千条平行历史，用来问"这个策略在别的世界里还成立吗"。
2. 合成市场知道"真相"（哪个因子真的有预测力、哪些是噪音），
   所以可以用来验证研究流水线本身有没有 bug —— 检验检验器。
3. 它内置退市、停牌、涨跌停、ST 转换，是回测引擎摩擦处理的试金石。

真实数据用 akshare_source.py，两者产出同一个契约。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import validate_bars
from ..rules import price_limit_pct

INDUSTRIES = [
    "银行", "医药生物", "电子", "食品饮料", "电力设备",
    "计算机", "机械设备", "基础化工", "房地产", "汽车",
]


def make_market(
    n_stocks: int = 400,
    start: str = "2016-01-04",
    n_days: int = 2000,
    seed: int = 42,
    alpha_strength: float = 0.012,
    delist_enabled: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成一个合成 A 股市场。

    返回 (bars, truth)：
      bars  —— 符合 schema 契约的行情表
      truth —— 每日每股的"真实"潜在因子值，仅供验证流水线使用，
               策略代码绝对不许碰它（它就是未来函数本身）。

    alpha_strength：真实 alpha 因子对下期收益的贡献强度（年化超额量级）。
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=n_days)

    codes = _make_codes(n_stocks, rng)
    industry = rng.choice(INDUSTRIES, size=n_stocks)

    # ---- 市场因子：三状态马尔可夫（牛/震荡/熊），贴近 A 股的政策市特征 ----
    mkt_ret, regime = _market_path(n_days, rng)

    # ---- 行业因子 ----
    n_ind = len(INDUSTRIES)
    ind_ret = rng.normal(0, 0.010, size=(n_days, n_ind))
    ind_idx = np.array([INDUSTRIES.index(x) for x in industry])

    # ---- 个股载荷 ----
    beta = rng.normal(1.0, 0.30, n_stocks).clip(0.2, 2.2)
    ind_beta = rng.normal(1.0, 0.25, n_stocks).clip(0.1, 2.0)
    idio_vol = rng.uniform(0.014, 0.032, n_stocks)

    # size 载荷：-1 = 最小盘, +1 = 最大盘。小盘有正向漂移但波动/困境概率更高。
    size_rank = rng.normal(0, 1, n_stocks)
    idio_vol = idio_vol * (1.0 - 0.22 * np.tanh(size_rank))
    small_premium = -0.010 / np.sqrt(252) * np.tanh(size_rank)

    # ---- 真实 alpha 潜变量：缓慢均值回复的 AR(1)，跨股独立 ----
    #      这是"真相"。可观测的因子只是它的带噪投影。
    z = np.zeros((n_days, n_stocks))
    phi = 0.985
    z[0] = rng.normal(0, 1, n_stocks)
    for t in range(1, n_days):
        z[t] = phi * z[t - 1] + rng.normal(0, np.sqrt(1 - phi**2), n_stocks)

    # ---- 上市时间：一部分股票中途 IPO ----
    ipo_day = np.zeros(n_stocks, dtype=int)
    late = rng.random(n_stocks) < 0.30
    ipo_day[late] = rng.integers(1, int(n_days * 0.7), size=int(late.sum()))

    # ---- 质地分：决定 ST / 退市概率。低质地股票同时有负 alpha ----
    quality = rng.normal(0, 1, n_stocks)

    # ---- 逐日演化 ----
    close = np.zeros((n_days, n_stocks))
    prev_close = np.zeros((n_days, n_stocks))
    is_st = np.zeros((n_days, n_stocks), dtype=bool)
    alive = np.zeros((n_days, n_stocks), dtype=bool)
    suspended = np.zeros((n_days, n_stocks), dtype=bool)

    px = rng.lognormal(mean=np.log(12), sigma=0.6, size=n_stocks).clip(2.0, 200.0)
    st_flag = np.zeros(n_stocks, dtype=bool)
    dead = np.zeros(n_stocks, dtype=bool)
    # 累计"经营恶化"指标，触发 ST
    distress = np.zeros(n_stocks)

    limit_pct_base = np.array([price_limit_pct(c) for c in codes])

    for t in range(n_days):
        live = (~dead) & (t >= ipo_day)
        alive[t] = live

        # 停牌：约 0.6% 的股票日，ST 股更高
        susp = (rng.random(n_stocks) < np.where(st_flag, 0.03, 0.006)) & live
        suspended[t] = susp

        if t == 0:
            prev_close[t] = px
        else:
            prev_close[t] = np.where(live, close[t - 1], 0.0)
            # 当日 IPO 的股票，prev_close 用发行价
            just_ipo = live & (t == ipo_day)
            prev_close[t] = np.where(just_ipo, px, prev_close[t])

        # 潜在收益
        latent = (
            beta * mkt_ret[t]
            + ind_beta * ind_ret[t, ind_idx]
            + alpha_strength / np.sqrt(252) * z[max(t - 1, 0)]     # 用 t-1 的 z 预测 t 的收益
            + 0.004 / np.sqrt(252) * quality
            + small_premium
            + rng.normal(0, 1, n_stocks) * idio_vol
        )
        # ST 股额外的下行压力（真实世界里 ST 是负 alpha）
        latent = np.where(st_flag, latent - 0.0012, latent)

        # 涨跌停约束
        lim = np.where(st_flag, np.where(limit_pct_base > 0.15, 0.20, 0.05), limit_pct_base)
        # 次新股前 5 日放开
        newly = (t - ipo_day) < 5
        lim = np.where(live & newly & (limit_pct_base > 0.15), 5.0, lim)
        realized = np.clip(latent, -lim, lim)

        new_px = np.where(live & ~susp, prev_close[t] * (1 + realized), prev_close[t])
        new_px = np.maximum(new_px, 0.30)
        close[t] = np.where(live, new_px, 0.0)
        px = np.where(live, new_px, px)

        # ---- ST / 退市演化（每 ~60 日评估一次，模拟年报节奏）----
        if delist_enabled and t > 0 and t % 60 == 0:
            drawdown_1y = close[t] / np.maximum(close[max(t - 250, 0)], 1e-9) - 1
            distress = 0.7 * distress + 0.3 * (
                -quality - 2.0 * np.minimum(drawdown_1y, 0) - 0.5 * np.tanh(size_rank)
            )
            newly_st = live & ~st_flag & (distress > 2.4) & (rng.random(n_stocks) < 0.25)
            st_flag |= newly_st
            # ST 股有概率退市
            to_die = st_flag & live & (distress > 2.7) & (rng.random(n_stocks) < 0.22)
            dead |= to_die
            # 少数 ST 摘帽
            recover = st_flag & live & (distress < 1.2) & (rng.random(n_stocks) < 0.35)
            st_flag &= ~recover

        is_st[t] = st_flag & live

    # ---- 构造 OHLC ----
    intraday = rng.uniform(0.004, 0.020, size=(n_days, n_stocks))
    open_ = prev_close * (1 + np.clip(
        (close / np.maximum(prev_close, 1e-9) - 1) * rng.uniform(0.1, 0.7, (n_days, n_stocks))
        + rng.normal(0, 0.004, (n_days, n_stocks)),
        -0.09, 0.09))
    open_ = np.where(alive, np.maximum(open_, 0.30), 0.0)
    high = np.maximum(open_, close) * (1 + intraday * rng.uniform(0.2, 1.0, (n_days, n_stocks)))
    low = np.minimum(open_, close) * (1 - intraday * rng.uniform(0.2, 1.0, (n_days, n_stocks)))
    low = np.maximum(low, 0.30)

    # 涨跌停日：开高低收全部等于停板价（模拟一字板，买不进/卖不出）
    ret = np.divide(close - prev_close, np.maximum(prev_close, 1e-9),
                    out=np.zeros_like(close), where=prev_close > 0)
    lim_grid = np.where(is_st, np.where(limit_pct_base > 0.15, 0.20, 0.05),
                        np.tile(limit_pct_base, (n_days, 1)))
    at_limit_up = ret >= lim_grid - 1e-6
    at_limit_dn = ret <= -lim_grid + 1e-6
    one_word = (rng.random((n_days, n_stocks)) < 0.35)     # 35% 的停板是一字板
    seal = (at_limit_up | at_limit_dn) & one_word
    open_ = np.where(seal, close, open_)
    high = np.where(seal, close, high)
    low = np.where(seal, close, low)

    # 停牌日：价格不变、无成交
    open_ = np.where(suspended, close, open_)
    high = np.where(suspended, close, high)
    low = np.where(suspended, close, low)

    # ---- 市值与成交 ----
    # 股本与 size_rank 一致，保证"小盘"在市值上也确实小
    shares = np.exp(np.log(5.5e8) + 0.95 * size_rank).clip(5e7, 2e10)
    total_mv = close * shares
    turnover_rate = np.exp(rng.normal(np.log(0.020), 0.7, (n_days, n_stocks))).clip(0.0005, 0.35)
    # 小市值换手更高，停板日换手极低
    turnover_rate *= np.where(seal, 0.08, 1.0)
    volume = np.where(suspended | ~alive, 0.0, shares * turnover_rate)
    amount = volume * (high + low + close) / 3.0

    days_since_ipo = np.maximum(np.arange(n_days)[:, None] - ipo_day[None, :], -1)

    # ---- 组装 ----
    idx = pd.MultiIndex.from_product([dates, codes], names=["date", "code"])
    bars = pd.DataFrame(
        {
            "open": open_.ravel(),
            "high": high.ravel(),
            "low": low.ravel(),
            "close": close.ravel(),
            "volume": volume.ravel(),
            "amount": amount.ravel(),
            "prev_close": prev_close.ravel(),
            "adj_factor": 1.0,
            "is_st": is_st.ravel(),
            "is_suspended": suspended.ravel(),
            "is_tradable": alive.ravel(),
            "days_since_ipo": days_since_ipo.ravel(),
            "total_mv": total_mv.ravel(),
            "float_mv": (total_mv * rng.uniform(0.3, 1.0, n_stocks)).ravel(),
            "industry": np.tile(industry, (n_days, 1)).ravel(),
        },
        index=idx,
    )
    # 未上市/已退市的行剔除 —— 但退市前的行必须保留，这正是幸存者偏差的解药
    bars = bars[bars["is_tradable"].values].copy()
    bars = validate_bars(bars, strict=False)

    truth = pd.DataFrame(
        {"z_true": z.ravel(), "quality": np.tile(quality, (n_days, 1)).ravel()},
        index=idx,
    ).loc[bars.index]

    return bars, truth


def _make_codes(n: int, rng: np.random.Generator) -> list[str]:
    """生成横跨各板块的代码，比例接近真实 A 股。"""
    out: list[str] = []
    prefixes = (["600", "601", "603", "000", "002"] * 6) + ["300"] * 8 + ["688"] * 4
    i = 0
    while len(out) < n:
        p = prefixes[i % len(prefixes)]
        out.append(f"{p}{(i * 37 + 11) % 1000:03d}")
        i += 1
    return sorted(set(out))[:n] if len(set(out)) >= n else out[:n]


def _market_path(n_days: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """三状态市场：牛(0)/震荡(1)/熊(2)。A 股的特点是转换快、熊市长。"""
    # 转移矩阵：震荡是吸收态附近，牛市短促，熊市粘性高
    P = np.array([
        [0.975, 0.020, 0.005],
        [0.010, 0.975, 0.015],
        [0.006, 0.019, 0.975],
    ])
    mu = np.array([0.0016, 0.0000, -0.0011])
    sd = np.array([0.0125, 0.0095, 0.0165])

    state = np.zeros(n_days, dtype=int)
    state[0] = 1
    for t in range(1, n_days):
        state[t] = rng.choice(3, p=P[state[t - 1]])
    ret = rng.normal(mu[state], sd[state])
    return ret, state
