"""断言 ID：由 statement 决定性地导出。

同一句话永远得到同一个 id，所以重复 kb lead 会在主键上撞车而不是
生成第二条记录。去重是免费的副作用。
"""

from __future__ import annotations

import hashlib

_PREFIX = {"institutional": "inst", "structural": "strc"}


def claim_id(layer: str, statement: str) -> str:
    if layer not in _PREFIX:
        raise ValueError(f"unknown layer: {layer}")
    digest = hashlib.sha1(statement.strip().encode("utf-8")).hexdigest()[:8]
    return f"{_PREFIX[layer]}-{digest}"
