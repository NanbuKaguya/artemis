"""因子评估。

判定一个因子能不能用，看四件事，缺一不可：
1. IC / ICIR —— 有没有预测力，稳不稳定
2. 分层单调性 —— 是全样本有效，还是只靠头尾两组的极端值
3. 衰减曲线 —— 信号能撑多久，决定了你的调仓频率和成本预算
4. 拥挤度 —— 别人是不是也在用它。2024 年 1 月的爆仓不是因子失效，是因子太挤

只看 IC 就上策略，是最常见的自杀方式。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def forward_returns(bars: pd.DataFrame, horizons=(1, 5, 10, 20)) -> pd.DataFrame:
    """未来收益。用后复权价，并且严格从 T+1 开盘算起 —— 因为 T 日收盘
    算出的信号，最早只能 T+1 开盘执行。用 close-to-close 会系统性高估收益。
    """
    adj_close = (bars["close"] * bars["adj_factor"]).unstack("code")
    adj_open = (bars["open"] * bars["adj_factor"]).unstack("code")
    out = {}
    for h in horizons:
        # T+1 开盘买入，T+1+h 开盘卖出
        entry = adj_open.shift(-1)
        exit_ = adj_open.shift(-1 - h)
        out[f"fwd_{h}"] = (exit_ / entry - 1).stack(future_stack=True).reindex(bars.index)
    return pd.DataFrame(out, index=bars.index)


@dataclass
class FactorReport:
    name: str
    ic: pd.Series
    stats: dict
    quantile_returns: pd.DataFrame
    decay: pd.Series

    def __repr__(self) -> str:
        s = self.stats
        return (f"<Factor {self.name}: IC={s['ic_mean']:.4f} ICIR={s['icir']:.2f} "
                f"t={s['t_stat']:.1f} 单调性={s['monotonicity']:.2f} 多空={s['ls_ann']:.1%}>")


def evaluate_factor(
    fac: pd.Series,
    bars: pd.DataFrame,
    mask: pd.Series | None = None,
    name: str = "factor",
    n_quantiles: int = 5,
    horizon: int = 5,
) -> FactorReport:
    """评估单因子。mask 为排雷层输出，只在可交易样本上评估。"""
    fwd = forward_returns(bars, horizons=(1, horizon, 20))
    df = pd.DataFrame({"f": fac, "r": fwd[f"fwd_{horizon}"]})
    if mask is not None:
        df = df[mask.reindex(df.index).fillna(False)]
    df = df.dropna()
    if df.empty:
        raise ValueError(f"因子 {name} 没有有效样本")

    # --- IC：截面 Spearman 秩相关 ---
    ic = df.groupby(level="date").apply(
        lambda g: g["f"].corr(g["r"], method="spearman") if len(g) >= 20 else np.nan
    ).dropna()

    n = len(ic)
    ic_mean, ic_std = float(ic.mean()), float(ic.std())
    icir = ic_mean / ic_std * np.sqrt(252 / horizon) if ic_std > 0 else 0.0
    t_stat = ic_mean / (ic_std / np.sqrt(n)) if ic_std > 0 and n > 1 else 0.0

    # --- 分层 ---
    def _q(g: pd.DataFrame) -> pd.DataFrame:
        if len(g) < n_quantiles * 4:
            return pd.DataFrame()
        g = g.copy()
        g["q"] = pd.qcut(g["f"].rank(method="first"), n_quantiles, labels=False)
        return g
    qd = df.groupby(level="date", group_keys=False).apply(_q)
    qret = qd.groupby([qd.index.get_level_values("date"), "q"])["r"].mean().unstack("q")
    qmean = qret.mean() * (252 / horizon)

    # 单调性：分组平均收益与组序号的秩相关。1.0 = 完美单调
    monot = float(pd.Series(qmean.values).corr(pd.Series(range(len(qmean))), method="spearman"))
    ls = qret[qret.columns[-1]] - qret[qret.columns[0]]
    ls_ann = float(ls.mean() * (252 / horizon))
    ls_ir = float(ls.mean() / ls.std() * np.sqrt(252 / horizon)) if ls.std() > 0 else 0.0

    # --- 衰减：不同前瞻期的 IC ---
    decay = {}
    for h in (1, 5, 10, 20, 40, 60):
        f2 = forward_returns(bars, horizons=(h,))[f"fwd_{h}"]
        d2 = pd.DataFrame({"f": fac, "r": f2})
        if mask is not None:
            d2 = d2[mask.reindex(d2.index).fillna(False)]
        d2 = d2.dropna()
        if d2.empty:
            continue
        decay[h] = float(d2.groupby(level="date").apply(
            lambda g: g["f"].corr(g["r"], method="spearman") if len(g) >= 20 else np.nan
        ).mean())

    # --- 因子自相关：决定换手率 ---
    fw = fac.unstack("code")
    autocorr = float(fw.corrwith(fw.shift(horizon), axis=1).mean())

    stats = {
        "n_days": n,
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "icir": icir,
        "t_stat": t_stat,
        "ic_win_rate": float((ic > 0).mean()),
        "monotonicity": monot,
        "ls_ann": ls_ann,
        "ls_ir": ls_ir,
        "autocorr": autocorr,
        "implied_turnover": 1 - autocorr,
        "horizon": horizon,
    }
    return FactorReport(name, ic, stats, qret, pd.Series(decay, name="ic_by_horizon"))


def evaluate_all(
    factors: pd.DataFrame, bars: pd.DataFrame, mask: pd.Series | None = None, horizon: int = 5
) -> pd.DataFrame:
    """批量评估，返回排序后的汇总表。"""
    rows = []
    for c in factors.columns:
        try:
            rep = evaluate_factor(factors[c], bars, mask=mask, name=c, horizon=horizon)
            rows.append({"factor": c, **rep.stats})
        except Exception as e:  # noqa: BLE001
            print(f"  [skip] {c}: {e}")
    df = pd.DataFrame(rows).set_index("factor")
    return df.sort_values("icir", key=abs, ascending=False)


def correlation_matrix(factors: pd.DataFrame) -> pd.DataFrame:
    """因子间截面相关。

    高相关的因子组合在一起，等于把同一个赌注下三遍 —— 回测夏普会虚高，
    实盘回撤会翻倍。相关性 > 0.7 的因子必须二选一或做正交化。
    """
    def _c(g: pd.DataFrame) -> pd.DataFrame:
        return g.corr(method="spearman")
    daily = factors.groupby(level="date", group_keys=False).apply(_c)
    return daily.groupby(level=-1).mean().reindex(index=factors.columns, columns=factors.columns)


def crowding(fac: pd.Series, bars: pd.DataFrame, window: int = 250) -> pd.Series:
    """因子拥挤度代理指标。

    思路：如果某个因子的多头组合，其内部相关性和相对估值同时抬升，
    说明大量资金在同向拥入。2024 年 1 月微盘股踩踏前，微盘因子的
    拥挤度就在历史极值。拥挤度不预测收益，它预测"崩起来有多快"。

    这里用可得数据构造：多头组的换手集中度 + 多头组内部收益相关性。
    """
    ret = (bars["close"] / bars["prev_close"] - 1).unstack("code")
    top_mask = fac.groupby(level="date").rank(pct=True) > 0.8
    top_wide = top_mask.unstack("code").fillna(False)

    # 多头组内部平均相关性（用横截面收益离散度的倒数近似，计算量可控）
    top_ret = ret.where(top_wide)
    disp = top_ret.std(axis=1)
    mkt_disp = ret.std(axis=1)
    ratio = (mkt_disp / disp.replace(0, np.nan))          # 越高说明多头组越"抱团"

    z = (ratio - ratio.rolling(window, min_periods=60).mean()) / \
        ratio.rolling(window, min_periods=60).std().replace(0, np.nan)
    return z.rename("crowding_z")
