"""kb doctor —— 动手之前先花十秒钟。

两件事：

1. **质量门还拦不拦得住。** 不是检查触发器在不在 —— 那是在度量"组件在不在"，
   不是"它有没有产出有效输出"。这里真的往库里写几条本该被拒的记录，
   看它拒不拒，写完回滚。库被从旧备份恢复、被手工 UPDATE 过、
   schema 漏迁移过 —— 这些情况下触发器可能就是不在了，而症状为零。

2. **数据源今天还能不能用。** akshare 背后是公开接口，列名变过、
   会限流、会挂。全A逐只历史要跑一两个小时，列名对不上却要等到跑到一半
   才暴露。先拉一只股票验一遍形状，十秒钟的事。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from pathlib import Path

from .db import DIRS, KBError, connect, db_path

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"

PROBE_ID = "__doctor_probe__"

# 每条都必须被拒。描述写的是"拦住了什么"，不是"测了什么"。
FORBIDDEN_INSERTS = [
    ("L5 来源不得为 verified", dict(source_tier=5, status="verified",
                                    last_verified="2026-01-01", verify_script="verify/x.py")),
    ("L4 来源不得为 verified", dict(source_tier=4, status="verified",
                                    last_verified="2026-01-01", verify_script="verify/x.py")),
    ("verified 必须有验证脚本", dict(source_tier=1, status="verified",
                                     last_verified="2026-01-01", verify_script=None)),
    ("verified 必须有验证日期", dict(source_tier=1, status="verified",
                                     last_verified=None, verify_script="verify/x.py")),
    ("if_wrong 不得为空白", dict(if_wrong="  \t\n")),
    ("statement 不得为空白", dict(statement="   ")),
    ("state 层不得入库", dict(layer="state")),
]


def _probe_row(**over) -> dict:
    row = dict(
        id=PROBE_ID, statement="doctor 探针", layer="institutional",
        if_wrong="doctor 探针", source_tier=1, source_ref="doctor",
        status="lead", verify_script=None, last_verified=None,
        created_at="2026-01-01", stale_after_days=None,
    )
    row.update(over)
    return row


def _insert(conn: sqlite3.Connection, row: dict) -> None:
    cols = list(row)
    conn.execute(
        f"INSERT INTO claim ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [row[c] for c in cols])


def check_gates(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """真写真拦，全程在 savepoint 里，结束回滚。"""
    out = []
    conn.execute("SAVEPOINT doctor")
    try:
        for label, over in FORBIDDEN_INSERTS:
            try:
                _insert(conn, _probe_row(**over))
            except sqlite3.IntegrityError:
                out.append((OK, label))
            else:
                out.append((FAIL, f"{label} —— 门没拦住，写进去了"))
            conn.execute("DELETE FROM claim WHERE id = ?", (PROBE_ID,))

        # UPDATE 路：先合法写入，再试图改成禁止状态
        _insert(conn, _probe_row(source_tier=5))
        for label, sql, params in [
            ("L5 不得被 UPDATE 成 verified",
             "UPDATE claim SET status='verified', last_verified='2026-01-01', "
             "verify_script='verify/x.py' WHERE id=?", (PROBE_ID,)),
            ("if_wrong 不得被 UPDATE 成空白",
             "UPDATE claim SET if_wrong='   ' WHERE id=?", (PROBE_ID,)),
        ]:
            try:
                conn.execute(sql, params)
            except sqlite3.IntegrityError:
                out.append((OK, label))
            else:
                out.append((FAIL, f"{label} —— 门没拦住"))
    finally:
        conn.execute("ROLLBACK TO doctor")
        conn.execute("RELEASE doctor")
    return out


def check_layout(root: Path) -> list[tuple[str, str]]:
    out = []
    missing = [d for d in DIRS if not (root / d).is_dir()]
    out.append((OK, "目录结构完整") if not missing
               else (WARN, f"缺目录: {', '.join(missing)}（跑 kb init 补）"))
    out.append((OK, f"库文件 {db_path(root).name}") if db_path(root).exists()
               else (FAIL, "kb.sqlite 不存在（kb init）"))
    return out


def check_digest(root: Path, conn: sqlite3.Connection) -> list[tuple[str, str]]:
    from . import digest as digest_mod
    path = root / "digest" / "latest.md"
    if not path.exists():
        return [(WARN, "digest/latest.md 不存在（kb digest）")]
    current = digest_mod.render(conn)
    on_disk = path.read_text(encoding="utf-8")
    if _strip_date(current) == _strip_date(on_disk):
        return [(OK, "digest/latest.md 与库同步")]
    return [(WARN, "digest/latest.md 落后于库 —— 下次会话会被过期状态 prime，"
                   "跑一次 kb digest")]


def _strip_date(text: str) -> str:
    """只比内容，不比生成日期 —— 隔天重跑不该被报成不同步。"""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.startswith("# ashare-kb digest"))


def check_verified_evidence(root: Path, conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """每条 verified 断言：脚本还在吗？当初验的那份证据还是这份吗？

    两种失效都是静默的，而且都让库继续替一件当前证据支持不了的事背书：

      - 验证脚本被删/改名 —— 这条断言连复核都做不到了
      - 快照被换掉（法规修订、kb fetch --force）—— 验的时候是那份原文，
        现在不是了，而没有任何人会通知你

    第二种正是这个库存在的理由：「制度变化本身是最强的信号」。
    抓不到它，制度层就白做了。
    """
    rows = conn.execute(
        "SELECT id, verify_script, evidence FROM claim WHERE status='verified'"
    ).fetchall()
    if not rows:
        return [(OK, "没有 verified 断言可查（这个库还没挣到东西）")]

    out, bad, compared = [], 0, 0
    for r in rows:
        script = r["verify_script"]
        if not script or not (root / script).exists():
            out.append((FAIL, f"{r['id']}: 验证脚本 {script or '（空）'} 不存在 —— "
                              "这条断言已经无法复核，却还是 verified"))
            bad += 1
            continue
        recorded_all = json.loads(r["evidence"] or "{}")
        compared += len(recorded_all)
        for name, recorded in recorded_all.items():
            path = root / "sources" / name
            if not path.exists():
                out.append((FAIL, f"{r['id']}: 快照 sources/{name} 没了 —— "
                                  "验它的那份证据已经不在"))
                bad += 1
            elif hashlib.sha256(path.read_bytes()).hexdigest() != recorded:
                out.append((FAIL, f"{r['id']}: 快照 sources/{name} 变了 —— "
                                  "验的时候不是这份原文。重跑 kb verify；"
                                  "确认制度真的改了就 kb falsify"))
                bad += 1
    if bad:
        return out

    # 说清楚**比对了什么**，而不是笼统说"都对得上"。
    # 一条 verified 断言可能压根没有快照指纹可比（结构层的证据是实时数据；
    # 或者它是在记录指纹这个特性之前验的、又从旧账本重建过）。
    # 那种情况下这项检查是空的，措辞却听着像通过了 ——
    # 那就成了"度量组件跑没跑，而不是度量它产出了有效结论"。
    if compared:
        out.append((OK, f"{len(rows)} 条 verified 断言：脚本都在，"
                        f"{compared} 份快照指纹对得上"))
    else:
        out.append((WARN, f"{len(rows)} 条 verified 断言的脚本都在，但**没有一份快照指纹**"
                          "可比对 —— 要么它们的证据是实时数据（结构层，正常），"
                          "要么是在记录指纹之前验的。后者重跑一次 kb verify 就有了。"))
    return out


def check_akshare() -> list[tuple[str, str]]:
    try:
        import akshare as ak
    except ImportError:
        return [(WARN, "akshare 未安装 —— 结构层断言无法验证。"
                       "pip install -r requirements.txt（Debian 系统 Python 上要用干净 venv）")]
    return [(OK, f"akshare {getattr(ak, '__version__', '?')}")]


def check_feed(root: Path) -> list[tuple[str, str]]:
    """拉一只股票和一个指数，验形状。全A跑两小时之前该先过这一关。"""
    import sys
    sys.path.insert(0, str(root / "verify"))
    try:
        import ashare_data as ad
    except ImportError as exc:
        return [(WARN, f"verify/ashare_data.py 导入失败: {exc}")]

    end = _dt.date.today()
    start = (end - _dt.timedelta(days=20)).strftime("%Y%m%d")
    out = []
    for label, sym, kind in [("行情接口 + 列名", "600519", "stock"),
                             ("指数接口 (中证全指)", ad.INDEX_ALL_SHARE, "index")]:
        try:
            rows = ad.history(sym, start, end.strftime("%Y%m%d"), kind=kind)
        except KeyError as exc:
            out.append((FAIL, f"{label} —— 列名认不出: {exc}。"
                              "akshare 改过列名，ashare_data._extract_closes 要跟着改"))
            continue
        except SystemExit:
            out.append((WARN, f"{label} —— akshare 缺失，跳过"))
            continue
        except Exception as exc:
            out.append((WARN, f"{label} —— 取数失败: {type(exc).__name__}: "
                              f"{str(exc)[:90]}"))
            continue
        out.append((OK, f"{label}（{len(rows)} 个交易日）") if rows
                   else (WARN, f"{label} —— 返回空，可能是接口变了或被限流"))
    return out


def run(root: Path, offline: bool) -> int:
    try:
        conn = connect(root)
    except KBError as exc:
        print(f"{FAIL}  {exc}")
        return 1

    results = (check_layout(root) + check_gates(conn)
               + check_verified_evidence(root, conn) + check_digest(root, conn))
    results += check_akshare()
    if offline:
        results.append((WARN, "--offline：跳过取数检查"))
    else:
        results += check_feed(root)

    for status, msg in results:
        print(f"{status}  {msg}")

    failed = sum(1 for s, _ in results if s == FAIL)
    warned = sum(1 for s, _ in results if s == WARN)
    print(f"\n{len(results)} 项检查：{len(results) - failed - warned} 通过，"
          f"{warned} 警告，{failed} 失败")
    if failed:
        print("有失败项 —— 在挣到任何 verified 之前先修掉。")
    return 1 if failed else 0
