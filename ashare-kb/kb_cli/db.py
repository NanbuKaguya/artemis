"""库的位置、连接、初始化。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = PKG_DIR.parent / "schema.sql"

DIRS = ("ledger", "ledger/falsified", "sources", "verify", "digest")

STALE_DEFAULT = {"institutional": None, "structural": 90}


class KBError(Exception):
    """预期内的用户错误 —— 打印一行，退出非零，不要栈回溯。"""


def kb_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("ASHARE_KB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return PKG_DIR.parent


def db_path(root: Path) -> Path:
    return root / "kb.sqlite"


def ensure_dirs(root: Path) -> None:
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)


def connect(root: Path, create: bool = False) -> sqlite3.Connection:
    path = db_path(root)
    if not path.exists() and not create:
        raise KBError(f"库不存在: {path}\n先跑: kb init")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def init(root: Path) -> sqlite3.Connection:
    ensure_dirs(root)
    conn = connect(root, create=True)
    apply_schema(conn)
    return conn


def count_claims(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM claim").fetchone()[0]


def get_claim(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM claim WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise KBError(f"没有这条断言: {claim_id}")
    return row


def row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}
