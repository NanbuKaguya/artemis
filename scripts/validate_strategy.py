"""策略上线评审：五道闸门全过才允许投真钱。

这个脚本是"我到底该不该上这个策略"的唯一裁判。
它的设计是默认拒绝 —— 你要拿证据说服它，而不是它来讨好你。
"""
from __future__ import annotations

import sys, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from artemis.config import ArtemisConfig
from artemis.data.synthetic import make_market
from artemis.guard.rules import Guard
from artemis.alpha import factors as F
from artemis.portfolio.construct import build_weights, combine_factors
from artemis.regime.market_state import RegimeModel
from artemis.backtest.engine import Backtester
from artemis.backtest.metrics import perf_stats
from artemis.validate import antifit as AF


FACTORS = ["momentum_120_20", "low_vol_60", "turnover_20", "vol_price_corr"]
_CACHE: dict = {}


def _score(bars, key="real", seed=0):
    """缓存因子计算，避免网格扫描时重复算。"""
    ck = (key, seed, id(bars))
    if ck in _CACHE:
        return _CACHE[ck]
    if key == "random":
        rng = np.random.default_rng(seed)
        s = F.prepare(pd.Series(rng.normal(size=len(bars)), index=bars.index), bars)
    else:
        raw = F.compute(bars, FACTORS)
        prep = pd.DataFrame({c: F.prepare(raw[c], bars) for c in raw.columns}, index=bars.index)
        s = combine_factors(prep)
    _CACHE[ck] = s
    return s


def strategy(bars: pd.DataFrame, params: dict) -> pd.Series:
    """被检验的策略。params 可调：持仓数、调仓频率、止损线。"""
    cfg = ArtemisConfig()
    cfg.portfolio.n_holdings = params.get("n_holdings", 20)
    cfg.portfolio.rebalance_freq = params.get("rebalance_freq", "W")
    cfg.risk.stop_loss_pct = params.get("stop_loss", 0.12)

    mask = Guard(cfg.guard).apply(bars).mask
    score = _score(bars, params.get("_score_key", "real"), params.get("_seed", 0))
    w = build_weights(score, bars, mask=mask, cfg=cfg.portfolio)
    scale = RegimeModel(cfg.regime).fit_transform(bars).target_position
    return Backtester(cfg).run(bars, w, position_scale=scale).equity


def main(seed=11, n_stocks=200, n_days=1300):
    t_all = time.time()
    print(f"生成市场 (seed={seed}, {n_stocks} 只, {n_days} 天)...")
    bars, _ = make_market(n_stocks=n_stocks, n_days=n_days, seed=seed)
    cfg = ArtemisConfig()
    dates = bars.index.get_level_values("date").unique().sort_values()

    # ---------- 闸门 1：三段切分 ----------
    i_tr, i_va = int(len(dates) * 0.5), int(len(dates) * 0.75)
    splits = {
        "train":   dates[:i_tr],
        "valid":   dates[i_tr:i_va],
        "holdout": dates[i_va:],
    }
    print("\n【闸门1】样本内 / 样本外 / 锁箱")
    stats_by = {}
    for name, dd in splits.items():
        sub = bars[bars.index.get_level_values("date").isin(dd)]
        eq = strategy(sub, {})
        s = perf_stats(eq)
        stats_by[name] = s
        print(f"  {name:<8} {dd[0].date()}~{dd[-1].date()}  "
              f"年化 {s['annual_return']:7.2%}  夏普 {s['sharpe']:6.2f}  回撤 {s['max_drawdown']:7.2%}")

    # ---------- 闸门 2：滚动前推 ----------
    print("\n【闸门2】滚动前推 (walk-forward)")
    wf = AF.walk_forward(bars, strategy, {}, n_folds=4, train_years=2.0, test_years=0.8)
    if not wf.empty:
        print(wf.round(3).to_string(index=False))
        print(f"  -> 各折夏普中位数 {wf.sharpe.median():.2f}, 正收益折数 {int((wf.annual_return>0).sum())}/{len(wf)}")

    # ---------- 闸门 3：随机对照 ----------
    print("\n【闸门3】随机对照组 (20 次)")
    my_eq = strategy(bars, {})
    rc = AF.random_control(
        bars, my_eq,
        random_strategy=lambda b, i: strategy(b, {"_score_key": "random", "_seed": i}),
        n_trials=20,
    )
    for m in ["annual_return", "sharpe"]:
        d = rc[m]
        print(f"  {m:<14} 策略 {d['strategy']:7.3f} | 随机均值 {d['control_mean']:7.3f} "
              f"| 随机P95 {d['control_p95']:7.3f} | 分位 {d['percentile']:.0%}")
    print(f"  -> {rc['verdict']}")

    # ---------- 闸门 4：参数高原 ----------
    print("\n【闸门4】参数高原扫描")
    grid = {"n_holdings": [10, 15, 20, 25, 30],
            "rebalance_freq": ["W", "M"],
            "stop_loss": [0.08, 0.12, 0.20]}
    pl = AF.parameter_plateau(bars, strategy, grid, metric="sharpe")
    print(f"  扫描 {len(pl)} 组参数: 正夏普占比 {pl.attrs['positive_ratio']:.0%}, "
          f"最优 {pl.sharpe.max():.2f}, 中位 {pl.sharpe.median():.2f}, 高原度 {pl.attrs['plateau_ratio']:.2f}")
    print(pl.groupby("n_holdings").sharpe.median().round(2).to_string())

    # ---------- 闸门 5：PBO + DSR ----------
    print("\n【闸门5】PBO 与收缩夏普")
    # 用参数网格里每组的日收益构造矩阵
    ret_cols = {}
    for _, r in pl.head(12).iterrows():
        p = {"n_holdings": int(r.n_holdings), "rebalance_freq": r.rebalance_freq,
             "stop_loss": float(r.stop_loss)}
        eq = strategy(bars, p)
        ret_cols[f"h{p['n_holdings']}_{p['rebalance_freq']}_s{p['stop_loss']}"] = eq.pct_change()
    pbo = AF.pbo_cscv(pd.DataFrame(ret_cols), n_splits=8)
    print(f"  PBO = {pbo.get('pbo', float('nan')):.0%}  ({pbo.get('n_combinations',0)} 组合)  -> {pbo.get('verdict','—')}")

    dsr = AF.trial_log_to_dsr(pl.sharpe.dropna().values, n_obs=len(dates),
                              returns=my_eq.pct_change())
    print(f"  DSR = {dsr['dsr']:.3f} (试了 {dsr['n_trials']} 组, sigma_sr={dsr['sigma_sr']:.2f}, "
          f"运气可解释夏普 {dsr['expected_max_sharpe_from_luck']:.2f}) -> {dsr['verdict']}")

    # ---------- 总闸门 ----------
    print("\n" + "=" * 62)
    gate = AF.deployment_gate(
        oos_stats=stats_by["holdout"], is_stats=stats_by["train"],
        random_ctrl=rc, plateau=pl, pbo=pbo, dsr=dsr, cfg=cfg.validation,
    )
    print(gate.report().to_string(index=False))
    print("=" * 62)
    print(f"最终结论: {'✅ 允许上实盘' if gate.passed else '❌ 不允许上实盘'}   [耗时 {time.time()-t_all:.0f}s]")
    return gate


if __name__ == "__main__":
    main()
