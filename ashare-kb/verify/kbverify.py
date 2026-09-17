"""验证脚本的公共库。

退出码契约（kb verify 按它改状态）：
  0  + stdout 行首 "HOLDS:"      -> verified
  1  + stdout 行首 "FALSIFIED:"  -> falsified（自动写墓碑）
  其余一切（含缺哨兵的 0/1）      -> 不确定，状态不变

为什么要哨兵而不是只看退出码：**Python 脚本抛未捕获异常时退出码就是 1**。
只认退出码的话，一个写错的脚本会把断言判成"被数据打脸"，
库会自己给自己捏造一条教训 —— 比不验证更糟。

"不确定"必须和"被打脸"分开。脚本自己坏了、数据源没接上、
网断了 —— 这些都不是证据。用下面的 holds()/falsified() 就自动带哨兵。

环境变量：KB_ROOT、KB_CLAIM_ID。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RC_HOLDS = 0
RC_FALSIFIED = 1
RC_INCONCLUSIVE = 2


def root() -> Path:
    return Path(os.environ.get("KB_ROOT", Path(__file__).resolve().parent.parent))


def claim_id() -> str:
    return os.environ.get("KB_CLAIM_ID", "<unknown>")


def holds(msg: str) -> None:
    print(f"HOLDS: {msg}")
    sys.exit(RC_HOLDS)


def falsified(msg: str) -> None:
    print(f"FALSIFIED: {msg}")
    sys.exit(RC_FALSIFIED)


def inconclusive(msg: str) -> None:
    print(f"INCONCLUSIVE: {msg}")
    sys.exit(RC_INCONCLUSIVE)


def snapshot_text(name: str) -> str:
    """读 sources/ 下的原文快照。没有快照 = 不确定，不是成立。

    快照是 L1/L3 断言的证据本身：URL 会死、页面会改，
    本地快照不会。source_ref 指向一个不存在的文件时，
    这条断言不该是 verified。
    """
    path = root() / "sources" / name
    if not path.exists():
        inconclusive(f"缺快照 sources/{name} —— 先把原文存下来再验证")
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        inconclusive(f"读不了 sources/{name}: {exc}")
    return ""  # unreachable


def require_phrases(name: str, *phrases: str) -> None:
    """断言快照里出现了全部关键短语。任何一条缺失 = 断言被打脸。

    这是 L1 断言的标准验证形态：不是"我读过原文"，
    而是"原文里确实有这几个字，现在、在这台机器上、可复核"。
    """
    text = snapshot_text(name)
    missing = [p for p in phrases if p not in text]
    if missing:
        falsified(f"sources/{name} 中找不到: " + " / ".join(missing))
    holds(f"sources/{name} 包含全部 {len(phrases)} 条关键短语")
