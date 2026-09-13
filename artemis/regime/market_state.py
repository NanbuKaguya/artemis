"""择时层：决定"仓位多重"，不决定"买哪只"。

为什么把择时和选股分开：
A 股个股收益里 beta 的方差远大于多数人能做出的 alpha。同样一份精力，
把总仓位从"永远满仓"改成"随市场状态浮动"，对回撤的改善通常比
换一套选股因子更大，而且不需要你比别人聪明。

方法论上刻意用"多信号投票 + 慢变量"而不是单一择时指标：
- 单指标必然在某段历史失效，投票能降低单点失效的伤害
- 慢变量减少调仓次数 —— 择时最大的隐性成本是频繁进出的摩擦

严格因果：所有信号只用截至 T 日收盘的信息，产出的是 T+1 的目标仓位。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import RegimeConfig


def clip_by_board(ret: "pd.DataFrame") -> "pd.DataFrame":
    """按各自板块的涨跌停幅度截断个股日收益。

    统一用 ±11% 是错的：创业板/科创板合法波动 20%，北交所 30%。
    拿主板的尺子去量它们，会把真实行情当成异常值切掉 ——
    市场指数的波动被系统性低估，而基于它算出来的 beta 偏小、
    超额收益偏大。归因报告于是把 beta 说成 alpha。
    """
    from ..rules import price_limit_pct

    lim = pd.Series({c: price_limit_pct(str(c)) * 1.1 for c in ret.columns})
    return ret.clip(lower=-lim, upper=lim, axis=1)


@dataclass
class RegimeOutput:
    target_position: pd.Series   # index=date, 值域 [min_position, max_position]
    score: pd.Series             # 0~1 的原始健康分
    signals: pd.DataFrame        # 各分项信号，用于复盘归因
    state: pd.Series             # 'bull' / 'neutral' / 'bear'


class RegimeModel:
    def __init__(self, cfg: RegimeConfig | None = None):
        self.cfg = cfg or RegimeConfig()

    def fit_transform(self, bars: pd.DataFrame, benchmark: pd.Series | None = None) -> RegimeOutput:
        """bars 为全市场行情；benchmark 为基准指数收盘价（可选）。

        没有指数数据时，用全市场等权价格指数代替 —— 对判断市场状态足够。
        """
        cfg = self.cfg
        px = bars["close"].unstack("code")

        if benchmark is None:
            # 等权市场指数：先算个股日收益再等权平均，避免成分变动造成的跳变
            ret = px.pct_change()
            # 剔除极端值（脏数据），但要按各自板块的合法幅度来剔
            ret = clip_by_board(ret)
            bench_ret = ret.mean(axis=1)
            benchmark = (1 + bench_ret.fillna(0)).cumprod()
        bench_ret = benchmark.pct_change()

        sig = pd.DataFrame(index=benchmark.index)

        # --- 1. 趋势：快线 vs 慢线，以及价格 vs 慢线 ---
        ma_f = benchmark.rolling(cfg.trend_fast, min_periods=cfg.trend_fast // 2).mean()
        ma_s = benchmark.rolling(cfg.trend_slow, min_periods=cfg.trend_slow // 2).mean()
        sig["trend_cross"] = (ma_f > ma_s).astype(float)
        sig["trend_price"] = (benchmark > ma_s).astype(float)

        # --- 2. 波动：高波动期降仓（波动聚集是最稳健的市场规律之一）---
        vol = bench_ret.rolling(cfg.vol_window, min_periods=10).std()
        vol_pct = vol.rolling(250, min_periods=60).rank(pct=True)
        sig["low_vol"] = (vol_pct < cfg.vol_high_pct).astype(float)

        # --- 3. 宽度：多少比例的股票在自己的 MA20 之上 ---
        ma20 = px.rolling(cfg.breadth_window, min_periods=10).mean()
        breadth = (px > ma20).sum(axis=1) / px.notna().sum(axis=1).replace(0, np.nan)
        breadth = breadth.reindex(benchmark.index).ffill()
        sig["breadth"] = (breadth > 0.45).astype(float)
        sig["breadth_raw"] = breadth

        # --- 4. 回撤：指数自身回撤过深时先减仓，等企稳 ---
        dd = benchmark / benchmark.cummax() - 1
        sig["not_deep_dd"] = (dd > -0.15).astype(float)

        # --- 投票合成 ---
        vote_cols = ["trend_cross", "trend_price", "low_vol", "breadth", "not_deep_dd"]
        raw_score = sig[vote_cols].mean(axis=1)
        # 平滑：避免在阈值附近来回横跳造成的无谓换手
        score = raw_score.rolling(5, min_periods=1).mean()

        # --- 映射到目标仓位，并按 step 量化 ---
        target = cfg.min_position + score * (cfg.max_position - cfg.min_position)
        step = cfg.position_step
        target = (target / step).round() * step
        target = target.clip(cfg.min_position, cfg.max_position)
        # 迟滞：仓位变化小于一个 step 就不动，进一步压制换手
        target = _hysteresis(target, step)

        state = pd.Series(
            np.select([score >= 0.7, score <= 0.35], ["bull", "bear"], default="neutral"),
            index=score.index,
        )

        sig["score"] = score
        sig["target_position"] = target
        return RegimeOutput(target_position=target, score=score, signals=sig, state=state)


def _hysteresis(series: pd.Series, step: float) -> pd.Series:
    """只有当目标偏离当前值达到一个完整 step 时才调整，抑制抖动。"""
    out = series.copy()
    cur = series.iloc[0] if len(series) else 0.0
    vals = []
    for v in series.values:
        if abs(v - cur) >= step - 1e-9:
            cur = v
        vals.append(cur)
    return pd.Series(vals, index=series.index)
