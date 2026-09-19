"""收盘账本：把「昨日真相」从 N 次请求变成 0 次请求。

设计上的纠正：上一版为了拿昨日真实值，改成每只票拉一次日线 ——
30 只自选股就是 30 次请求、20 秒、外加限频风险。但全市场快照本来
就是一次请求拿 5400 只，且带交易所口径的涨跌幅/成交额/换手率。

问题从来不在「快照」，而在「哪一天的快照」：开盘前的当日快照是空的，
昨天收盘的快照才是昨日真相。
"""

from __future__ import annotations

import pandas as pd
import pytest

CODES = ["600519", "000001", "600001", "600002", "301888"]
NAMES = ["贵州茅台", "平安银行", "某停牌股", "昨日涨停股", "某妖股"]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "cache"))


@pytest.fixture
def ledger(monkeypatch):
    """造 22 个交易日的收盘账本，内嵌停牌 / 昨日涨停 / 换手过热。"""
    import artemis.lite as L

    days = pd.bdate_range("2026-08-13", periods=22)
    by_day = {}
    for i, d in enumerate(days):
        rows = []
        for c, n in zip(CODES, NAMES):
            amt, pct, tr = 30e8, 0.5, 2.0
            if c == "600001" and i >= 18:          # 最后 4 天停牌
                amt, pct, tr = 0.0, 0.0, 0.0
            if c == "600002" and i == len(days) - 1:
                pct = 10.0                          # 昨日涨停
            if c == "301888":
                tr = 38.0                           # 换手过热
            rows.append({"code": c, "name": n, "price": 20.0, "pct_chg": pct,
                         "amount": amt, "total_mv": 300e8, "float_mv": 200e8,
                         "turnover_rate": tr})
        snap = pd.DataFrame(rows)
        L.save_snapshot(snap, d.date())
        by_day[d.date()] = snap

    monkeypatch.setattr(L, "fetch_snapshot", lambda: by_day[days[-1].date()])
    monkeypatch.setattr(L, "_market_last_trading_day",
                        lambda: pd.Timestamp(days[-1].date()))
    return days, by_day


def test_ledger_path_makes_zero_network_requests(ledger, monkeypatch):
    """账本够用时不许发任何逐只请求 —— 这是整个改动的理由。"""
    import artemis.lite as L

    def boom(*a, **k):
        raise AssertionError("账本够用时不该逐只拉取")

    monkeypatch.setattr(L, "fetch_recent_stats", boom)
    df = L.check(CODES, with_history=True)
    assert df.attrs["source"] == "ledger"
    assert df.attrs["ledger"].days == 22


def test_suspended_stock_caught_by_zero_amount(ledger):
    """停牌有两种长相，取决于数据从哪来：

      逐只日线 —— 停牌日没有行，表现为「最后交易日早于市场最后交易日」
      收盘账本 —— 停牌股照样在全市场快照里，只是成交额为 0

    写成 if/elif 会漏掉后者：账本路径下 last_date 永远已知，
    零成交那条分支永远进不去，停牌股一路「✓ 通过」。
    这个 bug 真的发生过 —— 就在引入账本的那一版。
    """
    import artemis.lite as L

    df = L.check(CODES, with_history=True).set_index("代码")
    assert df.loc["600001", "结论"] == "❌ 排除"
    assert "停牌" in df.loc["600001", "踩雷"]


def test_limit_up_uses_exchange_reported_pct(ledger):
    """涨跌幅直接取账本里源头给的那一列，不自己用收盘价相除。"""
    import artemis.lite as L

    df = L.check(CODES, with_history=True).set_index("代码")
    assert "昨日涨停" in df.loc["600002", "踩雷"]
    assert df.loc["600519", "结论"] == "✓ 通过"


def test_turnover_prefers_source_column(ledger):
    """换手率用交易所口径，不用 成交额/流通市值 自算 ——
    后者分母含价格，价格大幅变动时会偏。"""
    import artemis.lite as L

    df = L.check(CODES, with_history=True).set_index("代码")
    assert df.loc["301888", "结论"] == "⚠ 注意"
    assert "换手过热" in df.loc["301888", "提示"]


def test_thin_ledger_falls_back_and_says_so(monkeypatch):
    """账本不足 / 过期时必须回退到逐只拉取，并在凭证里讲明白。"""
    import artemis.lite as L

    snap = pd.DataFrame([{"code": "600519", "name": "贵州茅台", "price": 1680.0,
                          "pct_chg": 0.3, "amount": 40e8, "total_mv": 2.1e12,
                          "float_mv": 2.1e12, "turnover_rate": 0.2}])
    L.save_snapshot(snap, pd.Timestamp("2026-08-01").date())   # 只有一天，且很旧
    monkeypatch.setattr(L, "fetch_snapshot", lambda: snap)
    monkeypatch.setattr(L, "_market_last_trading_day",
                        lambda: pd.Timestamp("2026-09-11"))
    called = {"n": 0}

    def fake(codes, **kw):
        called["n"] += 1
        return {}, len(codes)

    monkeypatch.setattr(L, "fetch_recent_stats", fake)
    df = L.check(["600519"], with_history=True)
    assert called["n"] == 1, "账本过期必须回退"
    assert df.attrs["source"] != "ledger"


def test_provenance_is_printed_every_run_not_only_on_error(ledger):
    """凭证每次都打。只在异常时出现的提示，看多了就是墙纸。"""
    import artemis.lite as L

    df = L.check(CODES, with_history=True)
    text = L.data_provenance(df)
    assert "数据凭证" in text
    assert "收盘账本" in text and "零联网" in text


def test_short_ledger_warns_liquidity_window_is_incomplete(monkeypatch):
    """账本不足 20 天时，20 日均额是不足窗口的均值 —— 必须说出来。"""
    import artemis.lite as L

    days = pd.bdate_range("2026-09-01", periods=5)
    snap = None
    for d in days:
        snap = pd.DataFrame([{"code": "600519", "name": "贵州茅台", "price": 1680.0,
                              "pct_chg": 0.3, "amount": 40e8, "total_mv": 2.1e12,
                              "float_mv": 2.1e12, "turnover_rate": 0.2}])
        L.save_snapshot(snap, d.date())
    monkeypatch.setattr(L, "fetch_snapshot", lambda: snap)
    monkeypatch.setattr(L, "_market_last_trading_day",
                        lambda: pd.Timestamp(days[-1].date()))
    df = L.check(["600519"], with_history=True)
    assert "只有 5 天" in L.data_provenance(df)


def test_snapshot_command_refuses_on_non_trading_day(monkeypatch, capsys):
    """非交易日不存账本 —— 否则会把上一交易日的收盘值重复计入均额窗口。"""
    import artemis.lite as L

    class Cal:
        def is_trading_day(self):
            return False, "cached"

    monkeypatch.setattr("artemis.calendar.TradingCalendar", Cal)
    L.cmd_snapshot([])
    assert "不是交易日" in capsys.readouterr().out
