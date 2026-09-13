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
    r = check(["600666"], snapshot=snap, with_history=False).iloc[0]
    assert r["结论"] == "❌ 排除"
    assert "ST" in r["踩雷"]


def test_delisting_marker_in_name_also_caught():
    raw = pd.DataFrame([{"代码": "600123", "名称": "退市博元", "最新价": 0.9,
                         "涨跌幅": -3.0, "成交额": 0.05e8, "总市值": 5e8,
                         "流通市值": 5e8, "换手率": 1.0}])
    r = check(["600123"], snapshot=normalize_snapshot(raw), with_history=False).iloc[0]
    assert r["结论"] == "❌ 排除"


def test_yesterday_limit_up_blocks_buy():
    """昨日涨停要拦下 —— 今日大概率高开，追进去就是接盘。

    注意口径：判据是**昨日真实涨幅**，不是快照里的当日涨跌幅。
    watch 设计在开盘前跑，那时当日涨跌幅尚未产生。
    """
    from artemis.lite import RecentStats, check_one

    row = pd.Series({"code": "000001", "name": "平安银行", "price": 11.5,
                     "pct_chg": 0.0, "amount": 38e8, "total_mv": 2200e8,
                     "float_mv": 2200e8, "turnover_rate": 0.0})
    mkt = pd.Timestamp("2026-09-11")
    st = RecentStats(adv20=38e8, last_date=mkt, last_close=11.0,
                     prev_close=10.0, last_amount=38e8)      # 昨日 +10%
    mines = {m.rule: m for m in check_one(row, GuardConfig(), st, mkt)}
    assert mines["昨日涨停（今日易高开）"].hit


def test_suspended_stock_is_blocked():
    """停牌股必须排除 —— 此前完全没有这条检查，停牌股会进入当日清单。"""
    from artemis.lite import RecentStats, check_one

    row = pd.Series({"code": "600001", "name": "某停牌股", "price": 15.3,
                     "pct_chg": 0.0, "amount": 0.0, "total_mv": 120e8,
                     "float_mv": 100e8, "turnover_rate": 0.0})
    mkt = pd.Timestamp("2026-09-11")
    st = RecentStats(adv20=3e8, last_date=pd.Timestamp("2026-08-20"),
                     last_close=15.3, prev_close=15.3, last_amount=0.0)
    mines = {m.rule: m for m in check_one(row, GuardConfig(), st, mkt)}
    assert mines["停牌"].hit and mines["停牌"].severity == "block"


def test_intraday_snapshot_fields_not_used_for_limit_up():
    """回归测试：快照的当日涨跌幅不得再用于涨停判定。

    开盘前它是 0 或残留值。曾经的实现直接拿它判「当日涨停」，
    等于在检查一个尚未产生的数。
    """
    src = Path(__file__).resolve().parents[1] / "artemis" / "lite.py"
    body = src.read_text(encoding="utf-8")
    fn = body[body.index("def check_one("):body.index("def check(codes")]
    assert 'row.get("pct_chg"' not in fn, "check_one 不应再读取快照的当日涨跌幅"
    assert "stats.last_pct" in fn, "应改用昨日真实涨幅"


def test_board_specific_limit_threshold():
    """创业板 20% 才算涨停，用主板的 10% 会误杀。"""
    raw = pd.DataFrame([{"代码": "300750", "名称": "宁德时代", "最新价": 200.0,
                         "涨跌幅": 12.0, "成交额": 50e8, "总市值": 8000e8,
                         "流通市值": 7000e8, "换手率": 1.5}])
    r = check(["300750"], snapshot=normalize_snapshot(raw), with_history=False).iloc[0]
    assert r["结论"] != "❌ 排除", "创业板涨 12% 未到 20% 涨停，不该被判涨停"


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """把缓存根目录指到临时目录。

    此前这些测试读的是仓库里真实的 data_cache/journal_prices.parquet，
    于是 monkeypatch 的假行情压根没被用上 —— 几条 journal 测试是
    "碰巧过的"，改坏了也照样绿。顺带覆盖了 ARTEMIS_DATA_DIR 这条路径。
    """
    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "cache"))


def test_clean_stock_passes(snap):
    r = check(["600519"], snapshot=snap, with_history=False).iloc[0]
    assert r["结论"] == "✓ 通过"


def test_warn_does_not_block(snap, monkeypatch):
    """换手过热是提示不是否决 —— 分级很重要，否则清单会空。

    换手率现在由「昨日成交额 / 流通市值」算出，不再用快照里的日内值，
    所以要喂一份 stats 才能触发这条 warn。
    """
    import artemis.lite as lite

    fmv = float(snap.set_index("code").loc["301888", "float_mv"])
    st = lite.RecentStats(
        adv20=fmv * 0.4, last_date=pd.Timestamp("2026-09-11"),
        last_close=42.0, prev_close=41.9,          # 昨日几乎没涨，不触发涨停
        last_amount=fmv * 0.4,                     # 昨日换手 40% > 25% 红线
    )
    monkeypatch.setattr(lite, "fetch_recent_stats",
                        lambda codes, **kw: ({c: st for c in codes}, 0))
    monkeypatch.setattr(lite, "fetch_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(lite, "_market_last_trading_day",
                        lambda: pd.Timestamp("2026-09-11"))

    r = lite.check(["301888"], with_history=True).iloc[0]
    assert r["结论"] == "⚠ 注意", f"应为提示而非排除：{r.to_dict()}"
    assert "换手过热" in r["提示"]


def test_missing_codes_reported(snap):
    df = check(["600519", "999999"], snapshot=snap, with_history=False)
    assert df.attrs.get("missing") == ["999999"]


# ---------------------------------------------------------------- 诚实性
def test_no_history_marks_every_flow_rule_unchecked():
    """拿不到历史时，所有流量类规则必须标"未检"，不能装作通过。

    这是 Lite 最重要的性质：数据缺失时诚实标注，而不是静默放行。
    """
    row = pd.Series({"code": "600000", "name": "浦发银行", "price": 10.0,
                     "pct_chg": 0.5, "amount": 5e8, "total_mv": 3000e8,
                     "float_mv": 3000e8, "turnover_rate": 1.0})
    mines = {m.rule: m for m in check_one(row, GuardConfig(), stats=None)}
    for rule in ("停牌", "昨日涨停", "流动性", "昨日成交清淡", "换手过热"):
        assert "未检" in mines[rule].detail, f"{rule} 应标注未检"
        assert mines[rule].hit is False


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


# ---------------------------------------------------------------- 静默失效
def test_recent_stats_counts_failures_instead_of_swallowing(monkeypatch):
    """全部拉取失败时必须计数并告警。

    原实现是 except: pass，用户只会看到"流动性: 未检"，
    分不清是"没查"还是"查了但全失败"。这正是本项目一直在防的
    静默失效，而它曾经就出在这个函数里。
    """
    import sys
    import types

    fake = types.ModuleType("akshare")

    def boom(**kw):
        raise RuntimeError("模拟限频")
    fake.stock_zh_a_hist = boom
    monkeypatch.setitem(sys.modules, "akshare", fake)

    from artemis.lite import fetch_recent_stats
    out, failed = fetch_recent_stats(["600519", "000001"], sleep=0.0, progress=False)
    assert out == {}
    assert failed == 2, "失败必须被计数，不能静默吞掉"


def test_check_exposes_history_failure_count(snap):
    """失败数要透出到结果上，否则调用方无从判断 ✓ 的含金量。"""
    df = check(["600519"], snapshot=snap, with_history=False)
    assert "history_failed" in df.attrs


# ---------------------------------------------------------------- 收益对账
def _fake_akshare(monkeypatch, drift_map: dict[str, float]):
    import sys
    import types

    import numpy as np

    fake = types.ModuleType("akshare")

    def hist(symbol=None, **kw):
        rng = np.random.default_rng(abs(hash(symbol)) % 10000)
        dates = pd.bdate_range("2026-04-01", "2026-08-20")
        d = drift_map.get(symbol, 0.0)
        px = 20 * np.cumprod(1 + rng.normal(d, 0.012, len(dates)))
        return pd.DataFrame({"日期": dates.strftime("%Y-%m-%d"), "收盘": px})

    fake.stock_zh_a_hist = hist
    monkeypatch.setitem(sys.modules, "akshare", fake)


def _journal_df(n=10, source="system", code="600000", start="2026-05-01", side="buy"):
    return pd.DataFrame([{
        "date": pd.Timestamp(start) + pd.Timedelta(days=i * 3),
        "code": code, "side": side, "size_pct": 0.05, "source": source,
        "thesis": "x" * 20, "invalidation": "y" * 10,
        "expected_holding_days": 20, "emotion": "calm",
    } for i in range(n)])


def test_outcomes_computed_from_next_day(monkeypatch):
    """收益从记录日的**下一个**交易日算起。

    写日志时当日行情已经走完，用当日收盘等于偷跑了一天。
    """
    from artemis.lite import journal_outcomes

    _fake_akshare(monkeypatch, {"600000": 0.002})
    oc = journal_outcomes(_journal_df(6), horizon=10)
    assert not oc.empty
    assert "fwd_ret" in oc.columns


def test_sell_side_return_is_inverted(monkeypatch):
    """卖出后跌了才算你对 —— 符号搞反会让复盘结论完全颠倒。"""
    from artemis.lite import journal_outcomes

    _fake_akshare(monkeypatch, {"600000": 0.004})   # 明显上涨
    buy = journal_outcomes(_journal_df(6, side="buy"), horizon=10)
    sell = journal_outcomes(_journal_df(6, side="sell"), horizon=10)
    assert buy["fwd_ret"].mean() > 0
    assert sell["fwd_ret"].mean() < 0, "上涨行情里卖出应记为负收益"


def test_immature_records_excluded(monkeypatch):
    """还没走满 horizon 的记录必须排除，不能用不完整的窗口凑数。"""
    from artemis.lite import journal_outcomes

    _fake_akshare(monkeypatch, {"600000": 0.001})
    recent = _journal_df(4, start="2026-08-18")     # 离数据末尾太近
    oc = journal_outcomes(recent, horizon=20)
    assert oc.empty


def test_review_warns_on_small_sample(monkeypatch, capsys, tmp_path):
    """小样本必须明确告警。

    这是整个功能最容易被误读的地方：两组各几笔时的差值全是噪音，
    但数字摆在那里，人就会当结论用。
    """
    import os

    from artemis.lite import cmd_review
    from artemis.review.journal import Journal

    os.chdir(tmp_path)
    _fake_akshare(monkeypatch, {"600001": 0.003, "600002": -0.003})
    j = pd.concat([
        _journal_df(6, source="system", code="600001"),
        _journal_df(5, source="discretionary", code="600002"),
    ])
    with open(tmp_path / "journal.jsonl", "w", encoding="utf-8") as f:
        for _, r in j.iterrows():
            d = r.to_dict()
            d["date"] = str(d["date"].date())
            f.write(pd.io.json.ujson_dumps(d) if False else __import__("json").dumps(d, ensure_ascii=False) + "\n")

    cmd_review([])
    out = capsys.readouterr().out
    assert "样本太小" in out
    assert "不要据此下结论" in out


def test_review_says_so_when_only_one_source(monkeypatch, capsys, tmp_path):
    """只有一类记录时说明无法对比 —— 这个功能的价值全在对比上。"""
    import json
    import os

    from artemis.lite import cmd_review

    os.chdir(tmp_path)
    _fake_akshare(monkeypatch, {"600001": 0.002})
    j = _journal_df(8, source="system", code="600001")
    with open(tmp_path / "journal.jsonl", "w", encoding="utf-8") as f:
        for _, r in j.iterrows():
            d = r.to_dict()
            d["date"] = str(d["date"].date())
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    cmd_review([])
    out = capsys.readouterr().out
    assert "无法对比" in out


# ---------------------------------------------------------------- 价格缓存
def _cached_akshare(monkeypatch, calls: list):
    """确定性价格源：后复权序列不随重新拉取而改变（这是 hfq 的性质）。"""
    import sys
    import types

    import numpy as np

    base = pd.Series(
        20 * np.cumprod(1 + np.random.default_rng(1).normal(0.001, 0.01, 4000)),
        index=pd.bdate_range("2025-01-01", periods=4000))

    fake = types.ModuleType("akshare")

    def hist(symbol=None, start_date=None, end_date=None, **kw):
        calls.append((symbol, start_date))
        beg = pd.Timestamp(start_date) if start_date else pd.Timestamp("2025-01-01")
        dates = pd.bdate_range(max(beg, pd.Timestamp("2025-01-01")),
                               pd.Timestamp.today().normalize())
        if len(dates) == 0:
            return pd.DataFrame()
        seg = base.reindex(dates).ffill()
        return pd.DataFrame({"日期": dates.strftime("%Y-%m-%d"), "收盘": seg.values})

    fake.stock_zh_a_hist = hist
    monkeypatch.setitem(sys.modules, "akshare", fake)


def test_price_cache_avoids_refetch_for_matured_records(monkeypatch, tmp_path):
    """已成熟的记录不该每次复盘都重新联网。

    日志会越攒越多。若每次都全量重拉，攒到 40 只时每周要等 40 秒
    下载没变过的数据 —— 然后用户就不跑复盘了，而复盘是这套东西
    最值钱的部分。
    """
    from artemis.lite import fetch_returns_for_journal

    calls: list = []
    _cached_akshare(monkeypatch, calls)
    cp = str(tmp_path / "px.parquet")
    codes = ["600000", "600001", "600002"]
    matured = pd.Timestamp.today().normalize() - pd.Timedelta(days=100)

    fetch_returns_for_journal(codes, "2025-06-01", cache_path=cp, sleep=0.0,
                              progress=False, need_through=matured)
    assert len(calls) == 3, "冷缓存应拉取全部"

    calls.clear()
    out = fetch_returns_for_journal(codes, "2025-06-01", cache_path=cp, sleep=0.0,
                                    progress=False, need_through=matured)
    assert calls == [], "记录已成熟时不该再联网"
    assert len(out) == 3, "仍要能从缓存返回全部序列"


def test_price_cache_fetches_only_tail_for_new_records(monkeypatch, tmp_path):
    """有新记录时只补尾部，不重拉整条历史。"""
    from artemis.lite import fetch_returns_for_journal

    calls: list = []
    _cached_akshare(monkeypatch, calls)
    cp = str(tmp_path / "px.parquet")
    old = pd.Timestamp.today().normalize() - pd.Timedelta(days=100)

    fetch_returns_for_journal(["600000"], "2025-06-01", cache_path=cp, sleep=0.0,
                              progress=False, need_through=old)
    calls.clear()
    fetch_returns_for_journal(["600000"], "2025-06-01", cache_path=cp, sleep=0.0,
                              progress=False,
                              need_through=pd.Timestamp.today().normalize())
    assert len(calls) == 1
    frm = pd.Timestamp(calls[0][1])
    assert frm > pd.Timestamp("2025-06-01"), "应从缓存末尾附近开始，而非整条重拉"


def test_corrupt_cache_rebuilds_instead_of_crashing(monkeypatch, tmp_path):
    """缓存文件损坏时重建，而不是让复盘整个失败。"""
    from artemis.lite import _load_price_cache, fetch_returns_for_journal

    cp = tmp_path / "px.parquet"
    cp.write_text("这不是 parquet", encoding="utf-8")
    assert _load_price_cache(str(cp)).empty

    calls: list = []
    _cached_akshare(monkeypatch, calls)
    out = fetch_returns_for_journal(["600000"], "2025-06-01", cache_path=str(cp),
                                    sleep=0.0, progress=False)
    assert len(out) == 1, "坏缓存应被丢弃并重建"
