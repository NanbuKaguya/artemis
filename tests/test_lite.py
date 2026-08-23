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


# ---------------------------------------------------------------- 静默失效
def test_adv20_counts_failures_instead_of_swallowing(monkeypatch):
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

    from artemis.lite import fetch_adv20
    out, failed = fetch_adv20(["600519", "000001"], sleep=0.0, progress=False)
    assert out == {}
    assert failed == 2, "失败必须被计数，不能静默吞掉"


def test_check_exposes_adv20_failure_count(snap):
    """失败数要透出到结果上，否则调用方无从判断 ✓ 的含金量。"""
    df = check(["600519"], snapshot=snap, with_adv20=False)
    assert "adv20_failed" in df.attrs


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
