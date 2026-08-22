"""Agent 调用层：把 Artemis 变成可被程序调用的服务。

人用 CLI 和 agent 用 CLI 的要求完全不同：

  人要的            agent 要的
  ─────────────────────────────────────────
  好看的表格         JSON
  交互式提问         参数一次传入
  出错时打印堆栈     结构化错误 + 退出码
  "大概是对的"       明确的数据新鲜度与置信度

最后一条最关键。agent 不会像人一样看一眼日期觉得"咦这数据是昨天的"，
它会把过期数据当成今天的直接用。所以每个返回都带 `freshness` 字段，
并且**过期时主动降级为错误**，而不是返回一个看起来正常的结果。

退出码约定：
  0  成功
  1  执行失败（网络、依赖、数据源）
  2  参数错误
  3  非交易日 / 不该运行（agent 据此静默跳过，不该当成故障告警）
  4  数据过期或体检未通过（结果不可信，agent 不该消费）
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from .calendar import CN_TZ, TradingCalendar

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_BADARGS = 2
EXIT_SKIP = 3
EXIT_STALE = 4


@dataclass
class Envelope:
    """所有返回的统一信封。agent 只需要认这一个结构。"""

    ok: bool
    command: str
    data: Any = None
    error: str | None = None
    error_type: str | None = None
    warnings: list[str] | None = None
    freshness: dict | None = None
    generated_at: str = ""
    exit_code: int = EXIT_OK

    def emit(self) -> int:
        self.generated_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
        d = {k: v for k, v in asdict(self).items() if v is not None}
        print(json.dumps(d, ensure_ascii=False, default=str))
        return self.exit_code


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --------------------------------------------------------------------------
# 命令
# --------------------------------------------------------------------------
def cmd_health(args: dict) -> Envelope:
    """健康检查。agent 应在每次调度前跑一次，失败就别跑后面的。"""
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    ok = True

    # 1. 依赖
    for mod, required in [("pandas", True), ("numpy", True), ("pyarrow", True),
                          ("scipy", True), ("akshare", False), ("anthropic", False)]:
        try:
            m = __import__(mod)
            checks[mod] = getattr(m, "__version__", "installed")
        except ImportError:
            checks[mod] = None
            if required:
                ok = False
            else:
                warnings.append(f"{mod} 未安装（可选，缺失会禁用部分功能）")

    # 2. 时区。服务器跑在 UTC 而代码假设北京时间，是最隐蔽的一类部署故障
    checks["tz_env"] = os.environ.get("TZ", "(unset)")
    checks["now_cn"] = datetime.now(CN_TZ).isoformat(timespec="seconds")
    checks["now_local"] = datetime.now().astimezone().isoformat(timespec="seconds")

    # 3. 交易日历
    cal = TradingCalendar()
    checks["calendar"] = cal.to_dict()
    if cal.status.warning:
        warnings.append(f"日历：{cal.status.warning}")
    if cal.status.source != "cache" and cal.status.source != "fetched":
        warnings.append("无交易日历缓存，节假日无法识别。请先跑 `artemis-svc calendar-refresh`")

    # 4. 可写目录
    data_dir = Path(os.environ.get("ARTEMIS_DATA_DIR", "./data_cache"))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks["data_dir"] = {"path": str(data_dir.resolve()), "writable": True}
    except OSError as e:
        checks["data_dir"] = {"path": str(data_dir), "writable": False, "error": str(e)}
        ok = False

    # 5. 凭证（只报是否存在，绝不回显值）
    checks["anthropic_key_present"] = bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    return Envelope(ok=ok, command="health", data=checks,
                    warnings=warnings or None,
                    exit_code=EXIT_OK if ok else EXIT_FAIL)


def cmd_session(args: dict) -> Envelope:
    """当前该做什么。agent 的调度入口 —— 先问这个，再决定跑什么。"""
    cal = TradingCalendar()
    info = cal.to_dict()
    sess = info["session"]

    action = {
        "closed_holiday": "skip",
        "premarket": "run_premarket",
        "call_auction": "run_premarket",
        "trading_am": "hold",
        "lunch_break": "hold",
        "trading_pm": "hold",
        "postmarket": "run_postmarket",
    }.get(sess, "hold")

    info["recommended_action"] = action
    code = EXIT_SKIP if action == "skip" else EXIT_OK
    warns = [info["warning"]] if info.get("warning") else None
    return Envelope(ok=True, command="session", data=info,
                    warnings=warns, exit_code=code)


def cmd_calendar_refresh(args: dict) -> Envelope:
    cal = TradingCalendar()
    st = cal.refresh()
    return Envelope(
        ok=st.ok, command="calendar-refresh",
        data={"source": st.source,
              "covered_to": st.covered_to.isoformat() if st.covered_to else None},
        warnings=[st.warning] if st.warning else None,
        error=None if st.ok else (st.warning or "刷新失败"),
        exit_code=EXIT_OK if st.ok else EXIT_FAIL,
    )


def cmd_screen(args: dict) -> Envelope:
    """排雷检查。agent 传 codes，拿回每只票的结论。"""
    from .lite import check

    codes = args.get("codes") or []
    if not codes:
        return Envelope(ok=False, command="screen", error="缺少 --codes",
                        error_type="bad_args", exit_code=EXIT_BADARGS)

    cal = TradingCalendar()
    trading, basis = cal.is_trading_day()

    df = check(codes, with_adv20=bool(args.get("adv20", False)))
    records = df.to_dict("records")
    blocked = [r["代码"] for r in records if r["结论"].startswith("❌")]

    return Envelope(
        ok=True, command="screen",
        data={
            "checked": len(records),
            "blocked": blocked,
            "passed": [r["代码"] for r in records if r["结论"].startswith("✓")],
            "warned": [r["代码"] for r in records if r["结论"].startswith("⚠")],
            "detail": records,
            "not_found": df.attrs.get("missing", []),
        },
        freshness={"snapshot_taken_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                   "is_trading_day": trading, "basis": basis,
                   "note": "非交易日的快照是上一交易日收盘值" if not trading else None},
    )


def cmd_journal_add(args: dict) -> Envelope:
    """非交互式记录交易意图。agent 用这个代替人用的 `lite log`。"""
    from .review.journal import Journal, TradeIntent

    required = ["code", "side", "size_pct", "source", "thesis", "invalidation"]
    # 只检查"字段根本没传"。传了但内容不合格（thesis 太短、没写失效条件）
    # 交给下面的 validate() 处理 —— 这两件事对 agent 的含义完全不同：
    #   absent     → 调用写错了，agent 该改自己的代码
    #   inadequate → 这笔交易不该做，agent 该把理由转达给人
    absent = [k for k in required if k not in args or args[k] is None]
    if absent:
        return Envelope(ok=False, command="journal-add",
                        error=f"缺少必填字段: {absent}",
                        error_type="bad_args", exit_code=EXIT_BADARGS)

    try:
        size = float(args["size_pct"])
    except (TypeError, ValueError):
        return Envelope(ok=False, command="journal-add",
                        error=f"size_pct 不是数字: {args['size_pct']!r}",
                        error_type="bad_args", exit_code=EXIT_BADARGS)

    intent = TradeIntent(
        date=args.get("date") or str(date.today()),
        code=str(args["code"]).zfill(6), side=args["side"],
        size_pct=size, source=args["source"],
        thesis=args["thesis"], invalidation=args["invalidation"],
        expected_holding_days=int(args.get("holding_days", 20)),
        conviction=int(args.get("conviction", 3)),
        emotion=args.get("emotion", "calm"),
        notes=args.get("notes", ""),
    )
    errs = Journal(args.get("journal_path", "./journal.jsonl")).record(intent, strict=True)
    if errs:
        # 校验失败不是"系统故障"，是"这笔交易不该做"。agent 应把它转达给人。
        return Envelope(ok=False, command="journal-add",
                        error="事前承诺未通过校验", error_type="validation",
                        data={"issues": errs}, exit_code=EXIT_BADARGS)
    return Envelope(ok=True, command="journal-add",
                    data={"recorded": intent.code, "fingerprint_date": intent.date})


def cmd_review(args: dict) -> Envelope:
    from .review.journal import Journal

    j = Journal(args.get("journal_path", "./journal.jsonl")).load()
    if j.empty:
        return Envelope(ok=True, command="review",
                        data={"n_records": 0, "note": "日志为空"})

    disc = float((j["source"] == "discretionary").mean())
    emo = float(j["emotion"].isin(["fomo", "revenge"]).mean()) if "emotion" in j else None
    flags = []
    if disc > 0.10:
        flags.append(f"临时起意占比 {disc:.1%} 超过 10%，执行纪律是主要漏洞")
    if emo is not None and emo > 0.05:
        flags.append(f"冲动交易占比 {emo:.1%} 超过 5%")

    return Envelope(ok=True, command="review", data={
        "n_records": int(len(j)),
        "date_range": [str(j["date"].min().date()), str(j["date"].max().date())],
        "discretionary_ratio": round(disc, 4),
        "impulsive_ratio": round(emo, 4) if emo is not None else None,
        "by_source": j.groupby("source").size().to_dict(),
        "flags": flags,
    })


def cmd_preflight(args: dict) -> Envelope:
    """数据体检。agent 在消费任何回测/审计结果前应先跑这个。"""
    from .data.preflight import check as pf_check
    from .data.store import BarStore

    root = args.get("data_dir") or os.environ.get("ARTEMIS_DATA_DIR", "./data_cache")
    try:
        bars = BarStore(root).read()
    except FileNotFoundError as e:
        return Envelope(ok=False, command="preflight", error=str(e),
                        error_type="no_data", exit_code=EXIT_FAIL)

    df = pf_check(bars)
    dead = df[df.status == "dead"]
    degraded = df[df.status == "degraded"]
    d = bars.index.get_level_values("date")

    return Envelope(
        ok=dead.empty, command="preflight",
        data={
            "rows": len(bars),
            "codes": int(bars.index.get_level_values("code").nunique()),
            "dead": dead[["capability", "detail"]].to_dict("records"),
            "degraded": degraded[["capability", "detail"]].to_dict("records"),
            "ok_count": int((df.status == "ok").sum()),
        },
        freshness={"data_covers_to": str(d.max().date()),
                   "stale_days": (date.today() - d.max().date()).days},
        warnings=[f"{r.capability}: {r.detail}" for r in degraded.itertuples()] or None,
        exit_code=EXIT_OK if dead.empty else EXIT_STALE,
    )


COMMANDS: dict[str, Callable[[dict], Envelope]] = {
    "health": cmd_health,
    "session": cmd_session,
    "calendar-refresh": cmd_calendar_refresh,
    "screen": cmd_screen,
    "journal-add": cmd_journal_add,
    "review": cmd_review,
    "preflight": cmd_preflight,
}


def _parse(argv: list[str]) -> tuple[str, dict]:
    """极简参数解析：`cmd --key value --flag`，或 `cmd --json '{...}'`。

    刻意不用 argparse：agent 传参最方便的是一坨 JSON，
    而 argparse 在这个场景下只会增加转义麻烦。
    """
    if not argv:
        return "help", {}
    cmd, rest = argv[0], argv[1:]
    if len(rest) == 2 and rest[0] == "--json":
        return cmd, json.loads(rest[1])

    args: dict = {}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if not tok.startswith("--"):
            i += 1
            continue
        key = tok[2:].replace("-", "_")
        if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            val = rest[i + 1]
            args[key] = val.split(",") if key == "codes" else val
            i += 2
        else:
            args[key] = True
            i += 1
    return cmd, args


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd, args = _parse(argv)

    if cmd in ("help", "-h", "--help"):
        return Envelope(ok=True, command="help", data={
            "commands": list(COMMANDS),
            "exit_codes": {"0": "ok", "1": "fail", "2": "bad_args",
                           "3": "skip(非交易日)", "4": "stale(数据不可信)"},
            "usage": "artemis-svc <command> [--key value | --json '{...}']",
        }).emit()

    fn = COMMANDS.get(cmd)
    if fn is None:
        return Envelope(ok=False, command=cmd, error=f"未知命令 {cmd}",
                        error_type="bad_args",
                        data={"available": list(COMMANDS)},
                        exit_code=EXIT_BADARGS).emit()
    try:
        return fn(args).emit()
    except Exception as e:  # noqa: BLE001 - 顶层兜底，必须返回结构化错误而不是堆栈
        return Envelope(ok=False, command=cmd, error=str(e)[:300],
                        error_type=type(e).__name__,
                        data={"traceback": traceback.format_exc()[-800:]}
                        if os.environ.get("ARTEMIS_DEBUG") else None,
                        exit_code=EXIT_FAIL).emit()


if __name__ == "__main__":
    sys.exit(main())
