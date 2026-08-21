"""盘后工作流：收盘后跑一次，做归因 + 纪律检查。

盘后的目的不是看今天赚了多少 —— 那个数字你已经知道了，而且它没有信息量。
盘后的目的是回答三个问题：
  1. 今天的盈亏来自哪一层？（beta / 择时 / 选股 / 成本）
  2. 我有没有偏离系统？
  3. 有没有出现需要停下来的信号？（因子衰减、拥挤度、回撤逼近熔断）
"""
from __future__ import annotations

import sys, json, warnings
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from artemis.backtest.metrics import perf_stats, trade_stats, cost_drag, summary_table
from artemis.review.attribution import attribute, rolling_alpha_health
from artemis.review.discipline import score as discipline_score, behavioral_flags
from artemis.review.journal import Journal, summarize_by_source


def postmarket_report(result, bars: pd.DataFrame, journal_path: str | None = None,
                      planned_turnover: float = 3.0) -> dict:
    """生成盘后复盘报告（结构化）。"""
    eq = result.equity
    s = perf_stats(eq)
    attr = attribute(result, bars)
    health = rolling_alpha_health(result, bars, window=120).dropna()

    j = Journal(journal_path).load() if journal_path else pd.DataFrame()
    disc = discipline_score(j, result.trades, result.daily, planned_turnover)
    flags = behavioral_flags(eq, result.trades)

    # 风控预警
    warnings_list = []
    dd = s.get("max_drawdown", 0)
    cur_dd = float(result.daily["drawdown"].iloc[-1]) if "drawdown" in result.daily else 0.0
    risk = result.config.risk
    if cur_dd <= -risk.portfolio_dd_warn:
        warnings_list.append(f"⚠ 当前回撤 {cur_dd:.1%}，已触及预警线 {-risk.portfolio_dd_warn:.0%}")
    if cur_dd <= -risk.portfolio_dd_derisk:
        warnings_list.append(f"⚠ 已触发降仓线，仓位应减半")
    if not health.empty:
        recent_ir = float(health["rolling_alpha_ir"].iloc[-1])
        if recent_ir < 0:
            warnings_list.append(f"⚠ 滚动 120 日选股 alpha IR 为 {recent_ir:.2f}，因子可能正在失效")

    return {
        "summary": summary_table(result),
        "attribution": attr,
        "discipline": disc,
        "behavioral_flags": flags,
        "warnings": warnings_list,
        "alpha_health": health.tail(1).to_dict("records")[0] if not health.empty else {},
        "journal_by_source": summarize_by_source(
            Journal(journal_path).outcome_analysis(result.trades, bars)
        ) if journal_path else pd.DataFrame(),
    }


def render(rep: dict) -> str:
    out = ["=" * 64, "  盘后复盘", "=" * 64, "", "【绩效】"]
    out.append(rep["summary"].to_string(index=False))
    out += ["", "【收益归因 —— 钱是从哪一层来的】"]
    out.append(rep["attribution"].to_string(index=False))
    out += ["", "【纪律评分 —— 执行是不是你的漏洞】"]
    out.append(rep["discipline"].to_string(index=False))
    if rep["behavioral_flags"]:
        out += ["", "【行为陷阱】"] + [f"  {f}" for f in rep["behavioral_flags"]]
    if rep["warnings"]:
        out += ["", "【风控预警】"] + [f"  {w}" for w in rep["warnings"]]
    if rep.get("alpha_health"):
        h = rep["alpha_health"]
        out += ["", f"【Alpha 健康度】滚动年化 alpha {h.get('rolling_alpha_ann',0):.2%}, "
                    f"IR {h.get('rolling_alpha_ir',0):.2f}"]
    return "\n".join(out)


if __name__ == "__main__":
    from artemis.data.synthetic import make_market
    from artemis.config import ArtemisConfig
    from artemis.guard.rules import Guard
    from artemis.alpha import factors as F
    from artemis.portfolio.construct import build_weights, combine_factors
    from artemis.regime.market_state import RegimeModel
    from artemis.backtest.engine import Backtester

    bars, _ = make_market(n_stocks=200, n_days=900, seed=5)
    cfg = ArtemisConfig()
    mask = Guard(cfg.guard).apply(bars).mask
    names = ["momentum_120_20", "low_vol_60", "turnover_20", "vol_price_corr"]
    raw = F.compute(bars, names)
    prep = pd.DataFrame({c: F.prepare(raw[c], bars) for c in raw.columns}, index=bars.index)
    w = build_weights(combine_factors(prep), bars, mask=mask, cfg=cfg.portfolio)
    scale = RegimeModel(cfg.regime).fit_transform(bars).target_position
    res = Backtester(cfg).run(bars, w, position_scale=scale)
    print(render(postmarket_report(res, bars)))
