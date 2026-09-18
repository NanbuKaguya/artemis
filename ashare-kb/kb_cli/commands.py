"""kb 的命令实现。

核心循环三条：lead / verify / stale。
其余是这个循环必须的配件：source（回溯来源，L4→L1 的那一步）、
falsify（制度变了，手动打脸）、digest（生成下次会话的 prime 材料）。
"""

from __future__ import annotations

import datetime as _dt
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

from . import digest as digest_mod
from . import doctor as doctor_mod
from . import ledger, tombstone
from .db import (
    STALE_DEFAULT,
    KBError,
    connect,
    count_claims,
    get_claim,
    init as db_init,
    kb_root,
    row_to_dict,
)
from .ids import claim_id as make_id

TIER_NAMES = {
    1: "L1 法规原文/监管与交易所公告/上市公司公告/指数官方统计",
    2: "L2 Wind·Choice·同花顺原始数据 / 自算",
    3: "L3 券商研报（署名+方法论）",
    4: "L4 财经媒体 —— 只能是线索",
    5: "L5 自媒体·论坛·转述 —— 只能是线索",
}

VERIFY_TIMEOUT = 300

# 验证脚本的退出码契约。
# 退出码不够 —— Python 脚本抛未捕获异常时退出码就是 1，
# 光看退出码会把"脚本崩了"读成"断言被打脸"，库就会自己给自己捏造教训。
# 所以状态变更同时要求脚本在 stdout 上显式声明结论。
RC_HOLDS = 0        # 0 + "HOLDS:"      -> verified
RC_FALSIFIED = 1    # 1 + "FALSIFIED:"  -> falsified
# 其余一切（含 0/1 但缺哨兵）= 不确定 -> 不改状态
MARK_HOLDS = "HOLDS:"
MARK_FALSIFIED = "FALSIFIED:"


def today() -> str:
    return _dt.date.today().isoformat()


# --------------------------------------------------------------------------
# init / rebuild
# --------------------------------------------------------------------------

def cmd_init(args) -> int:
    root = kb_root(args.root)
    conn = db_init(root)
    print(f"库已就绪: {root}")
    if count_claims(conn) == 0 and ledger.events_path(root).exists():
        n = _replay(root, conn)
        if n:
            print(f"从 ledger/events.jsonl 重放了 {n} 个事件")
    _print_scoreboard(conn)
    return 0


def cmd_rebuild(args) -> int:
    """从 append-only 账本重建 kb.sqlite。数据库坏了/没进 git 时的恢复路径。"""
    root = kb_root(args.root)
    path = root / "kb.sqlite"
    if path.exists():
        if not args.force:
            raise KBError(f"{path} 已存在。确认要用账本覆盖它就加 --force")
        path.unlink()
    conn = db_init(root)
    n = _replay(root, conn)
    print(f"重建完成: 重放 {n} 个事件 -> {path}")
    _print_scoreboard(conn)
    return 0


def _replay(root: Path, conn: sqlite3.Connection) -> int:
    """按时间顺序重放事件。每个事件带完整行快照，所以直接覆盖即可。"""
    n = 0
    for event in ledger.read_all(root):
        row = event.get("row")
        if not row:
            continue
        cols = [c for c in row if c != "_"]
        conn.execute(
            f"INSERT OR REPLACE INTO claim ({','.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)})",
            [row[c] for c in cols],
        )
        n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------
# lead
# --------------------------------------------------------------------------

def cmd_lead(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    statement = args.statement.strip()
    cid = make_id(args.layer, statement)

    if conn.execute("SELECT 1 FROM claim WHERE id = ?", (cid,)).fetchone():
        raise KBError(f"这条断言已在库中: {cid}\n看它: kb show {cid}")

    if args.stale_after in (None, ""):
        stale_after = STALE_DEFAULT[args.layer]
    elif str(args.stale_after).lower() in ("never", "none", "0"):
        stale_after = None
    else:
        stale_after = int(args.stale_after)
        if stale_after <= 0:
            raise KBError("--stale-after 必须为正整数或 never")

    row = {
        "id": cid,
        "statement": statement,
        "layer": args.layer,
        "if_wrong": args.if_wrong.strip(),
        "source_tier": args.tier,
        "source_ref": args.src.strip(),
        "status": "lead",          # lead 永远是入库状态。verified 只能由脚本挣到。
        "verify_script": args.verify_script,
        "last_verified": None,
        "created_at": today(),
        "stale_after_days": stale_after,
    }
    _insert(conn, row)
    ledger.append(root, "lead", cid, row, note=args.note)

    print(f"{cid}  [lead]  L{args.tier}")
    print(f"  {statement}")
    print(f"  推翻条件: {row['if_wrong']}")
    if args.tier >= 4:
        print("  ⚠ L4/L5：在回溯到 L1-L3 之前，它永远只能是线索。")
        print(f"     回溯: kb source {cid} --tier <1-3> --src <原文或 sources/ 下的文件>")
    else:
        print(f"     验证: 写 verify/{cid}.py，然后 kb verify {cid} --script verify/{cid}.py")
    return 0


def _insert(conn: sqlite3.Connection, row: dict) -> None:
    cols = list(row)
    try:
        conn.execute(
            f"INSERT INTO claim ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            [row[c] for c in cols],
        )
    except sqlite3.IntegrityError as exc:
        raise KBError(_explain_integrity(exc)) from exc
    conn.commit()


def _explain_integrity(exc: Exception) -> str:
    msg = str(exc)
    if "L4/L5" in msg:
        return f"质量门拦截: {msg}"
    if "status <> 'verified'" in msg or "CHECK constraint" in msg:
        return (f"约束拦截: {msg}\n"
                "  verified 必须同时有 last_verified 和 verify_script；"
                "statement/if_wrong/source_ref 不能是空串。")
    return msg


# --------------------------------------------------------------------------
# source —— 回溯。整套系统里最重要的一个动作。
# --------------------------------------------------------------------------

def cmd_source(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    row = row_to_dict(get_claim(conn, args.claim_id))
    before = (row["source_tier"], row["source_ref"])

    if args.tier is not None:
        row["source_tier"] = args.tier
    if args.src:
        row["source_ref"] = args.src.strip()
    if before == (row["source_tier"], row["source_ref"]):
        raise KBError("没有变化。至少给 --tier 或 --src 其中之一。")

    # 来源换了，之前的验证就不再算数：退回 lead，重新挣。
    if row["status"] == "verified":
        row["status"] = "lead"
        row["last_verified"] = None
        print("注意: 来源已变更，该断言退回 lead —— 需要重新 verify。")

    _update(conn, row)
    ledger.append(root, "source", row["id"], row, note=args.note,
                  before={"source_tier": before[0], "source_ref": before[1]})
    print(f"{row['id']}  L{before[0]} -> L{row['source_tier']}")
    print(f"  {row['source_ref']}")
    if row["source_tier"] <= 3:
        print(f"  现在可以验证了: kb verify {row['id']} --script verify/{row['id']}.py")
    return 0


def _update(conn: sqlite3.Connection, row: dict) -> None:
    cols = [c for c in row if c != "id"]
    try:
        conn.execute(
            f"UPDATE claim SET {','.join(c + ' = ?' for c in cols)} WHERE id = ?",
            [row[c] for c in cols] + [row["id"]],
        )
    except sqlite3.IntegrityError as exc:
        raise KBError(_explain_integrity(exc)) from exc
    conn.commit()


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def cmd_verify(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    row = row_to_dict(get_claim(conn, args.claim_id))

    if args.script:
        bound = _check_script(root, args.script)
        if bound != row["verify_script"]:
            # 立刻落库。脚本绑定是元数据，不是验证结果 ——
            # 让它依赖本次运行的结果，退 2 时绑定就丢了。
            row["verify_script"] = bound
            _update(conn, row)
            ledger.append(root, "bind", row["id"], row, script=bound)

    script = row["verify_script"]
    if not script:
        raise KBError(
            f"{row['id']} 没有验证脚本。\n"
            "  verified 只能由脚本挣到 —— 人工「我读过了」是这套系统唯一的后门，已焊死。\n"
            f"  写一个 verify/{row['id']}.py（看 verify/README.md 里的契约），然后:\n"
            f"    kb verify {row['id']} --script verify/{row['id']}.py"
        )
    path = root / script
    if not path.exists():
        raise KBError(f"验证脚本不存在: {path}")

    if row["source_tier"] >= 4:
        raise KBError(
            f"{row['id']} 是 L{row['source_tier']}，跑脚本也不会让它变成 verified。\n"
            f"  先回溯来源: kb source {row['id']} --tier <1-3> --src <...>"
        )

    cmd = [sys.executable, str(path)] if path.suffix == ".py" else [str(path)]
    print(f"$ {' '.join(shlex.quote(c) for c in cmd)}")
    try:
        proc = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=VERIFY_TIMEOUT,
            env=_verify_env(root, row["id"]),
        )
    except subprocess.TimeoutExpired:
        raise KBError(f"验证脚本超时（{VERIFY_TIMEOUT}s），状态不变。") from None
    except PermissionError:
        raise KBError(f"验证脚本不可执行: {path}（chmod +x，或写成 .py）") from None

    evidence = (proc.stdout + proc.stderr).strip()
    if evidence:
        print(evidence)

    marked = _marker(proc.stdout)

    if proc.returncode == RC_HOLDS and marked == MARK_HOLDS:
        row["status"] = "verified"
        row["last_verified"] = today()
        _update(conn, row)
        ledger.append(root, "verify", row["id"], row, evidence=evidence, rc=proc.returncode)
        print(f"\n✓ {row['id']} -> verified ({row['last_verified']})")
        return 0

    if proc.returncode == RC_FALSIFIED and marked == MARK_FALSIFIED:
        why = args.note or "验证脚本以退出码 1 判定该断言被数据推翻。"
        _do_falsify(root, conn, row, why, evidence)
        print(f"\n✗ {row['id']} -> falsified。断言被自己的脚本打脸，这是系统在正确工作。")
        return 1

    if proc.returncode in (RC_HOLDS, RC_FALSIFIED) and marked is None:
        print(f"\n? 退出码 {proc.returncode}，但 stdout 里没有 "
              f"{MARK_HOLDS} / {MARK_FALSIFIED} 结论行 —— 按不确定处理。")
        print("  脚本崩溃时 Python 的退出码也是 1，只看退出码会把它读成"
              "「断言被打脸」。用 kbverify.holds()/falsified() 明确声明结论。")
    else:
        print(f"\n? 退出码 {proc.returncode} = 不确定（脚本坏了或数据缺失）。"
              f"状态不变: {row['status']}")
    return 2


def _marker(stdout: str) -> str | None:
    """脚本有没有显式声明结论。只认行首，避免被正文里的字样蹭到。"""
    found = None
    for line in stdout.splitlines():
        line = line.strip()
        for mark in (MARK_HOLDS, MARK_FALSIFIED):
            if line.startswith(mark):
                if found and found != mark:
                    return None  # 自相矛盾的脚本 = 不确定
                found = mark
    return found


def _verify_env(root: Path, cid: str) -> dict:
    import os
    env = dict(os.environ)
    env["KB_ROOT"] = str(root)
    env["KB_CLAIM_ID"] = cid
    env["PYTHONPATH"] = str(root / "verify") + (
        ":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _check_script(root: Path, script: str) -> str:
    path = (root / script).resolve() if not Path(script).is_absolute() else Path(script)
    try:
        rel = path.relative_to(root.resolve())
    except ValueError:
        raise KBError(f"验证脚本必须放在库内的 verify/ 下: {script}") from None
    if rel.parts[0] != "verify":
        raise KBError(f"验证脚本必须放在 verify/ 下，收到: {rel}")
    if not path.exists():
        raise KBError(f"验证脚本不存在: {path}")
    return str(rel)


# --------------------------------------------------------------------------
# falsify
# --------------------------------------------------------------------------

def cmd_falsify(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    row = row_to_dict(get_claim(conn, args.claim_id))
    path = _do_falsify(root, conn, row, args.why, args.evidence or "")
    print(f"{row['id']} -> falsified")
    print(f"  墓碑: {path.relative_to(root)}")
    print("  去把「教训」那一节填了。断言错了不是教训，我当初凭什么相信它才是。")
    return 0


def _do_falsify(root: Path, conn: sqlite3.Connection, row: dict, why: str, evidence: str) -> Path:
    row["status"] = "falsified"
    _update(conn, row)
    path = tombstone.write(root, row, why, evidence)
    ledger.append(root, "falsify", row["id"], row, why=why, evidence=evidence or None)
    return path


# --------------------------------------------------------------------------
# stale
# --------------------------------------------------------------------------

def cmd_stale(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    rows = conn.execute(
        "SELECT * FROM claim WHERE status = 'verified' "
        "AND stale_after_days IS NOT NULL AND last_verified IS NOT NULL "
        # 'start of day' 去掉时分秒；否则 last_verified 恰好是 90 天前的那天
        # 也会被判成超期（90.4 > 90），阈值实际变成 89 天。
        "AND julianday('now', 'start of day') - julianday(last_verified) "
        "> stale_after_days "
        "ORDER BY last_verified"
    ).fetchall()

    if not rows:
        n = conn.execute("SELECT count(*) FROM claim WHERE status='stale'").fetchone()[0]
        print("没有到期的 verified 断言。" + (f"（库里已有 {n} 条 stale 待重算）" if n else ""))
        return 0

    for r in rows:
        age = (_dt.date.today() - _dt.date.fromisoformat(r["last_verified"])).days
        print(f"{r['id']}  {age}天未验证（阈值 {r['stale_after_days']}）  L{r['source_tier']}")
        print(f"  {r['statement']}")
        if not args.dry_run:
            row = row_to_dict(r)
            row["status"] = "stale"
            _update(conn, row)
            ledger.append(root, "stale", row["id"], row, age_days=age)

    verb = "将被降级" if args.dry_run else "已降级为 stale"
    print(f"\n{len(rows)} 条{verb}。重算后 kb verify，或者 kb falsify 把它埋了。")
    if args.dry_run:
        print("（--dry-run：本次没有写库）")
    return 0


# --------------------------------------------------------------------------
# 只读
# --------------------------------------------------------------------------

def cmd_list(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    where, params = [], []
    for col, val in (("status", args.status), ("layer", args.layer)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    if args.tier:
        where.append("source_tier = ?")
        params.append(args.tier)
    sql = "SELECT * FROM claim"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY status, layer, source_tier, id"
    rows = conn.execute(sql, params).fetchall()
    for r in rows:
        print(f"{r['id']}  [{r['status']}]  L{r['source_tier']}  {r['layer'][:4]}")
        print(f"  {r['statement']}")
    print(f"\n{len(rows)} 条")
    _print_scoreboard(conn)
    return 0


def cmd_show(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    r = get_claim(conn, args.claim_id)
    print(f"# {r['id']}\n\n    {r['statement']}\n")
    for label, key in (("层", "layer"), ("状态", "status"), ("来源", "source_ref"),
                       ("推翻条件", "if_wrong"), ("验证脚本", "verify_script"),
                       ("最后验证", "last_verified"), ("建立", "created_at"),
                       ("衰减阈值(天)", "stale_after_days")):
        print(f"{label:<14}{r[key] if r[key] is not None else '—'}")
    print(f"{'来源分级':<12}L{r['source_tier']}  {TIER_NAMES[r['source_tier']]}")
    hist = ledger.history(root, r["id"])
    if hist:
        print("\n## 账本")
        for e in hist:
            extra = e.get("why") or e.get("note") or ""
            print(f"  {e['ts'][:10]}  {e['action']:<8} {extra}")
    return 0


def cmd_digest(args) -> int:
    root = kb_root(args.root)
    conn = connect(root)
    paths = digest_mod.write(root, conn)
    for p in paths:
        print(f"写入 {p.relative_to(root)}")
    _print_scoreboard(conn)
    return 0


def cmd_doctor(args) -> int:
    return doctor_mod.run(kb_root(args.root), args.offline)


def _print_scoreboard(conn: sqlite3.Connection) -> None:
    counts = dict(conn.execute("SELECT status, count(*) FROM claim GROUP BY status").fetchall())
    parts = [f"{s}: {counts.get(s, 0)}" for s in ("verified", "lead", "stale", "falsified")]
    print("\n" + "  |  ".join(parts))
    print("唯一有意义的指标是 verified。总条目数不是指标。")
