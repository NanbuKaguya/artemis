"""Artemis Lite 的回归测试。

Lite 是给"不上全系统"路径准备的最小可用集。它的测试重点不是算法精度，
而是**在数据不完整时是否诚实** —— 因为它面对的正是数据最简陋的场景。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.config import GuardConfig
from artemis.lite import check, check_one, normalize_snapshot


@pytest.fixture
def snap():
    raw = pd.DataFrame([
        {"代码": "600519", "名称": "贵州茅台", "最新价": 1680.0, "涨跌幅": 1.2,
         "成交额": 45e8, "总市值": 2.1e12, "流通市值": 2.1e12, "换手率": 0.3},
        {"代码": "000001", "名称": "平安银行", "最新价": 11.5, "涨跌幅": 9.98,
         "成交额": 38e8, "总市值": 2200e8, "流通市值": 2200e8, "换手率": 2.1},
        {"代码": "600666", "名称": "*ST瑞康", "最新价": 1.85, "涨跌幅": -4.6,
         "成交额": 0.3e8, "总市值": 18e8, "流通市值": 15e8, "换手率": 3.2},
        {"代码": "300999", "名称": "某冷门股", "最新价": 8.2, "涨跌幅": 0.5,
         "成交额": 0.12e8, "总市值": 25e8, "流通市值": 20e8, "换手率": 0.8},
        {"代码": "301888", "名称": "某妖股", "最新价": 42.0, "涨跌幅": 15.3,
         "成交额": 30e8, "总市值": 180e8, "流通市值": 90e8, "换手率": 38.5},
    ])
    return normalize_snapshot(raw)


def test_snapshot_contract(snap):
    assert list(snap.columns) == ["code", "name", "price", "pct_chg", "amount",
                                  "total_mv", "float_mv", "turnover_rate"]
    assert snap["code"].str.len().eq(6).all()


def test_missing_required_column_raises_with_actual_names():
    """列名对不上时必须把真实列名打出来 —— AkShare 的中文列名跨版本会变。"""
    with pytest.raises(ValueError, match="实际列名"):
        normalize_snapshot(pd.DataFrame({"foo": [1], "bar": [2]}))


# ---------------------------------------------------------------- 排雷判定
def test_st_detected_from_name(snap):
    """ST 状态藏在名称里，这是 Lite 不需要额外数据源的关键。"""
    r = check(["600666"], snapshot=snap, with_adv20=False).iloc[0]
    assert r["结论"] == "❌ 排除"
    assert "ST" in r["踩雷"]


def test_delisting_marker_in_name_also_caught():
    raw = pd.DataFrame([{"代码": "600123", "名称": "退市博元", "最新价": 0.9,
                         "涨跌幅": -3.0, "成交额": 0.05e8, "总市值": 5e8,
                         "流通市值": 5e8, "换手率": 1.0}])
    r = check(["600123"], snapshot=normalize_snapshot(raw), with_adv20=False).iloc[0]
    assert r["结论"] == "❌ 排除"


def test_limit_up_blocks_buy(snap):
    """涨停买不进 —— 与回测引擎的行为必须一致。"""
    r = check(["000001"], snapshot=snap, with_adv20=False).iloc[0]
    assert r["结论"] == "❌ 排除"
    assert "涨停" in r["踩雷"]


def test_board_specific_limit_threshold():
    """创业板 20% 才算涨停，用主板的 10% 会误杀。"""
    raw = pd.DataFrame([{"代码": "300750", "名称": "宁德时代", "最新价": 200.0,
                         "涨跌幅": 12.0, "成交额": 50e8, "总市值": 8000e8,
                         "流通市值": 7000e8, "换手率": 1.5}])
    r = check(["300750"], snapshot=normalize_snapshot(raw), with_adv20=False).iloc[0]
    assert r["结论"] != "❌ 排除", "创业板涨 12% 未到 20% 涨停，不该被判涨停"


def test_clean_stock_passes(snap):
    r = check(["600519"], snapshot=snap, with_adv20=False).iloc[0]
    assert r["结论"] == "✓ 通过"


def test_warn_does_not_block(snap):
    """换手过热是提示不是否决 —— 分级很重要，否则清单会空。"""
    r = check(["301888"], snapshot=snap, with_adv20=False).iloc[0]
    assert r["结论"] == "⚠ 注意"


def test_missing_codes_reported(snap):
    df = check(["600519", "999999"], snapshot=snap, with_adv20=False)
    assert df.attrs.get("missing") == ["999999"]


# ---------------------------------------------------------------- 诚实性
def test_unavailable_check_says_so_not_silently_passes():
    """拿不到 20 日均额时，流动性这条必须说"未检"，不能装作通过。

    这是 Lite 最重要的性质：数据缺失时诚实标注，而不是静默放行。
    """
    row = pd.Series({"code": "600000", "name": "浦发银行", "price": 10.0,
                     "pct_chg": 0.5, "amount": 5e8, "total_mv": 3000e8,
                     "float_mv": 3000e8, "turnover_rate": 1.0})
    mines = {m.rule: m for m in check_one(row, GuardConfig(), adv20=None)}
    assert "未检" in mines["流动性"].detail
    assert mines["流动性"].hit is False


def test_missing_market_cap_says_unchecked():
    row = pd.Series({"code": "600000", "name": "浦发银行", "price": 10.0,
                     "pct_chg": 0.5, "amount": 5e8, "total_mv": np.nan,
                     "float_mv": np.nan, "turnover_rate": 1.0})
    mines = {m.rule: m for m in check_one(row, GuardConfig())}
    assert "缺失" in mines["市值下限"].detail
    assert mines["市值下限"].hit is False, "数据缺失不该被当成踩雷"


def test_low_price_rule():
    row = pd.Series({"code": "600000", "name": "某低价股", "price": 1.5,
                     "pct_chg": 0.0, "amount": 2e8, "total_mv": 50e8,
                     "float_mv": 40e8, "turnover_rate": 2.0})
    mines = {m.rule: m for m in check_one(row, GuardConfig())}
    assert mines["低价股（面值退市）"].hit
