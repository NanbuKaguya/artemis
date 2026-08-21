"""收益归因。

不做归因，你就不知道钱是怎么赚到的 —— 也就不知道它什么时候会停。
很多人以为自己在做 alpha，实际上只是在做 beta 或者押注小盘风格。
2024 年 1 月之前，大量"中性策略"的持有人都是这么想的。

本模块把组合收益拆成五块：
  市场 beta   —— 你只是跟着大盘涨
  择时贡献    —— 仓位控制带来的
  行业配置    —— 押对了行业
  个股选择    —— 真正的选股 alpha
  成本拖累    —— 被摩擦吃掉的
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def attribute(result, bars: pd.DataFrame, benchmark: pd.Series | None = None) -> pd.DataFrame:
    """对一次回测做收益归因。返回各分项的年化贡献。"""
    daily = result.daily
    ret = result.equity.pct_change().fillna(0)
    dates = ret.index

    px = bars["close"].unstack("code")
    if benchmark is None:
        mkt_ret = px.pct_change().clip(-0.11, 0.11).mean(axis=1).reindex(dates).fillna(0)
    else:
        mkt_ret = benchmark.reindex(dates).ffill().pct_change().fillna(0)

    pos = daily["position_pct"].reindex(dates).fillna(0)

    # 1) 市场 beta：假设始终满仓所能拿到的市场收益
    beta_contrib = mkt_ret
    # 2) 择时：实际仓位 vs 满仓的差异带来的收益差
    timing_contrib = (pos - 1.0) * mkt_ret
    # 3) 选股：组合实际收益减去按仓位缩放的市场收益
    selection_contrib = ret - pos * mkt_ret

    # 4) 成本：从成交记录估算
    trades = result.trades
    cost_daily = pd.Series(0.0, index=dates)
    if trades is not None and not trades.empty:
        cm = result.config.cost
        t = trades.copy()
        t["fee"] = t.apply(
            lambda r: (cm.sell_cost(r["amount"]) if r["side"] in ("sell", "delist")
                       else cm.buy_cost(r["amount"])) + r["amount"] * cm.slippage_bps / 1e4,
            axis=1,
        )
        by_day = t.groupby("date")["fee"].sum()
        eq = result.equity.reindex(dates).ffill()
        cost_daily = (by_day.reindex(dates).fillna(0) / eq).fillna(0)

    ann = lambda s: float((1 + s).prod() ** (252 / len(s)) - 1) if len(s) else 0.0
    rows = [
        ("市场 beta (满仓基准)", ann(beta_contrib)),
        ("择时贡献 (仓位控制)", ann(timing_contrib)),
        ("选股贡献 (含风控)", ann(selection_contrib)),
        ("成本拖累", -ann(cost_daily)),
        ("—— 合计（组合实际）", ann(ret)),
    ]
    df = pd.DataFrame(rows, columns=["来源", "年化贡献"])
    df["年化贡献"] = df["年化贡献"].map(lambda x: f"{x:.2%}")
    return df


def rolling_alpha_health(result, bars: pd.DataFrame, window: int = 120) -> pd.DataFrame:
    """滚动监测选股 alpha 是否还活着。

    因子会衰减，这是常态而非意外。关键是在它衰减时你能察觉，
    而不是等回撤打到熔断线才知道。
    """
    ret = result.equity.pct_change().fillna(0)
    px = bars["close"].unstack("code")
    mkt = px.pct_change().clip(-0.11, 0.11).mean(axis=1).reindex(ret.index).fillna(0)
    pos = result.daily["position_pct"].reindex(ret.index).fillna(0)
    alpha = ret - pos * mkt
    out = pd.DataFrame({
        "rolling_alpha_ann": alpha.rolling(window).mean() * 252,
        "rolling_alpha_ir": alpha.rolling(window).mean() / alpha.rolling(window).std() * np.sqrt(252),
    })
    return out
