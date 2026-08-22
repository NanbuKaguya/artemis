"""数据体检的回归测试。

这组测试守护的是一个具体的失败场景：拿只有 OHLCV 的数据跑整套系统，
micro_cap 规则剔除 0%、size/turnover 因子全空、中性化完全不起作用，
**而这一切都不报错**。静默降级比崩溃危险，因为你会拿它去做决策。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.alpha import factors as F
from artemis.data.preflight import assert_ready, check, report
from artemis.data.synthetic import make_market


@pytest.fixture(scope="module")
def good_bars():
    bars, _ = make_market(n_stocks=120, n_days=900, seed=7)
    return bars


@pytest.fixture(scope="module")
def akshare_like(good_bars):
    """AkShare 的 stock_zh_a_hist 实际只返回 OHLCV。"""
    b = good_bars.copy()
    b["total_mv"] = np.nan
    b["float_mv"] = np.nan
    b["industry"] = "未知"
    b["is_st"] = False
    return b


# ---------------------------------------------------------------- 无误报
def test_clean_data_passes_without_false_alarms(good_bars):
    """完整数据必须全绿。会喊狼来了的体检器等于没有体检器。"""
    df = check(good_bars)
    bad = df[df.status != "ok"]
    assert bad.empty, f"完整数据被误报：\n{bad[['capability','status','detail']]}"
    assert_ready(good_bars)


# ---------------------------------------------------------------- 检出缺口
def test_missing_market_cap_is_detected(akshare_like):
    df = check(akshare_like).set_index("capability")
    assert df.loc["市值排雷 + 市值中性化", "status"] == "dead"
    assert df.loc["换手率因子", "status"] == "dead"


def test_constant_columns_count_as_dead(akshare_like):
    """industry 全是"未知"、is_st 全是 False，等同于没有这项信息。"""
    df = check(akshare_like).set_index("capability")
    assert df.loc["行业中性化 + 行业约束", "status"] in ("dead", "degraded")
    assert df.loc["ST 排雷", "status"] in ("dead", "degraded")


def test_assert_ready_blocks_degraded_data(akshare_like):
    with pytest.raises(ValueError, match="静默"):
        assert_ready(akshare_like)
    # 明确知情时可以放行
    assert_ready(akshare_like, allow_degraded=True)


# ---------------------------------------------------------------- 幸存者偏差
def test_survivorship_bias_is_caught(good_bars):
    """只保留活到最后的股票 —— 最经典的幸存者偏差，必须被识破。"""
    last = good_bars.index.get_level_values("date").max()
    survivors = set(good_bars.loc[last].index)
    biased = good_bars[good_bars.index.get_level_values("code").isin(survivors)]

    row = check(biased).set_index("capability").loc["退市处理"]
    assert row["status"] == "dead"
    assert "幸存者偏差" in row["detail"]


def test_survivorship_ok_when_delistings_present(good_bars):
    row = check(good_bars).set_index("capability").loc["退市处理"]
    assert row["status"] == "ok"
    assert "消失" in row["detail"]


def test_short_sample_not_flagged_for_survivorship():
    """样本不足两年时退市样本少属正常，不该误报。"""
    bars, _ = make_market(n_stocks=60, n_days=200, seed=3)
    row = check(bars).set_index("capability").loc["退市处理"]
    assert row["status"] == "ok"


# ---------------------------------------------------------------- 中性化告警
def test_neutralize_warns_when_regressors_unavailable(akshare_like):
    """中性化跳过时必须发出 RuntimeWarning，不能静默返回。"""
    raw = F.compute(akshare_like, ["momentum_120_20"])["momentum_120_20"]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        F.prepare(raw, akshare_like)
    msgs = [str(x.message) for x in w if issubclass(x.category, RuntimeWarning)]
    assert any("中性化被跳过" in m for m in msgs), "中性化失效时必须告警"


def test_neutralize_silent_on_good_data(good_bars):
    raw = F.compute(good_bars, ["momentum_120_20"])["momentum_120_20"]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        F.prepare(raw, good_bars)
    msgs = [str(x.message) for x in w if issubclass(x.category, RuntimeWarning)]
    assert not any("中性化被跳过" in m for m in msgs), "完整数据不该告警"


# ---------------------------------------------------------------- 报告可读
def test_report_names_the_consequence(akshare_like):
    """报告必须说清"后果"，而不只是"缺了什么" —— 前者才会让人去补。"""
    txt = report(akshare_like)
    assert "静默" in txt
    assert "补法" in txt
    assert "micro_cap" in txt
