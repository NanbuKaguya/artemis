"""append-only 事件账本。

kb.sqlite 是派生物（.gitignore 掉了）。进 git 的是这个 JSONL：
它可 diff、可审计、可 merge，而且 `kb rebuild` 能从它完整重建数据库。
每个事件携带动作之后的完整行快照，所以重放不需要推断。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

EVENTS = "ledger/events.jsonl"


def events_path(root: Path) -> Path:
    return root / EVENTS


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def append(root: Path, action: str, claim_id: str, row: dict | None, **extra) -> dict:
    event = {"ts": now(), "action": action, "claim_id": claim_id, "row": row}
    event.update({k: v for k, v in extra.items() if v is not None})
    path = events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=False) + "\n")
    return event


def read_all(root: Path) -> list[dict]:
    path = events_path(root)
    if not path.exists():
        return []
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{EVENTS}:{lineno} 解析失败: {exc}") from exc
    return out


def history(root: Path, claim_id: str) -> list[dict]:
    return [e for e in read_all(root) if e.get("claim_id") == claim_id]
