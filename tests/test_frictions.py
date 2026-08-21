"""A 股摩擦的回归测试。

这些测试的价值在于：它们会在你未来"优化"回测引擎时，
拦住那些让回测变好看的改动。回测引擎的每一次"提速"和"简化"，
都可能悄悄删掉一条摩擦。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.config import ArtemisConfig
from artemis.backtest.engine import Backtester
from artemis.data.schema import validate_bars
from artemis.rules import CostModel, classify_board, price_limit_pct, round_limit_price, Board


# ---------------------------------------------------------------- 规则层
def test_board_classification():
    assert classify_board("600519") is Board.MAIN
    assert classify_board("000001.SZ") is Board.MAIN
    assert classify_board("300750") is Board.CHINEXT
    assert classify_board("688981") is Board.STAR
    assert classify_board("830799") is Board.BSE


def test_price_limits_by_board():
    assert price_limit_pct("600519") == 0.10
    assert price_limit_pct("300750") == 0.20
    assert price_limit_pct("688981") == 0.20
    assert price_limit_pct("830799") == 0.30
    # ST 主板 5%，但创业板 ST 仍是 20%
    assert price_limit_pct("600519", is_st=True) == 0.05
    assert price_limit_pct("300750", is_st=True) == 0.20


def test_limit_price_rounding():
    # 交易所对涨跌停价四舍五入到分
    assert round_limit_price(10.00, 0.10, True) == 11.00
    assert round_limit_price(3.33, 0.10, True) == 3.66
    assert round_limit_price(3.33, 0.10, False) == 3.00


def test_cost_model_sell_includes_stamp_tax():
    c = CostModel(min_commission=0.0)
    turnover = 100_000.0
    assert c.sell_cost(turnover) > c.buy_cost(turnover)
    # 差额应恰好等于印花税
    assert c.sell_cost(turnover) - c.buy_cost(turnover) == pytest.approx(turnover * c.stamp_tax)


def test_min_commission_applies_to_small_trades():
    c = CostModel(min_commission=5.0, commission=0.00025)
    # 1000 元的交易，按费率只要 0.25 元，但最低收 5 元
    assert c.buy_cost(1000.0) >= 5.0
    # 小额交易的实际成本率极高 —— 这是小资金的隐性税
    assert c.buy_cost(1000.0) / 1000.0 > 0.004


# ---------------------------------------------------------------- 构造测试行情
def _make_bars(spec: pd.DataFrame, code: str = "600000") -> pd.DataFrame:
    """由简表构造符合契约的行情。spec 需含 open/high/low/close 列。"""
    spec = spec.copy()
    spec["code"] = code
    spec["volume"] = 1e7
    spec["amount"] = spec["close"] * 1e7
    spec["adj_factor"] = 1.0
    spec["is_st"] = spec.get("is_st", False)
    spec["is_suspended"] = spec.get("is_suspended", False)
    spec["is_tradable"] = spec.get("is_tradable", True)
    spec["days_since_ipo"] = 500
    spec["total_mv"] = 1e10
    spec["float_mv"] = 8e9
    spec["industry"] = "测试"
    spec["prev_close"] = spec["close"].shift(1).fillna(spec["close"].iloc[0])
    spec.index.name = "date"
    out = spec.reset_index().set_index(["date", "code"])
    return validate_bars(out, strict=False)


def _flat_config() -> ArtemisConfig:
    """关掉所有会干扰单点测试的风控。"""
    cfg = ArtemisConfig(account_size=1_000_000.0)
    cfg.risk.stop_loss_pct = 0.99
    cfg.risk.trailing_stop_pct = 0.99
    cfg.risk.max_holding_days = 99999
    cfg.risk.portfolio_dd_halt = 0.99
    cfg.risk.portfolio_dd_derisk = 0.99
    cfg.risk.portfolio_dd_warn = 0.99
    cfg.portfolio.max_turnover_per_rebalance = 10.0
    cfg.guard.max_position_adv_ratio = 1.0
    return cfg


# ---------------------------------------------------------------- 摩擦测试
def test_cannot_buy_at_limit_up():
    """开盘一字涨停时不能买入 —— 挂单排队也买不到。"""
    dates = pd.bdate_range("2024-01-02", periods=5)
    # 第 2 天一字涨停：开=高=低=收=涨停价
    df = pd.DataFrame({
        "open":  [10.0, 11.0, 11.5, 11.6, 11.7],
        "high":  [10.2, 11.0, 11.8, 11.9, 11.9],
        "low":   [ 9.8, 11.0, 11.3, 11.4, 11.5],
        "close": [10.0, 11.0, 11.6, 11.7, 11.8],
    }, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[0] = 1.0          # T0 收盘决定：T1 开盘全仓买入
    res = Backtester(_flat_config()).run(bars, w)

    assert res.trades.empty or (res.trades.side == "buy").sum() == 0, "涨停日不应成交"
    assert not res.blocked.empty
    assert "涨停/停牌无法买入" in set(res.blocked.reason)


def test_cannot_sell_at_limit_down():
    """开盘一字跌停时卖不掉 —— 这正是回撤被放大的机制。"""
    dates = pd.bdate_range("2024-01-02", periods=6)
    df = pd.DataFrame({
        "open":  [10.0, 10.1, 10.2,  9.18,  9.0,  9.1],
        "high":  [10.2, 10.3, 10.4,  9.18,  9.2,  9.3],
        "low":   [ 9.8,  9.9, 10.0,  9.18,  8.9,  9.0],
        "close": [10.0, 10.1, 10.2,  9.18,  9.1,  9.2],
    }, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[0:2] = 1.0        # 先建仓
    w.iloc[2:] = 0.0         # T2 收盘决定清仓 -> T3 开盘执行，但 T3 是跌停
    res = Backtester(_flat_config()).run(bars, w)

    blocked_sell = res.blocked[res.blocked.side == "sell"] if not res.blocked.empty else res.blocked
    assert not blocked_sell.empty, "跌停日的卖出应被拦截"
    assert "跌停/停牌无法卖出" in set(blocked_sell.reason)


def test_t_plus_1_no_same_day_round_trip():
    """T+1：同一只票不可能在同一天既买入又卖出。

    引擎靠"卖出循环先于买入循环"在结构上保证这一点。这个测试直接检验
    最终性质，而不是检验某一行代码 —— 无论内部怎么重构，性质都必须成立。
    """
    dates = pd.bdate_range("2024-01-02", periods=12)
    rng = np.random.default_rng(3)
    px = 10 * np.cumprod(1 + rng.normal(0, 0.008, 12))
    df = pd.DataFrame({"open": px, "high": px * 1.005, "low": px * 0.995, "close": px}, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    cfg = _flat_config()
    cfg.risk.max_holding_days = 1        # 持有 1 天就要求换出，制造高频进出
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[::2] = 1.0
    res = Backtester(cfg).run(bars, w)

    assert not res.trades.empty
    per_day = res.trades.groupby(["date", "code"])["side"].apply(set)
    for (d, c), sides in per_day.items():
        assert not ({"buy"} <= sides and "sell" in sides), \
            f"{c} 在 {d} 同日既买又卖，违反 T+1"


def test_t_plus_1_allows_sell_next_day():
    """T+1 的另一半：第二天必须能卖 —— 不能矫枉过正锁死持仓。"""
    dates = pd.bdate_range("2024-01-02", periods=6)
    df = pd.DataFrame({
        "open":  [10.0] * 6, "high": [10.0] * 6,
        "low":   [10.0] * 6, "close": [10.0] * 6,
    }, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[0] = 1.0       # T1 开盘买入
    w.iloc[1:] = 0.0      # T1 收盘决定清仓 -> T2 开盘卖出，应当成功
    res = Backtester(_flat_config()).run(bars, w)
    sells = res.trades[res.trades.side == "sell"] if not res.trades.empty else pd.DataFrame()
    assert not sells.empty, "买入后第二天应当可以卖出"


def test_suspended_stock_is_untradable():
    """停牌日既不能买也不能卖。"""
    dates = pd.bdate_range("2024-01-02", periods=4)
    df = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0, 10.0],
        "high":  [10.0, 10.0, 10.0, 10.0],
        "low":   [10.0, 10.0, 10.0, 10.0],
        "close": [10.0, 10.0, 10.0, 10.0],
        "is_suspended": [False, True, True, False],
    }, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[0] = 1.0
    res = Backtester(_flat_config()).run(bars, w)
    buys_on_susp = res.trades[(res.trades.side == "buy") & (res.trades.date == dates[1])] \
        if not res.trades.empty else pd.DataFrame()
    assert buys_on_susp.empty, "停牌日不应有成交"


def test_delisting_forces_liquidation_with_haircut():
    """退市强制清算，且按折价计 —— 不是从池子里悄悄消失。"""
    dates = pd.bdate_range("2024-01-02", periods=5)
    df = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0, 10.0, 10.0],
        "high":  [10.0, 10.0, 10.0, 10.0, 10.0],
        "low":   [10.0, 10.0, 10.0, 10.0, 10.0],
        "close": [10.0, 10.0, 10.0, 10.0, 10.0],
        "is_tradable": [True, True, True, False, False],
    }, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[0:2] = 1.0
    res = Backtester(_flat_config(), delist_haircut=0.45).run(bars, w)

    dl = res.trades[res.trades.side == "delist"]
    assert len(dl) == 1, "应触发一次退市清算"
    assert dl.iloc[0]["price"] == pytest.approx(10.0 * 0.55, rel=1e-6)
    # 组合应实际亏损，而不是净值不变
    assert res.equity.iloc[-1] < res.equity.iloc[0] * 0.7


def test_lot_size_rounding():
    """买入必须是 100 股整数倍（科创板 200 股）。"""
    dates = pd.bdate_range("2024-01-02", periods=3)
    df = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0], "high": [10.0, 10.0, 10.0],
        "low":   [10.0, 10.0, 10.0], "close": [10.0, 10.0, 10.0],
    }, index=dates)
    for code, lot in [("600000", 100), ("688001", 200)]:
        bars = _make_bars(df, code=code)
        codes = bars.index.get_level_values("code").unique()
        w = pd.DataFrame(0.0, index=dates, columns=codes)
        w.iloc[0] = 1.0
        res = Backtester(_flat_config()).run(bars, w)
        buys = res.trades[res.trades.side == "buy"]
        assert not buys.empty
        assert buys.iloc[0]["shares"] % lot == 0, f"{code} 应按 {lot} 股取整"


def test_execution_price_is_next_day_open_not_signal_day_close():
    """执行价必须是 T+1 开盘，不是 T 日收盘 —— 这是最常见的未来函数。"""
    dates = pd.bdate_range("2024-01-02", periods=3)
    df = pd.DataFrame({
        "open":  [10.0, 10.5, 10.5],     # T1 开盘跳空到 10.5 (+5%，未触及涨停)
        "high":  [10.0, 10.5, 10.5],
        "low":   [10.0, 10.5, 10.5],
        "close": [10.0, 10.5, 10.5],
    }, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[0] = 1.0      # T0 收盘(10 元)决定买入
    res = Backtester(_flat_config()).run(bars, w)
    buys = res.trades[res.trades.side == "buy"]
    assert not buys.empty
    # 成交价应接近 10.5（T1 开盘）而不是 10（T0 收盘）
    assert buys.iloc[0]["price"] > 10.4, "买入价必须是 T+1 开盘价，不是信号日收盘价"


def test_costs_actually_reduce_equity():
    """零成本和有成本必须产出不同净值 —— 防止成本被静默跳过。"""
    dates = pd.bdate_range("2024-01-02", periods=40)
    rng = np.random.default_rng(0)
    px = 10 * np.cumprod(1 + rng.normal(0, 0.01, 40))
    df = pd.DataFrame({"open": px, "high": px * 1.01, "low": px * 0.99, "close": px}, index=dates)
    bars = _make_bars(df)
    codes = bars.index.get_level_values("code").unique()
    w = pd.DataFrame(0.0, index=dates, columns=codes)
    w.iloc[::2] = 1.0        # 隔日进出，制造换手
    w.iloc[1::2] = 0.0

    cfg_cost = _flat_config()
    cfg_free = _flat_config()
    cfg_free.cost = CostModel(0.0, 0.0, 0.0, 0.0, 0.0)
    eq_cost = Backtester(cfg_cost).run(bars, w).equity.iloc[-1]
    eq_free = Backtester(cfg_free).run(bars, w).equity.iloc[-1]
    assert eq_free > eq_cost, "有成本的净值必须低于零成本"
