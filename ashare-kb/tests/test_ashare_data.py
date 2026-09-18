"""ashare_data 的纯函数测试。

这个沙箱的 egress 策略把东财接口 403 了，实盘取数在这里跑不了。
所以这里测的是**算数**，取数只测降级路径 —— 拿不到数据必须是
inconclusive，不能是任何一种结论。那才是会让库撒谎的分支。
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent   # sys.path 见 conftest.py

import ashare_data as ad  # noqa: E402


# ---------------------------------------------------------------------------
# 季度边界
# ---------------------------------------------------------------------------

def test_current_quarter_is_excluded():
    """半个季度的收益和整个季度的收益不可比。"""
    qs = ad.last_complete_quarters(4, _dt.date(2026, 9, 18))
    assert [q[0] for q in qs] == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert qs[-1][1:] == ("20260401", "20260630")


def test_quarter_boundaries_across_new_year():
    qs = ad.last_complete_quarters(2, _dt.date(2026, 1, 5))
    assert [q[0] for q in qs] == ["2025Q3", "2025Q4"]
    assert qs[-1][1:] == ("20251001", "20251231")


def test_quarter_completes_on_its_first_day_out():
    """4月1日那天，Q1 已经是完整季度。"""
    assert ad.last_complete_quarters(1, _dt.date(2026, 4, 1))[0][0] == "2026Q1"
    assert ad.last_complete_quarters(1, _dt.date(2026, 3, 31))[0][0] == "2025Q4"


@pytest.mark.parametrize("n", [1, 4, 9])
def test_quarters_are_contiguous_and_ordered(n):
    qs = ad.last_complete_quarters(n, _dt.date(2026, 9, 18))
    assert len(qs) == n
    starts = [q[1] for q in qs]
    assert starts == sorted(starts)          # 早的在前
    for (_, _, end), (_, start, _) in zip(qs, qs[1:]):
        gap = (_dt.datetime.strptime(start, "%Y%m%d")
               - _dt.datetime.strptime(end, "%Y%m%d")).days
        assert gap == 1                       # 无空档、无重叠


# ---------------------------------------------------------------------------
# 区间涨跌幅
# ---------------------------------------------------------------------------

ROWS = [("20251231", 100.0), ("20260105", 110.0), ("20260630", 90.0), ("20260701", 95.0)]


def test_base_is_the_close_before_the_window():
    """区间涨跌幅以区间开始前最后一个交易日收盘价为基准，不是区间内第一根。"""
    assert ad.window_return(ROWS, "20260101", "20260630") == pytest.approx(-0.10)


def test_days_after_the_window_are_ignored():
    assert ad.window_return(ROWS, "20260101", "20260105") == pytest.approx(0.10)


def test_new_listing_is_excluded_not_zero():
    """区间内新上市 -> None。当成 0.0 会把中位数往上拉，而断言比的正是中位数。"""
    rows = [("20260105", 50.0), ("20260630", 80.0)]
    assert ad.window_return(rows, "20260101", "20260630") is None


def test_no_trading_inside_the_window_is_excluded():
    rows = [("20251231", 100.0), ("20260701", 95.0)]
    assert ad.window_return(rows, "20260101", "20260630") is None


def test_nonpositive_base_is_excluded():
    rows = [("20251231", 0.0), ("20260630", 90.0)]
    assert ad.window_return(rows, "20260101", "20260630") is None


def test_delisted_midway_still_counts():
    """区间内退市的按最后一个交易日计入 —— 那是诚实的中位数的一部分。"""
    rows = [("20251231", 100.0), ("20260210", 40.0)]
    assert ad.window_return(rows, "20260101", "20260630") == pytest.approx(-0.60)


# ---------------------------------------------------------------------------
# 中位数 / 宽度
# ---------------------------------------------------------------------------

def test_median_odd_and_even():
    assert ad.median([0.1, -0.2, 0.3]) == pytest.approx(0.1)
    assert ad.median([0.1, -0.2, 0.3, 0.5]) == pytest.approx(0.2)
    assert ad.median([]) is None


def test_flat_does_not_count_as_up():
    assert ad.breadth([0.1, 0.0, -0.1, 0.2]) == (2, 4)


# ---------------------------------------------------------------------------
# 列名识别 / 缓存
# ---------------------------------------------------------------------------

class FakeDF:
    """够用的假 DataFrame —— 只为测列名识别，不引入 pandas 依赖。"""

    def __init__(self, data):
        self._d = data
        self.columns = list(data)

    def __getitem__(self, k):
        return self._d[k]


@pytest.mark.parametrize("date_col,close_col", [("日期", "收盘"), ("date", "close")])
def test_column_names_are_found_by_name(date_col, close_col):
    df = FakeDF({date_col: ["2026-01-05", "2026-06-30"], close_col: [110.0, 90.0],
                 "开盘": [1, 2]})
    assert ad._extract_closes(df) == [("20260105", 110.0), ("20260630", 90.0)]


def test_unknown_columns_raise_rather_than_guess():
    """列名认不出就抛，让调用方转成 inconclusive —— 不按位置猜。"""
    with pytest.raises(KeyError):
        ad._extract_closes(FakeDF({"a": ["2026-01-05"], "b": [1.0]}))


def test_cache_round_trip(tmp_path):
    p = tmp_path / "x.csv"
    ad._write_cache(p, [("20260105", 110.0), ("20260630", 90.0)])
    assert ad._read_cache(p) == [("20260105", 110.0), ("20260630", 90.0)]
    assert not p.with_suffix(".tmp").exists()   # 原子替换，不留半截文件


def test_corrupt_cache_is_treated_as_absent(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("这不是CSV\n", encoding="utf-8")
    assert ad._read_cache(p) is None


def test_missing_cache_is_none(tmp_path):
    assert ad._read_cache(tmp_path / "nope.csv") is None


# ---------------------------------------------------------------------------
# 降级路径 —— 拿不到数据必须是 inconclusive
# ---------------------------------------------------------------------------

def test_missing_akshare_is_inconclusive(monkeypatch):
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def blocked(name, *a, **k):
        if name == "akshare":
            raise ImportError("no akshare")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", blocked)
    with pytest.raises(SystemExit) as exc:
        ad.require_akshare()
    assert exc.value.code == ad.kv.RC_INCONCLUSIVE   # 2，不是 0 也不是 1
