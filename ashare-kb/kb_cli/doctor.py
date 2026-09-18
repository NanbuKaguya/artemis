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

    results = check_layout(root) + check_gates(conn) + check_digest(root, conn)
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
