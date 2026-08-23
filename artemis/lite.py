"""Artemis Lite —— 不上全系统，只用最值钱的两块。

这个模块存在的理由：完整系统从零到实盘不少于一年，而大部分人走不完。
但系统里有两块**不需要 alpha、不需要 Level-2、不需要财务数据**就能用，
而且恰恰是"少亏钱"贡献最大的：

  1. 排雷      —— 买之前先看这票踩没踩雷
  2. 纪律      —— 记下事前承诺，定期对账，看清你的临时起意值多少钱

数据依赖被压到最低：AkShare 一个免费接口。
`stock_zh_a_spot_em()` 一次请求返回全市场快照，含名称（ST 标记就在里面）、
成交额、总市值、换手率 —— 排雷需要的东西基本一次拿全。

用法：
    python -m artemis.lite doctor                  # 第一件事：体检，告诉你卡在哪
    python -m artemis.lite check 600519 000001 300750
    python -m artemis.lite watch                  # 检查 watchlist.txt 里的自选股
    python -m artemis.lite log                    # 记一笔交易的事前承诺
    python -m artemis.lite review                 # 纪律复盘 + 实际收益对账
    python -m artemis.lite review --no-prices     # 只看占比，不拉行情
    python -m artemis.lite audit 200 3            # 抽样审计排雷规则（唯一需要真实历史的一步）

一个重要区分：
**实时排雷用当前快照是对的**（你就是想知道它今天是不是 ST）；
**历史审计才需要历史 ST 记录**（用今天的名单过滤三年前的回测是未来函数）。
这个区分砍掉了一大半数据工程。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .config import GuardConfig
from .rules import classify_board, price_limit_pct

# 快照契约：check() 只认这几列，任何数据源产出这个结构都能用
SNAPSHOT_COLS = ["code", "name", "price", "pct_chg", "amount", "total_mv",
                 "float_mv", "turnover_rate"]


# --------------------------------------------------------------------------
# 数据获取
# --------------------------------------------------------------------------
def fetch_snapshot() -> pd.DataFrame:
    """全市场快照。一次请求，约 5400 只股票。

    [需本机验证] AkShare 的中文列名跨版本会变；对不上时在 _SPOT_RENAME 补一行。
    """
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("请先 pip install akshare") from e

    import sys
    print("  拉取全市场快照（约 5400 只，5-15 秒）...", file=sys.stderr, flush=True)
    df = ak.stock_zh_a_spot_em()
    print(f"\r    已取 {len(df)} 只" + " " * 20, file=sys.stderr, flush=True)
    return normalize_snapshot(df)


_SPOT_RENAME = {
    "代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "pct_chg",
    "成交额": "amount", "总市值": "total_mv", "流通市值": "float_mv",
    "换手率": "turnover_rate",
}


def normalize_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """把数据源的原始返回转成快照契约。"""
    out = df.rename(columns=_SPOT_RENAME).copy()
    missing = [c for c in ["code", "name", "price"] if c not in out.columns]
    if missing:
        raise ValueError(
            f"快照缺少必需列 {missing}。实际列名：{list(df.columns)[:12]}\n"
            f"AkShare 的列名跨版本会变，请在 lite._SPOT_RENAME 里补映射。"
        )
    out["code"] = out["code"].astype(str).str.zfill(6)
    for c in ["price", "pct_chg", "amount", "total_mv", "float_mv", "turnover_rate"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        else:
            out[c] = np.nan
    return out[SNAPSHOT_COLS]


def fetch_adv20(codes: list[str], sleep: float = 0.2,
                progress: bool = True) -> tuple[dict[str, float], int]:
    """取 20 日均成交额。快照里没有，只能逐只拉历史。

    返回 (结果字典, 失败数)。

    两个必须处理的事：
    1. **进度输出**。逐只拉取 + 限速，20 只要 30-60 秒。没有输出的话
       用户会以为程序卡死然后 Ctrl-C —— 然后再也不用这个工具了。
    2. **失败要计数**。原来是 except: pass，全部失败时用户只看到
       "流动性: 未检"，分不清是"没查"还是"查了但失败"。
       这正是本项目一直在防的静默失效，而它就出在我自己的代码里。
    """
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("请先 pip install akshare") from e
    import sys
    import time

    end = date.today().strftime("%Y%m%d")
    start = (pd.Timestamp.today() - pd.Timedelta(days=60)).strftime("%Y%m%d")
    out: dict[str, float] = {}
    failed = 0
    total = len(codes)

    if progress and total:
        print(f"  取 20 日均成交额（{total} 只，约 {total * (sleep + 0.5):.0f} 秒）...",
              file=sys.stderr, flush=True)

    for i, c in enumerate(codes, 1):
        try:
            d = ak.stock_zh_a_hist(symbol=c, period="daily",
                                   start_date=start, end_date=end, adjust="")
            col = next((x for x in d.columns if "成交额" in str(x)), None)
            if col is not None and len(d):
                out[c] = float(pd.to_numeric(d[col], errors="coerce").tail(20).mean())
            else:
                failed += 1
        except Exception:  # noqa: BLE001 - 单只失败不该中断整批，但要计数
            failed += 1
        if progress and total:
            print(f"\r    {i}/{total}", end="", file=sys.stderr, flush=True)
        time.sleep(sleep)

    if progress and total:
        # 直接换行而不是 \r 清行：清行技巧在管道/日志里会渲染成乱码，
        # 而这个输出很可能被重定向到文件（定时任务）
        print("", file=sys.stderr, flush=True)
        if failed:
            print(f"  ⚠ {failed}/{total} 只没取到成交额，这些票的流动性检查会跳过",
                  file=sys.stderr, flush=True)
            if failed == total:
                print("  ⚠ 全部失败 —— 多半是被限频了。等几分钟再试，"
                      "或先用 --no-adv20 跳过流动性检查", file=sys.stderr, flush=True)
    return out, failed


# --------------------------------------------------------------------------
# 排雷检查
# --------------------------------------------------------------------------
@dataclass
class Landmine:
    rule: str
    hit: bool
    detail: str
    severity: str      # 'block' 一票否决 / 'warn' 提示


def check_one(row: pd.Series, cfg: GuardConfig, adv20: float | None = None) -> list[Landmine]:
    """单只股票的排雷检查。"""
    code, name = row["code"], str(row.get("name", ""))
    out: list[Landmine] = []

    is_st = ("ST" in name.upper()) or ("退" in name)
    out.append(Landmine(
        "ST/退市风险", is_st,
        f"名称含 ST/退：{name}" if is_st else f"{name}",
        "block"))

    mv = row.get("total_mv", np.nan)
    small = bool(pd.notna(mv) and mv < cfg.min_market_cap)
    out.append(Landmine(
        "市值下限", small,
        f"总市值 {mv/1e8:.1f} 亿（红线 {cfg.min_market_cap/1e8:.0f} 亿）"
        if pd.notna(mv) else "总市值缺失，本条未检",
        "block"))

    px = row.get("price", np.nan)
    low_px = bool(pd.notna(px) and px < 2.0)
    out.append(Landmine(
        "低价股（面值退市）", low_px,
        f"股价 {px:.2f} 元" if pd.notna(px) else "股价缺失", "block"))

    pct = row.get("pct_chg", np.nan)
    lim = price_limit_pct(code, is_st) * 100
    at_limit = bool(pd.notna(pct) and pct >= lim - 0.5)
    out.append(Landmine(
        "当日涨停（买不进）", at_limit,
        f"涨幅 {pct:+.2f}%（涨停 {lim:.0f}%）" if pd.notna(pct) else "涨幅缺失",
        "block"))

    if adv20 is not None and np.isfinite(adv20):
        illiq = adv20 < cfg.min_adv20
        out.append(Landmine(
            "流动性", illiq,
            f"20日均额 {adv20/1e8:.3f} 亿（下限 {cfg.min_adv20/1e8:.2f} 亿）",
            "block"))
    else:
        out.append(Landmine("流动性", False, "未取 20 日均额，本条未检", "warn"))

    amt = row.get("amount", np.nan)
    thin_today = bool(pd.notna(amt) and amt < cfg.min_adv20 * 0.5)
    out.append(Landmine(
        "当日成交清淡", thin_today,
        f"今日成交额 {amt/1e8:.3f} 亿" if pd.notna(amt) else "成交额缺失", "warn"))

    tr = row.get("turnover_rate", np.nan)
    hot = bool(pd.notna(tr) and tr > 25.0)
    out.append(Landmine(
        "换手过热", hot,
        f"换手率 {tr:.1f}%" if pd.notna(tr) else "换手率缺失", "warn"))

    return out


def check(codes: list[str], snapshot: pd.DataFrame | None = None,
          with_adv20: bool = True, cfg: GuardConfig | None = None) -> pd.DataFrame:
    """批量排雷检查。返回一张给人看的表。"""
    cfg = cfg or GuardConfig()
    snap = snapshot if snapshot is not None else fetch_snapshot()
    codes = [str(c).zfill(6) for c in codes]

    sub = snap[snap["code"].isin(codes)]
    missing = sorted(set(codes) - set(sub["code"]))

    adv: dict[str, float] = {}
    adv_failed = 0
    if with_adv20 and snapshot is None:
        adv, adv_failed = fetch_adv20(list(sub["code"]))

    rows = []
    for _, r in sub.iterrows():
        mines = check_one(r, cfg, adv.get(r["code"]))
        blocked = [m for m in mines if m.hit and m.severity == "block"]
        warned = [m for m in mines if m.hit and m.severity == "warn"]
        rows.append({
            "代码": r["code"], "名称": r.get("name", ""),
            "结论": "❌ 排除" if blocked else ("⚠ 注意" if warned else "✓ 通过"),
            "踩雷": "；".join(f"{m.rule}({m.detail})" for m in blocked) or "—",
            "提示": "；".join(m.rule for m in warned) or "—",
        })

    df = pd.DataFrame(rows)
    if missing:
        df.attrs["missing"] = missing
    df.attrs["adv20_failed"] = adv_failed
    return df


# --------------------------------------------------------------------------
# 规则审计：做一次，学到永久
# --------------------------------------------------------------------------
def fetch_sample_history(
    codes: list[str], years: float = 3.0, sleep: float = 0.25, verbose: bool = True
) -> pd.DataFrame:
    """为审计拼装一份抽样历史行情（契约格式）。

    刻意只抽样而不拉全市场：审计要回答的是"这条规则在我的市场里值多少钱"，
    几百只股票的统计功效已经够了，而全市场要跑一整夜。

    诚实说明它拿不到什么：
      is_st          —— AkShare 只有当前 ST 快照，没有历史。用当前名单过滤
                        三年前的数据是未来函数，所以这里**留空**而不是硬填。
      is_tradable    —— 只能拿到还在交易的股票，已退市的抓不到 →
                        **这份数据带幸存者偏差**，preflight 会明确报出来。
      industry       —— 需要额外 90 次请求，默认不取。

    所以基于它的审计结论对 ST 规则和退市相关的部分不成立，
    对流动性/市值/低价/涨停/暴涨这几条成立。跑完 preflight 会告诉你哪些能信。
    """
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("请先 pip install akshare") from e
    import time

    end = pd.Timestamp.today()
    start = end - pd.Timedelta(days=int(years * 365))
    s_str, e_str = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    # 市值：用当前快照的总市值除以当前价，反推股本，再乘历史价。
    # 这是近似 —— 期间发生过增发/回购的股票会有偏差，但比完全没有市值好得多。
    snap = fetch_snapshot().set_index("code")

    frames = []
    for i, c in enumerate(codes, 1):
        try:
            d = ak.stock_zh_a_hist(symbol=c, period="daily",
                                   start_date=s_str, end_date=e_str, adjust="")
            h = ak.stock_zh_a_hist(symbol=c, period="daily",
                                   start_date=s_str, end_date=e_str, adjust="hfq")
            if d is None or len(d) == 0:
                continue
            d = _norm_hist(d)
            if h is not None and len(h):
                d["adj_factor"] = (_norm_hist(h)["close"] / d["close"]).ffill().fillna(1.0)
            else:
                d["adj_factor"] = 1.0

            d["code"] = c
            d["prev_close"] = d["close"].shift(1).fillna(d["open"])
            if c in snap.index and pd.notna(snap.loc[c, "price"]) and snap.loc[c, "price"] > 0:
                shares = snap.loc[c, "total_mv"] / snap.loc[c, "price"]
                d["total_mv"] = d["close"] * shares
                d["float_mv"] = d["total_mv"] * float(
                    snap.loc[c, "float_mv"] / max(snap.loc[c, "total_mv"], 1e-9))
            else:
                d["total_mv"] = np.nan
                d["float_mv"] = np.nan

            d["is_st"] = False          # 历史 ST 拿不到，留 False 并由 preflight 报出
            d["is_suspended"] = d["volume"].fillna(0) <= 0
            d["is_tradable"] = True
            d["days_since_ipo"] = np.arange(len(d)) + 9999   # 无上市日，按"非次新"处理
            d["industry"] = "未知"
            frames.append(d.reset_index().set_index(["date", "code"]))
        except Exception as ex:  # noqa: BLE001
            if verbose:
                print(f"  [跳过] {c}: {str(ex)[:60]}")
        if verbose and i % 25 == 0:
            print(f"  {i}/{len(codes)} ...")
        time.sleep(sleep)

    if not frames:
        raise RuntimeError("没有拉到任何数据")
    return pd.concat(frames).sort_index()


_HIST_RENAME_LITE = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                     "最低": "low", "成交量": "volume", "成交额": "amount"}


def _norm_hist(df: pd.DataFrame) -> pd.DataFrame:
    d = df.rename(columns=_HIST_RENAME_LITE).copy()
    d["date"] = pd.to_datetime(d["date"])
    keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount"]
            if c in d.columns]
    d = d[keep].set_index("date").sort_index()
    if "volume" in d.columns:
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce") * 100   # 手 -> 股
    return d.astype(float, errors="ignore")


def audit_rules(bars: pd.DataFrame, horizon: int = 20) -> tuple[pd.DataFrame, str]:
    """在你自己的数据上量化每条排雷规则的价值。

    这是整个 Lite 里唯一"做一次、学到永久"的东西：
    它告诉你每条规则在**你的市场、你的持有期**下，
    牺牲了多少平均收益、换回了多少尾部保护。
    """
    from .guard.rules import Guard
    from .data.preflight import report as preflight_report

    return Guard().audit(bars, horizon=horizon), preflight_report(bars)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _watchlist_path() -> Path:
    return Path("watchlist.txt")


def cmd_check(codes: list[str]) -> None:
    no_adv = "--no-adv20" in codes
    codes = [c for c in codes if not c.startswith("--")]
    if not codes:
        print("用法: python -m artemis.lite check 600519 000001 ... [--no-adv20]")
        return
    df = check(codes, with_adv20=not no_adv)
    print(df.to_string(index=False))
    if df.attrs.get("missing"):
        print(f"\n未在快照中找到（可能已退市或代码有误）：{df.attrs['missing']}")
    n_block = int((df["结论"] == "❌ 排除").sum())
    print(f"\n{len(df)} 只中 {n_block} 只应排除。清单之外的票一律不碰。")
    if df.attrs.get("adv20_failed"):
        print(f"注意：{df.attrs['adv20_failed']} 只的流动性未能检查，"
              f"它们的 ✓ 通过含金量要打折。")


def cmd_watch(extra: list[str] | None = None) -> None:
    p = _watchlist_path()
    if not p.exists():
        p.write_text("# 每行一个 6 位代码，# 开头为注释\n600519\n000001\n", encoding="utf-8")
        print(f"已创建 {p}，把你的自选股写进去再跑一次。")
        return
    codes = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    cmd_check(codes + (extra or []))


def cmd_log() -> None:
    """交互式记录一笔交易的事前承诺。"""
    from .review.journal import Journal, TradeIntent

    print("记录事前承诺。写不出理由和失效条件的交易，本身就是信号。\n")
    try:
        code = input("代码: ").strip().zfill(6)
        side = (input("方向 (buy/sell) [buy]: ").strip() or "buy").lower()
        size = float(input("仓位占比 %  (如 5): ").strip() or "5") / 100
        source = (input("来源 (system/discretionary) [system]: ").strip() or "system").lower()
        thesis = input("为什么买/卖（可证伪的理由）: ").strip()
        inval = input("什么情况证明我错了: ").strip()
        days = int(input("打算持有多少天 [20]: ").strip() or "20")
        emo = (input("当前情绪 (calm/fomo/fear/revenge/bored) [calm]: ").strip() or "calm").lower()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        return

    intent = TradeIntent(date=str(date.today()), code=code, side=side, size_pct=size,
                         source=source, thesis=thesis, invalidation=inval,
                         expected_holding_days=days, emotion=emo)
    errs = Journal().record(intent, strict=True)
    if errs:
        print("\n未记录，以下问题需要先解决：")
        for e in errs:
            print(f"  - {e}")
        print("\n这不是形式主义。说不清理由的交易，事后你会重构一个理由出来。")
    else:
        print(f"\n已记录到 journal.jsonl（{code} {side} {size:.1%}）")


def fetch_returns_for_journal(
    codes: list[str], start: str, horizon: int = 20, sleep: float = 0.25
) -> dict[str, "pd.Series"]:
    """为日志里的股票拉取价格序列，用于计算事后收益。

    只拉日志里出现过的代码，不是全市场 —— 通常几十只，可接受。
    """
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("需要 akshare 才能对上实际收益") from e
    import sys
    import time

    s_str = (pd.Timestamp(start) - pd.Timedelta(days=10)).strftime("%Y%m%d")
    e_str = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y%m%d")
    out: dict[str, pd.Series] = {}
    total = len(codes)
    print(f"  取 {total} 只的价格序列（约 {total * (sleep + 0.5):.0f} 秒）...",
          file=sys.stderr, flush=True)

    for i, c in enumerate(codes, 1):
        try:
            d = ak.stock_zh_a_hist(symbol=c, period="daily",
                                   start_date=s_str, end_date=e_str, adjust="hfq")
            dcol = next((x for x in d.columns if "日期" in str(x)), None)
            ccol = next((x for x in d.columns if "收盘" in str(x)), None)
            if dcol and ccol and len(d):
                ser = pd.Series(pd.to_numeric(d[ccol], errors="coerce").values,
                                index=pd.to_datetime(d[dcol]))
                out[c] = ser.sort_index()
        except Exception:  # noqa: BLE001 - 单只失败不中断整批
            pass
        print(f"\r    {i}/{total}", end="", file=sys.stderr, flush=True)
        time.sleep(sleep)
    print("", file=sys.stderr, flush=True)
    return out


def journal_outcomes(j: "pd.DataFrame", horizon: int = 20) -> "pd.DataFrame":
    """把每笔事前承诺对上它之后的实际收益。

    收益口径：记录日的下一个交易日收盘 → 再往后 horizon 个交易日收盘。
    用下一日而非当日，因为你写日志时当日行情已经走完了。
    卖出方向取负号：卖出后跌了才算你对。
    """
    codes = sorted(j["code"].astype(str).unique())
    prices = fetch_returns_for_journal(codes, str(j["date"].min().date()), horizon)

    rows = []
    for _, r in j.iterrows():
        ser = prices.get(str(r["code"]))
        if ser is None or ser.empty:
            continue
        after = ser[ser.index > pd.Timestamp(r["date"])]
        if len(after) < horizon + 1:
            continue          # 还没走满 horizon，不能算
        entry = float(after.iloc[0])
        exit_ = float(after.iloc[horizon])
        if entry <= 0:
            continue
        ret = exit_ / entry - 1
        if str(r.get("side", "buy")).lower() == "sell":
            ret = -ret        # 卖出后跌了才算对
        rows.append({**r.to_dict(), "fwd_ret": ret})
    return pd.DataFrame(rows)


def cmd_review(args: list[str] | None = None) -> None:
    """纪律复盘：系统信号 vs 临时起意，到底哪个在赚钱。"""
    from .review.journal import Journal

    args = args or []
    horizon = 20
    for i, a in enumerate(args):
        if a in ("--horizon", "-h") and i + 1 < len(args):
            try:
                horizon = int(args[i + 1])
            except ValueError:
                pass
    skip_prices = "--no-prices" in args

    j = Journal().load()
    if j.empty:
        print("journal.jsonl 还是空的。先用 `artemis log` 记几笔。")
        return

    print(f"共 {len(j)} 笔记录，{j['date'].min().date()} ~ {j['date'].max().date()}\n")
    print("按来源分布：")
    print(j.groupby("source").agg(笔数=("code", "size"),
                                  平均仓位=("size_pct", "mean")).round(3).to_string())

    disc = float((j["source"] == "discretionary").mean())
    print(f"\n临时起意占比 {disc:.1%}  "
          f"{'← 超过 10%，执行纪律是你的主要漏洞' if disc > 0.10 else '✓'}")
    if "emotion" in j:
        bad = float(j["emotion"].isin(["fomo", "revenge"]).mean())
        print(f"冲动交易占比 {bad:.1%}  {'← 超过 5%' if bad > 0.05 else '✓'}")

    if skip_prices:
        print("\n（--no-prices：跳过实际收益对账）")
        return

    # ---------- 对上实际收益 ----------
    print(f"\n对账实际收益（{horizon} 个交易日前瞻）")
    try:
        oc = journal_outcomes(j, horizon)
    except RuntimeError as e:
        print(f"  跳过：{e}")
        return

    if oc.empty:
        print(f"  还没有走满 {horizon} 个交易日的记录。"
              f"最早那笔是 {j['date'].min().date()}，再等等。")
        return

    g = oc.groupby("source")["fwd_ret"]
    tbl = pd.DataFrame({
        "笔数": g.size(),
        "平均收益": g.mean().mul(100).round(2),
        "中位数": g.median().mul(100).round(2),
        "胜率": g.apply(lambda x: (x > 0).mean()).mul(100).round(1),
        "最差": g.min().mul(100).round(2),
    })
    print(tbl.to_string())

    n_sys = int((oc["source"] == "system").sum())
    n_dis = int((oc["source"] == "discretionary").sum())

    print()
    if n_sys and n_dis:
        gap = float(oc[oc.source == "system"]["fwd_ret"].mean()
                    - oc[oc.source == "discretionary"]["fwd_ret"].mean())
        print(f"系统信号 − 临时起意 = {gap * 100:+.2f}pp / {horizon}日")
        # 样本量诚实提示：这是整个功能最容易被误读的地方
        if min(n_sys, n_dis) < 20:
            print(f"  ⚠ 样本太小（system {n_sys} 笔 / discretionary {n_dis} 笔），"
                  f"这个差值主要是噪音，不要据此下结论。")
            print(f"    每组至少 20 笔才开始有参考价值，30+ 笔才比较可靠。")
        elif gap < 0:
            print("  你的临时起意平均跑赢了系统信号。两种可能："
                  "系统信号确实不行，或者你恰好赶上一段顺风。再攒些样本。")
        else:
            print(f"  按这个差值，每笔临时起意平均让你少赚 {abs(gap)*100:.2f}pp。")
    else:
        have = "system" if n_sys else "discretionary"
        print(f"  只有 {have} 一类记录（{max(n_sys, n_dis)} 笔），无法对比。")
        print(f"  这个功能的价值全在对比上 —— 两类都要有记录才看得出差距。")


def cmd_audit(args: list[str]) -> None:
    """抽样审计排雷规则。默认 200 只 × 3 年，约 15 分钟。"""
    n = int(args[0]) if args else 200
    years = float(args[1]) if len(args) > 1 else 3.0

    print(f"抽样 {n} 只 × {years} 年做规则审计。这是唯一需要真实历史的一步。\n")
    snap = fetch_snapshot()
    # 排除当前 ST 和北交所，抽样要贴近你实际会买的池子
    pool = snap[~snap["name"].str.upper().str.contains("ST|退", na=False)]
    pool = pool[~pool["code"].str.startswith(("4", "8", "9"))]
    codes = pool["code"].sample(min(n, len(pool)), random_state=0).tolist()

    bars = fetch_sample_history(codes, years=years)
    print(f"\n拿到 {len(bars):,} 行，{bars.index.get_level_values('code').nunique()} 只\n")

    audit, pf = audit_rules(bars)
    print(pf)
    print("\n" + "=" * 76)
    print("  规则价值审计（20 日前瞻）")
    print("=" * 76)
    print(audit.to_string(index=False))
    print("""
读法：
  edge        保留样本 − 剔除样本的平均收益差。正数说明这条规则提高了平均收益
  tail_saved  被剔除样本中未来跌超 20% 的比例
  tail_base   保留样本中的同一比例

  edge 为正 = 规则免费午餐，无条件保留
  edge 为负但 tail_saved 明显高于 tail_base = 保险费，值不值看你的风险偏好
  edge 为负且 tail_saved 也不高 = 这条规则在帮倒忙，删掉

注意上面体检报告里标为失效的能力 —— 对应的规则审计结论不可信。""")


def main(argv: list[str] | None = None) -> int | None:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "help"
    if cmd == "doctor":
        from .doctor import main as doctor_main
        return doctor_main()
    if cmd == "check":
        cmd_check(argv[1:])
    elif cmd == "watch":
        cmd_watch(argv[1:])
    elif cmd == "log":
        cmd_log()
    elif cmd == "review":
        cmd_review(argv[1:])
    elif cmd == "audit":
        cmd_audit(argv[1:])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
