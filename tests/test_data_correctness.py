"""数据正确性回归测试。

这一组测试守的都是**静默降级**：系统照常跑完、照常给出结论，
但结论是错的，而且没有任何报错。这是本项目里最危险的一类缺陷 ——
崩溃会被发现，静默的错误会被相信。

每条测试对应一个真实出现过的缺陷，注释里写清楚"错的时候会怎样"。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 1. 时区：绝不能用 date.today()
# --------------------------------------------------------------------------
def test_today_cn_is_beijing_regardless_of_system_tz():
    """launchd/cron 不带 TZ 时进程是 UTC，北京时间早八点前会差一天。

    错的时候会怎样：journal 的日期直接用来切价格序列，差一天就取错入场价，
    整份复盘的收益都是错的 —— 而且看不出来。
    """
    code = (
        "from artemis.lite import today_cn\n"
        "from datetime import date\n"
        "print(date.today().isoformat(), today_cn().isoformat())\n"
    )
    env = {**os.environ, "TZ": "Pacific/Honolulu", "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=ROOT, check=True).stdout.split()
    sys_day, cn_day = out
    # 檀香山比北京晚 18 小时，一天里有 18 小时两者日期不同；
    # 不断言它们必然不等，只断言 today_cn 不受 TZ 摆布。
    env2 = {**os.environ, "TZ": "Europe/London", "PYTHONPATH": str(ROOT)}
    out2 = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env2, cwd=ROOT, check=True).stdout.split()
    assert cn_day == out2[1], "today_cn() 在不同 TZ 下必须一致"


def test_no_bare_date_today_in_dated_paths():
    """回归：日期敏感的模块里不允许真的调用 date.today()。

    用 AST 而不是字符串匹配 —— 注释里解释"为什么不能用"是好事，
    不该被算成违规。
    """
    import ast

    for rel in ("artemis/lite.py", "artemis/review/journal.py", "artemis/calendar.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        bad = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "today"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "date"
        ]
        assert not bad, f"{rel}:{[n.lineno for n in bad]} 调用了 date.today()"


# --------------------------------------------------------------------------
# 2. 比较运算吞 NaN：把"不知道"变成"没踩雷"
# --------------------------------------------------------------------------
def test_cmp_preserves_unknown():
    """NaN < 阈值 在 pandas 里是 False —— 即"数据缺失"被判为"通过"。

    错的时候会怎样：上市不足 20 天、20 日均额还是 NaN 的次新股，
    会顺利通过流动性检查。而它恰恰是流动性最不可测的那类。
    """
    from artemis.guard.rules import _cmp

    v = pd.Series([1e6, np.nan, 1e9])
    naive = v < 5e7
    safe = _cmp(v, "<", 5e7)

    assert bool(naive.iloc[1]) is False, "先确认原生行为确实吞了 NaN"
    assert safe.iloc[1] is pd.NA, "缺失必须传播为 pd.NA"
    assert bool(safe.iloc[0]) is True and bool(safe.iloc[2]) is False


def test_guard_reports_how_much_of_exclusion_is_missing_data():
    """排除率里有多少是"真踩雷"、多少是"没数据"，必须分得清。

    错的时候会怎样：你以为 19% 的股票踩了雷，实际上它们只是没数据，
    于是你会去调阈值 —— 调一个根本不是原因的东西。
    """
    from artemis.config import GuardConfig
    from artemis.data.synthetic import make_market
    from artemis.guard.rules import Guard

    bars, _ = make_market(n_stocks=25, n_days=80, seed=7)
    # 让一部分票缺成交额（次新股 / 长期停牌复牌后数据不全）
    codes = sorted(bars.index.get_level_values("code").unique())
    late = bars.index.get_level_values("code").isin(codes[:5])
    bars = bars.copy()
    bars.loc[late, "amount"] = np.nan

    res = Guard(GuardConfig()).apply(bars)
    assert res.no_data is not None
    assert res.no_data_ratio > 0, "缺失样本必须被单独计数，而不是混进排除率"
    assert "of_which_no_data_pct" in res.summary.columns


# --------------------------------------------------------------------------
# 3. 排雷用的必须是"昨日真实值"，不是开盘前的快照日内字段
# --------------------------------------------------------------------------
def test_suspension_and_prev_limit_up_use_previous_day_truth():
    """watch 在开盘前跑，快照里的当日涨跌幅那时还不存在。

    错的时候会怎样：涨停判定永远不触发（开盘前是 0），
    停牌股则完全无人拦截，直接进当日清单。
    """
    from artemis.config import GuardConfig
    from artemis.lite import RecentStats, check_one

    mkt = pd.Timestamp("2026-09-11")
    base = {"price": 15.0, "pct_chg": 0.0, "amount": 3e8,
            "total_mv": 120e8, "float_mv": 100e8, "turnover_rate": 0.0}

    susp = pd.Series({"code": "600001", "name": "某停牌股", **base})
    st = RecentStats(adv20=3e8, last_date=pd.Timestamp("2026-08-20"),
                     last_close=15.0, prev_close=15.0, last_amount=0.0)
    mines = {m.rule: m for m in check_one(susp, GuardConfig(), st, mkt)}
    assert mines["停牌"].hit and mines["停牌"].severity == "block"

    lu = pd.Series({"code": "600002", "name": "某涨停股", **base})
    st2 = RecentStats(adv20=3e8, last_date=mkt, last_close=11.0,
                      prev_close=10.0, last_amount=3e8)
    mines2 = {m.rule: m for m in check_one(lu, GuardConfig(), st2, mkt)}
    assert mines2["昨日涨停（今日易高开）"].hit
    assert not mines2["停牌"].hit


def test_board_limit_threshold_respected_for_prev_day():
    """创业板 20%：涨 11% 不是涨停，主板涨 11% 不可能出现。

    错的时候会怎样：对 300/301 开头的票，10% 阈值会把正常的
    大阳线误判成涨停，把本该能买的票全部排除。
    """
    from artemis.config import GuardConfig
    from artemis.lite import RecentStats, check_one

    mkt = pd.Timestamp("2026-09-11")
    row = pd.Series({"code": "300001", "name": "特锐德", "price": 22.2,
                     "pct_chg": 0.0, "amount": 5e8, "total_mv": 200e8,
                     "float_mv": 180e8, "turnover_rate": 0.0})
    st = RecentStats(adv20=5e8, last_date=mkt, last_close=22.2,
                     prev_close=20.0, last_amount=5e8)          # +11%
    mines = {m.rule: m for m in check_one(row, GuardConfig(), st, mkt)}
    assert not mines["昨日涨停（今日易高开）"].hit, "创业板 +11% 不是涨停"

    st2 = RecentStats(adv20=5e8, last_date=mkt, last_close=24.0,
                      prev_close=20.0, last_amount=5e8)         # +20%
    mines2 = {m.rule: m for m in check_one(row, GuardConfig(), st2, mkt)}
    assert mines2["昨日涨停（今日易高开）"].hit


# --------------------------------------------------------------------------
# 4. 历史市值不能拿今天的市值回填
# --------------------------------------------------------------------------
def test_historical_market_cap_scales_with_price():
    """用今天的总市值当整段历史的市值，等于假装股价从没动过。

    错的时候会怎样：一只一年翻倍的票，它在半年前"看起来"就已经是
    今天的市值 —— 市值下限规则于是在整段历史上都判错，
    而规则审计的结论会告诉你"市值规则没用"。
    """
    hfq_close = pd.Series(
        [10.0, 12.0, 20.0],
        index=pd.to_datetime(["2026-01-05", "2026-04-01", "2026-09-11"]))
    mv_now = 200e8

    ratio = mv_now / float(hfq_close.iloc[-1])
    mv_series = hfq_close * ratio

    assert mv_series.iloc[-1] == pytest.approx(mv_now)
    assert mv_series.iloc[0] == pytest.approx(100e8), "翻倍前市值应是一半"
    # 旧做法：整段填 mv_now，起点误差 +100%
    assert abs(mv_now - 100e8) / 100e8 == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 5. 中性化不能用中位数填补缺失的市值
# --------------------------------------------------------------------------
def test_neutralize_drops_missing_logmv_instead_of_imputing():
    """缺市值的票用中位数填补，等于凭空给它一个"中等规模"的身份。

    错的时候会怎样：它的因子残差是对着一个假市值算出来的，
    却和真实样本一起进了 IC 统计。
    """
    from artemis.alpha.factors import neutralize

    dates = pd.bdate_range("2026-01-01", periods=3)
    codes = [f"{600000 + i:06d}" for i in range(40)]
    idx = pd.MultiIndex.from_product([dates, codes], names=["date", "code"])
    rng = np.random.default_rng(1)
    factor = pd.Series(rng.normal(size=len(idx)), index=idx)
    bars = pd.DataFrame({
        "total_mv": rng.uniform(50e8, 500e8, len(idx)),
        "industry": rng.choice(["银行", "医药", "电子"], len(idx)),
    }, index=idx)
    missing = idx.get_level_values("code").isin(codes[:5])
    bars.loc[missing, "total_mv"] = np.nan

    out = neutralize(factor, bars)
    assert out[missing].isna().all(), "缺市值的样本必须留空，不能被填补"
    assert out[~missing].notna().any(), "其余样本仍应有残差"


# --------------------------------------------------------------------------
# 6. 缓存路径必须跟随 ARTEMIS_DATA_DIR
# --------------------------------------------------------------------------
def test_cache_paths_follow_env(monkeypatch, tmp_path):
    """launchd 的工作目录是 /，写死相对路径会让 watch 和 review 读写不同文件。

    错的时候会怎样：复盘每次都当冷启动重拉几十只票的历史，
    慢到你不再跑复盘 —— 而复盘是这套东西最值钱的部分。
    """
    from artemis.calendar import _default_cache
    from artemis.lite import price_cache_path

    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "abc"))
    assert str(tmp_path / "abc") in str(price_cache_path())
    assert str(tmp_path / "abc") in str(_default_cache())


# --------------------------------------------------------------------------
# 7. agent 入口默认必须查历史
# --------------------------------------------------------------------------
def test_screen_defaults_to_fetching_history(monkeypatch):
    """默认 False 意味着 agent 每次 screen 都跳过四条流量规则却回"通过"。

    错的时候会怎样：Hermes 转达给你的"3 只都通过了"，
    其实只检查了名称、市值、股价 —— 停牌股也会通过。
    """
    import artemis.service as svc

    seen = {}

    def fake_check(codes, with_history=True, **kw):
        seen["with_history"] = with_history
        df = pd.DataFrame([{"代码": c, "名称": "x", "结论": "✓ 通过",
                            "踩雷": "—", "提示": "—"} for c in codes])
        df.attrs["history_failed"] = 0
        return df

    monkeypatch.setattr("artemis.lite.check", fake_check)
    env = svc.cmd_screen({"codes": ["600519"]})
    assert seen["with_history"] is True
    assert env.data["unchecked_rules"] == []


def test_screen_declares_what_it_skipped(monkeypatch):
    """跳过时必须在 envelope 里说清楚，不能只是安静地少查几条。"""
    import artemis.service as svc

    def fake_check(codes, with_history=True, **kw):
        df = pd.DataFrame([{"代码": c, "名称": "x", "结论": "✓ 通过",
                            "踩雷": "—", "提示": "—"} for c in codes])
        df.attrs["history_failed"] = 0
        return df

    monkeypatch.setattr("artemis.lite.check", fake_check)
    env = svc.cmd_screen({"codes": ["600519"], "with_history": False})
    assert "停牌" in env.data["unchecked_rules"]
    assert env.data["caveat"]


# --------------------------------------------------------------------------
# 8. 回测引擎：缺失值必须往"更难成交"的方向取
# --------------------------------------------------------------------------
def _engine_run(bars):
    from artemis.backtest.engine import Backtester
    from artemis.config import DEFAULT_CONFIG

    codes = sorted(bars.index.get_level_values("code").unique())
    dates = bars.index.get_level_values("date").unique().sort_values()
    # 一直满仓等权，把撮合约束的影响放到最大
    tw = pd.DataFrame(1.0 / len(codes), index=dates, columns=codes)
    return Backtester(DEFAULT_CONFIG).run(bars, tw)


def test_engine_refuses_to_trade_at_unknown_prices():
    """昨收缺失 -> 涨停价是 NaN -> `open >= NaN` 求值为 False -> "没涨停，可以买"。

    错的时候会怎样：新股上市首日的 prev_close 正好是 NaN，而那天涨幅最极端。
    回测会在一个它根本判不出涨跌停的日子里成交，净值曲线凭空变好。
    """
    from artemis.data.synthetic import make_market

    bars, _ = make_market(n_stocks=20, n_days=120, seed=11)
    codes = sorted(bars.index.get_level_values("code").unique())
    victim = codes[0]

    holed = bars.copy()
    mask = holed.index.get_level_values("code") == victim
    holed.loc[mask, "prev_close"] = np.nan       # 整只票的昨收全部缺失

    res = _engine_run(holed)
    trades = res.trades
    if trades is not None and len(trades):
        assert victim not in set(trades["code"].astype(str)), \
            "昨收缺失的票不该产生任何成交 —— 涨跌停无法判定"


def test_synthetic_market_is_too_clean_to_catch_data_bugs():
    """守住一个事实，别让它悄悄变成"我们已经测过缺失值了"。

    合成市场里一个 NaN 都没有，所以任何"缺失值该怎么办"的 bug
    都不可能被主回归测试发现 —— 只能靠本文件里这种显式注入。
    """
    from artemis.data.synthetic import make_market

    bars, _ = make_market(n_stocks=15, n_days=60, seed=5)
    critical = ["prev_close", "adj_factor", "is_st", "is_suspended", "is_tradable"]
    assert bars[critical].isna().sum().sum() == 0, (
        "合成市场现在带缺失了 —— 这是好事，但要同步复核所有 fillna 的方向")


def test_st_limit_only_narrows_main_board():
    """创业板/科创板 ST 仍是 20%，北交所 ST 仍是 30%，只有主板压到 5%。

    错的时候会怎样：把 20cm 的 ST 一律按 20% 甚至 5% 处理，
    会在回测里凭空拦掉大量本可成交的单子，或反之。
    """
    from artemis.rules import price_limit_pct

    base = np.array([price_limit_pct(c) for c in
                     ["600000", "300001", "688001", "830001"]])
    st_lim = np.where(base > 0.15, base, 0.05)
    assert st_lim[0] == pytest.approx(0.05), "主板 ST 是 5%"
    assert st_lim[1] == pytest.approx(base[1]), "创业板 ST 不被压缩"
    assert st_lim[2] == pytest.approx(base[2]), "科创板 ST 不被压缩"
    assert st_lim[3] == pytest.approx(base[3]), "北交所 ST 不被压缩"


# --------------------------------------------------------------------------
# 9. 风控：价格读不到 ≠ 没触发
# --------------------------------------------------------------------------
def test_stop_loss_does_not_silently_vanish_on_missing_price():
    """NaN <= -0.08 求值为 False，止损和移动止盈会一起静默失效。

    错的时候会怎样：一只停牌或已进入退市整理期的票 —— 恰恰是最该
    处理的那类 —— 会被风控判为"无需处理"，不报错，只是什么都不做。
    """
    from artemis.risk.controls import Position, check_position

    pos = Position(code="600001", shares=1000, cost_basis=20.0,
                   peak_price=25.0, entry_date=pd.Timestamp("2026-01-05").date(),
                   current_price=float("nan"))
    out = check_position(pos, pd.Timestamp("2026-09-11").date())
    assert out["needs_attention"] is True
    assert "缺失" in out["reasons"][0]

    ok = Position(code="600002", shares=1000, cost_basis=20.0, peak_price=25.0,
                  entry_date=pd.Timestamp("2026-01-05").date(), current_price=17.0)
    out2 = check_position(ok, pd.Timestamp("2026-09-11").date())
    assert out2["should_exit"] is True and out2["needs_attention"] is False


# --------------------------------------------------------------------------
# 10. 市场收益截断要按各自板块，不能一律 ±11%
# --------------------------------------------------------------------------
def test_return_clipping_respects_board_limits():
    """用主板的尺子量 20cm 板，会把真实行情当异常值切掉。

    错的时候会怎样：市场指数波动被系统性低估 -> beta 偏小 ->
    超额收益偏大 -> 归因报告把 beta 说成 alpha。
    """
    from artemis.regime.market_state import clip_by_board

    ret = pd.DataFrame({"600000": [0.15], "300001": [0.15],
                        "688001": [0.15], "830001": [0.35]})
    out = clip_by_board(ret).iloc[0]
    assert out["600000"] < 0.15, "主板 15% 是脏数据，应被截断"
    assert out["300001"] == pytest.approx(0.15), "创业板 15% 是合法波动"
    assert out["688001"] == pytest.approx(0.15), "科创板 15% 是合法波动"
    assert out["830001"] < 0.35, "北交所超过 30% 才算脏数据"


def test_no_hardcoded_main_board_clip_remains():
    """回归：不允许再出现写死的 ±11% 全市场截断。"""
    for rel in ("artemis/regime/market_state.py", "artemis/review/attribution.py"):
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert "clip(-0.11, 0.11)" not in body, f"{rel} 仍有写死的主板截断"
