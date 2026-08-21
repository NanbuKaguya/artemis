"""绩效指标。

刻意把"亏钱侧"的指标放在前面：最大回撤、回撤持续时间、亏损月占比、
最差单月。因为决定你能不能拿住策略的，从来不是年化收益，
而是最难受的那段时间有多难受、有多长。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def perf_stats(equity: pd.Series, benchmark: pd.Series | None = None,
               rf: float = 0.015) -> dict:
    eq = equity.dropna()
    if len(eq) < 2:
        return {}
    ret = eq.pct_change().fillna(0)
    n = len(eq)
    years = n / TRADING_DAYS

    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    ann = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0
    vol = float(ret.std() * np.sqrt(TRADING_DAYS))
    sharpe = (ann - rf) / vol if vol > 0 else 0.0

    dd_series = eq / eq.cummax() - 1
    mdd = float(dd_series.min())
    # 最长回撤持续天数：从上一个高点到收复失地
    underwater = dd_series < -1e-9
    dd_days, cur = 0, 0
    for u in underwater:
        cur = cur + 1 if u else 0
        dd_days = max(dd_days, cur)

    downside = ret[ret < 0].std() * np.sqrt(TRADING_DAYS)
    sortino = (ann - rf) / downside if downside > 0 else 0.0
    calmar = ann / abs(mdd) if mdd < 0 else 0.0

    monthly = eq.resample("ME").last().pct_change().dropna()
    stats = {
        # ---- 亏钱侧（先看这一栏）----
        "max_drawdown": mdd,
        "max_dd_days": int(dd_days),
        "worst_month": float(monthly.min()) if len(monthly) else 0.0,
        "loss_month_pct": float((monthly < 0).mean()) if len(monthly) else 0.0,
        "var_95_daily": float(ret.quantile(0.05)),
        "cvar_95_daily": float(ret[ret <= ret.quantile(0.05)].mean()) if (ret <= ret.quantile(0.05)).any() else 0.0,
        # ---- 赚钱侧 ----
        "total_return": total,
        "annual_return": ann,
        "annual_vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "win_rate_daily": float((ret > 0).mean()),
        "years": round(years, 2),
    }

    if benchmark is not None:
        b = benchmark.reindex(eq.index).ffill()
        b_ret = b.pct_change().fillna(0)
        excess = ret - b_ret
        b_ann = float((b.iloc[-1] / b.iloc[0]) ** (1 / years) - 1) if years > 0 and b.iloc[0] > 0 else 0.0
        te = float(excess.std() * np.sqrt(TRADING_DAYS))
        stats.update({
            "benchmark_annual": b_ann,
            "excess_annual": ann - b_ann,
            "tracking_error": te,
            "information_ratio": (ann - b_ann) / te if te > 0 else 0.0,
            "beta": float(np.cov(ret, b_ret)[0, 1] / np.var(b_ret)) if np.var(b_ret) > 0 else 0.0,
        })
    return stats


def trade_stats(trades: pd.DataFrame, equity: pd.Series) -> dict:
    """交易层面统计。换手率和成本占比是最容易被忽略的净值杀手。"""
    if trades is None or trades.empty:
        return {}
    buy_amt = trades.loc[trades.side == "buy", "amount"].sum()
    sell_amt = trades.loc[trades.side.isin(["sell", "delist"]), "amount"].sum()
    avg_equity = float(equity.mean())
    years = len(equity) / TRADING_DAYS
    return {
        "n_trades": int(len(trades)),
        "n_buys": int((trades.side == "buy").sum()),
        "n_sells": int((trades.side == "sell").sum()),
        "n_delistings": int((trades.side == "delist").sum()),
        "annual_turnover": float((buy_amt + sell_amt) / 2 / avg_equity / years) if avg_equity > 0 and years > 0 else 0.0,
        "total_buy_amount": float(buy_amt),
        "total_sell_amount": float(sell_amt),
    }


def cost_drag(trades: pd.DataFrame, equity: pd.Series, cost_model) -> dict:
    """成本拖累分析：你的收益到底被摩擦吃掉了多少。"""
    if trades is None or trades.empty:
        return {}
    buys = trades[trades.side == "buy"]["amount"]
    sells = trades[trades.side.isin(["sell", "delist"])]["amount"]
    comm = sum(max(a * cost_model.commission, cost_model.min_commission) for a in buys) + \
           sum(max(a * cost_model.commission, cost_model.min_commission) for a in sells)
    stamp = float(sells.sum() * cost_model.stamp_tax)
    transfer = float((buys.sum() + sells.sum()) * cost_model.transfer_fee)
    slip = float((buys.sum() + sells.sum()) * cost_model.slippage_bps / 1e4)
    total = comm + stamp + transfer + slip
    years = len(equity) / TRADING_DAYS
    avg_eq = float(equity.mean())
    return {
        "commission": comm, "stamp_tax": stamp, "transfer_fee": transfer,
        "slippage": slip, "total_cost": total,
        "cost_pct_of_equity": total / avg_eq if avg_eq > 0 else 0.0,
        "annual_cost_drag": total / avg_eq / years if avg_eq > 0 and years > 0 else 0.0,
    }


def summary_table(result, benchmark: pd.Series | None = None) -> pd.DataFrame:
    """把一次回测压成一张给人看的表。"""
    s = perf_stats(result.equity, benchmark)
    t = trade_stats(result.trades, result.equity)
    c = cost_drag(result.trades, result.equity, result.config.cost)
    rows = [
        ("年化收益", f"{s.get('annual_return',0):.2%}"),
        ("最大回撤", f"{s.get('max_drawdown',0):.2%}"),
        ("回撤最长天数", f"{s.get('max_dd_days',0)} 天"),
        ("Calmar", f"{s.get('calmar',0):.2f}"),
        ("夏普", f"{s.get('sharpe',0):.2f}"),
        ("最差单月", f"{s.get('worst_month',0):.2%}"),
        ("亏损月占比", f"{s.get('loss_month_pct',0):.1%}"),
        ("日 CVaR(95)", f"{s.get('cvar_95_daily',0):.2%}"),
        ("年化换手", f"{t.get('annual_turnover',0):.2f}x"),
        ("年化成本拖累", f"{c.get('annual_cost_drag',0):.2%}"),
        ("成交笔数", f"{t.get('n_trades',0)}"),
        ("踩雷退市次数", f"{t.get('n_delistings',0)}"),
    ]
    if benchmark is not None:
        rows.insert(2, ("超额年化", f"{s.get('excess_annual',0):.2%}"))
        rows.append(("信息比率", f"{s.get('information_ratio',0):.2f}"))
    return pd.DataFrame(rows, columns=["指标", "值"])
