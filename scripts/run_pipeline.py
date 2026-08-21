"""端到端流水线 + 消融实验。

消融实验回答的问题是："系统里哪一层真的在帮我？"
不做消融，你永远不知道自己的收益是来自哪一层，也就无法在它失效时察觉。
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
from artemis.backtest.metrics import perf_stats, trade_stats, cost_drag


def build_inputs(bars, use_guard=True, factor_names=None):
    mask = Guard().apply(bars).mask if use_guard else pd.Series(True, index=bars.index)
    names = factor_names or ["momentum_120_20", "low_vol_60", "turnover_20", "vol_price_corr"]
    raw = F.compute(bars, names)
    prep = pd.DataFrame({c: F.prepare(raw[c], bars) for c in raw.columns}, index=bars.index)
    score = combine_factors(prep)
    return mask, score


def run_variant(bars, cfg, use_guard=True, use_regime=True, zero_cost=False, label=""):
    mask, score = build_inputs(bars, use_guard=use_guard)
    w = build_weights(score, bars, mask=mask, cfg=cfg.portfolio)
    scale = None
    if use_regime:
        scale = RegimeModel(cfg.regime).fit_transform(bars).target_position
    if zero_cost:
        from artemis.rules import CostModel
        cfg = ArtemisConfig(**{**cfg.__dict__, "cost": CostModel(0, 0, 0, 0, 0)})
    bt = Backtester(cfg)
    res = bt.run(bars, w, position_scale=scale)
    s = perf_stats(res.equity)
    t = trade_stats(res.trades, res.equity)
    c = cost_drag(res.trades, res.equity, cfg.cost)
    return dict(
        variant=label,
        年化=s.get("annual_return", 0) * 100,
        最大回撤=s.get("max_drawdown", 0) * 100,
        Calmar=s.get("calmar", 0),
        夏普=s.get("sharpe", 0),
        最差月=s.get("worst_month", 0) * 100,
        回撤天数=s.get("max_dd_days", 0),
        年换手=t.get("annual_turnover", 0),
        成本拖累=c.get("annual_cost_drag", 0) * 100,
        踩雷退市=t.get("n_delistings", 0),
    ), res


def main(seed=7, n_stocks=300, n_days=1500):
    print(f"=== 生成合成市场 (seed={seed}, {n_stocks} 只, {n_days} 天) ===")
    bars, _ = make_market(n_stocks=n_stocks, n_days=n_days, seed=seed)
    cfg = ArtemisConfig()

    variants = [
        dict(use_guard=True,  use_regime=True,  zero_cost=False, label="完整系统"),
        dict(use_guard=False, use_regime=True,  zero_cost=False, label="关掉排雷层"),
        dict(use_guard=True,  use_regime=False, zero_cost=False, label="关掉择时层"),
        dict(use_guard=False, use_regime=False, zero_cost=False, label="只有选股"),
        dict(use_guard=True,  use_regime=True,  zero_cost=True,  label="完整系统(零成本幻觉)"),
    ]
    rows, results = [], {}
    for v in variants:
        t0 = time.time()
        row, res = run_variant(bars, cfg, **v)
        rows.append(row); results[v["label"]] = res
        print(f"  {v['label']:<22} done in {time.time()-t0:.0f}s")

    df = pd.DataFrame(rows).set_index("variant")
    print("\n=== 消融实验结果 ===")
    print(df.round(2).to_string())

    full = results["完整系统"]
    if not full.blocked.empty:
        print("\n=== 被 A 股摩擦挡下的交易（回测与实盘的差距就在这里）===")
        print(full.blocked.groupby("reason").agg(次数=("want", "size"), 涉及金额=("want", "sum")).round(0).to_string())
    return df, results


if __name__ == "__main__":
    main()
