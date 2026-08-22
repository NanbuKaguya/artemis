"""Level-2 聚合与执行成本的回归测试。

重点覆盖两类会**静默出错**的地方：
1. 沪深撤单编码差异 —— 用同一套代码算撤单率，沪市会恒为 0 且不报错
2. 逆向选择 —— 漏掉它会系统性高估被动挂单的收益
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.data.level2 import (
    Exchange, daily_features, exchange_of, make_synthetic_l2,
    validate_orders, validate_trades, Level2Error,
)
from artemis.execution.cost import (
    BookSnapshot, Fill, PlacementPolicy, attribution, choose_placement, savings_estimate,
)


# ---------------------------------------------------------------- 交易所判定
def test_exchange_classification():
    assert exchange_of("600000") is Exchange.SH
    assert exchange_of("688981.SH") is Exchange.SH
    assert exchange_of("000001") is Exchange.SZ
    assert exchange_of("300750") is Exchange.SZ
    assert exchange_of("830799") is Exchange.BJ


# ---------------------------------------------------------------- 契约校验
def test_missing_columns_rejected():
    with pytest.raises(Level2Error):
        validate_trades(pd.DataFrame({"time": [], "code": []}))
    with pytest.raises(Level2Error):
        validate_orders(pd.DataFrame({"time": [], "code": []}))


# ---------------------------------------------------------------- 主动方判定
def test_aggressor_side_from_order_numbers():
    """委托编号大的一方是后到的，即主动方。判反了 OFI 会整体变号。"""
    day = pd.Timestamp("2026-08-21 09:35")
    trades = pd.DataFrame({
        "time": [day, day], "code": ["600000", "600000"],
        "price": [10.0, 10.0], "volume": [1000.0, 2000.0],
        # 第一笔买方编号大 → 主动买；第二笔卖方编号大 → 主动卖
        "bid_order_no": [500, 100], "ask_order_no": [100, 500],
        "trade_type": ["T", "T"],
    })
    f = daily_features(None, trades)
    # 主动买 10000 元，主动卖 20000 元 → ofi = (10000-20000)/30000
    assert f["ofi"].iloc[0] == pytest.approx(-1 / 3, abs=1e-6)


def test_cancelled_trades_excluded_from_amount():
    """trade_type='C' 是撤单记录，不能计入成交额。"""
    day = pd.Timestamp("2026-08-21 09:35")
    trades = pd.DataFrame({
        "time": [day, day], "code": ["600000", "600000"],
        "price": [10.0, 10.0], "volume": [1000.0, 9000.0],
        "bid_order_no": [500, 0], "ask_order_no": [100, 0],
        "trade_type": ["T", "C"],
    })
    f = daily_features(None, trades)
    assert f["amount"].iloc[0] == pytest.approx(10000.0)
    assert f["n_trades"].iloc[0] == 1


# ---------------------------------------------------------------- 沪深不对称
def test_cancel_ratio_works_for_both_exchanges():
    """核心回归测试：沪深撤单编码方式不同，两边都必须算得出非零撤单率。

    这个测试存在的理由：直接用同一套代码处理，沪市的 cancel_ratio 会恒为 0
    而且不报任何错 —— 你会以为沪市股票都不撤单。
    """
    orders, trades, _ = make_synthetic_l2(["600000", "000001"], seed=5, n_trades_per_stock=500)
    feat = daily_features(orders, trades)

    sh = feat.xs("600000", level="code")["cancel_ratio"].iloc[0]
    sz = feat.xs("000001", level="code")["cancel_ratio"].iloc[0]

    assert sh > 0.01, f"沪市撤单率为 {sh:.4f}，说明沪市的撤单（编码在成交表）没被算进去"
    assert sz > 0.01, f"深市撤单率为 {sz:.4f}，说明深市的撤单（编码在委托表）没被算进去"


def test_synthetic_encodes_cancels_differently_by_exchange():
    """确认合成数据本身确实做出了沪深差异 —— 否则上面的测试是空转。"""
    orders, trades, _ = make_synthetic_l2(["600000", "000001"], seed=5, n_trades_per_stock=500)
    sh_cancel_in_trades = ((trades.code == "600000") & (trades.trade_type == "C")).sum()
    sz_cancel_in_trades = ((trades.code == "000001") & (trades.trade_type == "C")).sum()
    sh_cancel_in_orders = ((orders.code == "600000") & (orders.order_type == "CANCEL")).sum()
    sz_cancel_in_orders = ((orders.code == "000001") & (orders.order_type == "CANCEL")).sum()

    assert sh_cancel_in_trades > 0 and sh_cancel_in_orders == 0, "沪市撤单应只出现在成交表"
    assert sz_cancel_in_orders > 0 and sz_cancel_in_trades == 0, "深市撤单应只出现在委托表"


# ---------------------------------------------------------------- 盘口
def test_book_basic_properties():
    b = BookSnapshot([10.00, 9.99], [1000, 2000], [10.01, 10.02], [500, 600])
    assert b.mid == pytest.approx(10.005)
    assert b.spread == pytest.approx(0.01)
    assert b.imbalance > 0, "买量大于卖量时失衡应为正"
    assert b.depth_ahead("buy", 1) == 1000
    assert b.depth_ahead("buy", 2) == 3000


# ---------------------------------------------------------------- 逆向选择
def test_adverse_selection_raises_passive_cost():
    """逆向选择参数必须真实影响被动挂单的期望成本。

    漏掉这一项会让被动挂单看起来白赚半个价差，
    然后你在实盘发现省下的钱远比回测少。
    """
    book = BookSnapshot([12.00, 11.99, 11.98], [50000, 40000, 30000],
                        [12.01, 12.02, 12.03], [200000, 180000, 150000])
    lo = choose_placement(book, "buy", PlacementPolicy(adverse_selection_bps=0.0))
    hi = choose_placement(book, "buy", PlacementPolicy(adverse_selection_bps=12.0))

    lo_p1 = lo["候选对比"].set_index("方案").loc["被动挂第1档", "期望成本bp"]
    hi_p1 = hi["候选对比"].set_index("方案").loc["被动挂第1档", "期望成本bp"]
    assert hi_p1 > lo_p1, "提高逆向选择成本后，被动挂单的期望成本必须上升"


def test_placement_responds_to_book_shape():
    """同样是买入，盘口形态不同应导出不同策略 —— 这才是 L2 的实际价值。"""
    thick_bid = BookSnapshot([12.00] * 3, [300000, 250000, 200000],
                             [12.01, 12.02, 12.03], [30000, 25000, 20000])
    thick_ask = BookSnapshot([12.00, 11.99, 11.98], [30000, 25000, 20000],
                             [12.01] * 3, [300000, 250000, 200000])
    r_bid = choose_placement(thick_bid, "buy")
    r_ask = choose_placement(thick_ask, "buy")
    assert r_bid["推荐方案"] != r_ask["推荐方案"], \
        "买盘厚与卖盘厚应导出不同的挂单策略"


def test_market_order_has_no_adverse_selection():
    """主动吃单不承担逆向选择 —— 你选择了成交时点，不是被别人选中。"""
    book = BookSnapshot([12.00], [50000], [12.01], [50000])
    r = choose_placement(book, "buy")
    row = r["候选对比"].set_index("方案").loc["立即成交(吃单)"]
    assert row["逆向选择bp"] == 0.0
    assert row["成交概率"] == 1.0


# ---------------------------------------------------------------- 成本换算
def test_savings_scale_with_turnover():
    """年化节省应与换手率成正比 —— 这是判断 L2 值不值的唯一算式。"""
    a = savings_estimate(8.0, 4.0, annual_turnover=3.0)
    b = savings_estimate(8.0, 4.0, annual_turnover=6.0)
    assert b["年化节省"] == pytest.approx(2 * a["年化节省"])
    # 单边省 4bp、年换手 6 倍 → 4 * 2 * 6 / 10000 = 0.48%
    assert b["年化节省"] == pytest.approx(0.0048)


def test_attribution_decomposes_slippage():
    f = Fill("600000", "buy", arrival_price=12.00, fill_price=12.018,
             shares=10000, interval_vwap=12.010, close_price=12.05)
    d = f.decompose()
    # 总滑点 = 冲击 + 时机
    assert d["total_bps"] == pytest.approx(d["impact_bps"] + d["timing_bps"], abs=1e-6)
    assert d["total_bps"] > 0, "买入成交价高于决策价，滑点应为正（不利）"


def test_sell_side_sign_convention():
    """卖出时成交价低于决策价才是不利 —— 符号约定搞反会让归因全错。"""
    f = Fill("600000", "sell", arrival_price=12.00, fill_price=11.98,
             shares=10000, interval_vwap=11.99, close_price=11.95)
    assert f.decompose()["total_bps"] > 0, "卖得比决策价低，滑点应为正（不利）"
