"""Point-in-time 正确性测试。

这组测试比摩擦测试更重要，因为 PIT 错误是**静默的**：
它不报错，不崩溃，只是让你的回测凭空多出一块 alpha，
然后你满怀信心地上实盘，再慢慢把钱还回去。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.data.fundamentals import (
    align_to_bars, build_pit_series, cumulative_to_single,
    make_synthetic_pit, validate_pit, PITError,
)


# ---------------------------------------------------------------- 累计转单季
def test_cumulative_to_single_full_year():
    periods = pd.to_datetime(["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31"])
    cum = pd.Series([100.0, 250.0, 420.0, 600.0])
    single = cumulative_to_single(pd.Series(periods), cum)
    assert list(single.values) == [100.0, 150.0, 170.0, 180.0]


def test_cumulative_resets_each_fiscal_year():
    """跨年必须重置累计基准 —— 否则 Q1 会被算成"年报到一季报的差"，成为巨大负数。"""
    periods = pd.to_datetime(["2020-09-30", "2020-12-31", "2021-03-31"])
    cum = pd.Series([420.0, 600.0, 110.0])
    single = cumulative_to_single(pd.Series(periods), cum)
    assert single.iloc[-1] == 110.0, "新年度 Q1 的单季值应等于其累计值"


def test_missing_quarter_yields_nan_not_a_guess():
    """中间季度缺失时返回 NaN。猜出来的数字会变成假因子。"""
    periods = pd.to_datetime(["2020-03-31", "2020-12-31"])   # 缺 Q2/Q3
    single = cumulative_to_single(pd.Series(periods), pd.Series([100.0, 600.0]))
    assert np.isnan(single.iloc[-1])


# ---------------------------------------------------------------- PIT 核心
def _bars(dates, codes):
    idx = pd.MultiIndex.from_product([pd.to_datetime(dates), codes], names=["date", "code"])
    return pd.DataFrame({"close": 10.0}, index=idx)


def test_value_is_unknown_before_announcement():
    """报告期已过但尚未公告时，该值必须是 NaN，不能提前可见。"""
    pit = pd.DataFrame([
        # 2020 年报，报告期 12-31，但 2021-04-20 才公告
        {"code": "600000", "report_period": "2020-12-31", "ann_date": "2021-04-20",
         "field": "total_assets", "value": 1000.0},
    ])
    bars = _bars(["2021-01-05", "2021-04-19", "2021-04-20", "2021-06-01"], ["600000"])
    out = align_to_bars(pit, bars, ["total_assets"])
    v = out["total_assets"].droplevel("code")

    assert np.isnan(v.loc["2021-01-05"]), "报告期已过但未公告，不该可见"
    assert np.isnan(v.loc["2021-04-19"]), "公告前一天仍不该可见"
    assert v.loc["2021-04-20"] == 1000.0, "公告当日应可见"
    assert v.loc["2021-06-01"] == 1000.0, "公告后应持续可见"


def test_restatement_uses_version_known_at_the_time():
    """追溯调整：T 时刻必须看到 T 时刻那一版，而不是数据库里的最终版。

    这是 PIT 最刁钻的一条。用最终版做回测，等于你提前知道了会计差错更正 ——
    而差错更正的方向往往和股价走势高度相关。
    """
    pit = pd.DataFrame([
        {"code": "600000", "report_period": "2020-12-31", "ann_date": "2021-04-20",
         "field": "total_assets", "value": 1000.0},          # 首次公告
        {"code": "600000", "report_period": "2020-12-31", "ann_date": "2021-09-15",
         "field": "total_assets", "value": 700.0},           # 半年后追溯下修
    ])
    bars = _bars(["2021-05-01", "2021-09-14", "2021-09-15", "2021-12-01"], ["600000"])
    v = align_to_bars(pit, bars, ["total_assets"])["total_assets"].droplevel("code")

    assert v.loc["2021-05-01"] == 1000.0, "修正前应看到原值 1000"
    assert v.loc["2021-09-14"] == 1000.0, "修正前一天仍是原值"
    assert v.loc["2021-09-15"] == 700.0, "修正当日起才看到 700"
    assert v.loc["2021-12-01"] == 700.0


def test_annual_report_announced_after_next_q1():
    """A 股常见：上年年报比本年一季报还晚公告。

    此时在两份报告之间的日子里，"最新已知报告期"是 Q1 还是年报？
    必须按公告日推进，而不是按报告期排序。
    """
    pit = pd.DataFrame([
        {"code": "600000", "report_period": "2021-03-31", "ann_date": "2021-04-22",
         "field": "total_assets", "value": 500.0},           # Q1 先公告
        {"code": "600000", "report_period": "2020-12-31", "ann_date": "2021-04-25",
         "field": "total_assets", "value": 900.0},           # 年报后公告
    ])
    bars = _bars(["2021-04-23", "2021-04-26"], ["600000"])
    v = align_to_bars(pit, bars, ["total_assets"])["total_assets"].droplevel("code")

    assert v.loc["2021-04-23"] == 500.0, "只公告了 Q1 时，应取 Q1 的值"
    # 年报公告后，最新报告期仍是 2021-03-31（Q1），时点值取最新报告期
    assert v.loc["2021-04-26"] == 500.0, "年报报告期更早，不应覆盖更新的 Q1 时点值"


def test_ttm_needs_four_quarters():
    """TTM 在不足四个单季时返回 NaN，而不是用两三个季度硬凑。"""
    rows = []
    for i, (p, a, val) in enumerate([
        ("2020-03-31", "2020-04-25", 100.0),
        ("2020-06-30", "2020-08-25", 250.0),
    ]):
        rows.append({"code": "600000", "report_period": p, "ann_date": a,
                     "field": "net_profit", "value": val})
    ser = build_pit_series(pd.DataFrame(rows), "net_profit", kind="flow")
    assert ser["value"].isna().all(), "不足四季时 TTM 应为 NaN"


def test_ttm_correct_with_four_quarters():
    rows = [
        ("2020-03-31", "2020-04-25", 100.0),
        ("2020-06-30", "2020-08-25", 250.0),
        ("2020-09-30", "2020-10-25", 420.0),
        ("2020-12-31", "2021-04-25", 600.0),
    ]
    df = pd.DataFrame([{"code": "600000", "report_period": p, "ann_date": a,
                        "field": "net_profit", "value": v} for p, a, v in rows])
    ser = build_pit_series(df, "net_profit", kind="flow")
    # 全年四个单季 100+150+170+180 = 600
    assert ser["value"].iloc[-1] == pytest.approx(600.0)


def test_missing_ann_date_is_rejected_loudly():
    """没有公告日的财务数据必须拒收，不能静默用报告期顶替。"""
    bad = pd.DataFrame([{"code": "600000", "report_period": "2020-12-31",
                         "field": "net_profit", "value": 1.0}])
    with pytest.raises(PITError, match="ann_date"):
        validate_pit(bad)


def test_extra_lag_shifts_visibility():
    """min_report_lag_days 提供额外的保守缓冲。"""
    pit = pd.DataFrame([
        {"code": "600000", "report_period": "2020-12-31", "ann_date": "2021-04-20",
         "field": "total_assets", "value": 1000.0},
    ])
    bars = _bars(["2021-04-20", "2021-04-22"], ["600000"])
    v0 = align_to_bars(pit, bars, ["total_assets"], min_report_lag_days=0)["total_assets"]
    v2 = align_to_bars(pit, bars, ["total_assets"], min_report_lag_days=2)["total_assets"]
    assert v0.droplevel("code").loc["2021-04-20"] == 1000.0
    assert np.isnan(v2.droplevel("code").loc["2021-04-20"]), "加了 2 天缓冲后当日不可见"
    assert v2.droplevel("code").loc["2021-04-22"] == 1000.0


def test_no_lookahead_on_synthetic_panel():
    """全景检验：合成面板上，任何 (date, code) 的取值都必须能追溯到
    一条 ann_date <= date 的公告。"""
    codes = [f"60000{i}" for i in range(5)]
    pit = validate_pit(make_synthetic_pit(codes, "2018-01-01", "2020-12-31", seed=7))
    dates = pd.bdate_range("2018-01-01", "2020-12-31")
    bars = _bars(dates, codes)
    out = align_to_bars(pit, bars, ["total_assets"])

    sub = pit[pit.field == "total_assets"]
    first_ann = sub.groupby("code")["ann_date"].min()
    got = out["total_assets"].dropna()
    for (d, c) in got.index[:2000]:
        assert d >= first_ann[c], f"{c} 在首次公告 {first_ann[c]} 之前就有值（{d}）"
