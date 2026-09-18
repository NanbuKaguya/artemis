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
    """断言快照里出现了全部关键短语。

    这是 L1 断言的标准验证形态：不是"我读过原文"，
    而是"原文里确实有这几个字，现在、在这台机器上、可复核"。

    **短语找不到时退「不确定」，不退「被打脸」。** 这不是保守 ——
    是分清两件事。短语匹配不上，绝大多数时候是口径问题而不是事实问题：
    原文可能写"二〇二四年四月十二日"而不是"2024年4月12日"，
    PDF 转文本可能把数字拆开，页面可能只是换了个说法。
    判成 falsified 的话，库会自动写一块记录着不存在的教训的墓碑 ——
    正是本模块开头警告的那个失败模式，只不过换了个入口。

    制度层断言的 falsify 该由人来做：读到修订后的法规，手动 kb falsify。
    脚本对 L1 的职责是"确认快照仍然支持这条断言"，
    它说"没找到"的意思是"去看一眼"，不是"它是假的"。
    """
    text = snapshot_text(name)
    missing = [p for p in phrases if p not in text]
    if missing:
        inconclusive(
            f"sources/{name} 中找不到: " + " / ".join(missing)
            + "\n  先核对短语写法与原文是否一致（日期格式、全角半角、转文本时的换行拆字）。"
            + "\n  确认原文确实不再支持这条断言了，再手动 kb falsify。"
        )
    holds(f"sources/{name} 包含全部 {len(phrases)} 条关键短语")
