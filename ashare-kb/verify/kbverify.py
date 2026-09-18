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

import hashlib
import os
import sys
from pathlib import Path

RC_HOLDS = 0
RC_FALSIFIED = 1
RC_INCONCLUSIVE = 2

# 低于这个长度的快照当作"没抽对"，而不是"短语找不到"
MIN_SNAPSHOT_CHARS = 200

# 这次运行读过哪些快照，以及它们当时的指纹。holds() 会把它报给 kb verify，
# 于是"这条断言是对着哪份证据验过的"变成可复核的事实，而不是记忆。
_evidence: dict[str, str] = {}


def root() -> Path:
    return Path(os.environ.get("KB_ROOT", Path(__file__).resolve().parent.parent))


def claim_id() -> str:
    return os.environ.get("KB_CLAIM_ID", "<unknown>")


def holds(msg: str) -> None:
    # 先报证据再报结论：kb verify 把这些指纹存进库，
    # 之后 kb doctor 就能发现"验的时候是这份原文，现在不是了"。
    for name, digest in sorted(_evidence.items()):
        print(f"EVIDENCE: {name} {digest}")
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
        raw = path.read_bytes()
    except OSError as exc:
        inconclusive(f"读不了 sources/{name}: {exc}")
        return ""  # unreachable
    _evidence[name] = hashlib.sha256(raw).hexdigest()
    return raw.decode("utf-8", errors="replace")


def normalize(text: str) -> str:
    """折叠掉不改变内容的写法差异，好让短语匹配不被排版打败。

    做两件事：
      - 去掉全部空白 —— PDF 转文本会把"50万元"拆到两行，把"20 个交易日"
        中间塞进换行；这些都不是内容差异
      - 全角数字/字母/标点 -> 半角 —— 同一个数字的两种编码

    **不做的事**：不做同义替换，不做繁简转换，不做近义归并。

    normalize 只能消除"同一个字符串的不同写法"。一旦它开始消除
    "不同的说法"，验证就比断言宽松了 —— 那时脚本说 HOLDS，
    实际支持的是一条比库里记的更弱的断言。
    """
    out = []
    for ch in text:
        code = ord(ch)
        if ch.isspace():
            continue
        if 0xFF01 <= code <= 0xFF5E:      # 全角 ASCII -> 半角
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


_CN_DIGITS = "〇一二三四五六七八九"


def _cn_num(n: int) -> str:
    """1-31 的中文写法：12 -> 十二，20 -> 二十，24 -> 二十四。"""
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n - 10] if n > 10 else "")
    return _CN_DIGITS[n // 10] + "十" + (_CN_DIGITS[n % 10] if n % 10 else "")


def date_variants(year: int, month: int, day: int) -> tuple[str, ...]:
    """一个日期在法规原文里的常见写法，用作 require_phrases 的候选组。

    国务院、证监会、交易所的文件正文用阿拉伯数字，落款和文号常用中文数字，
    网页版和 PDF 版也不一致。写死一种写法，验证失败的原因就会是排版而不是事实 ——
    而那正是 require_phrases 退 2 不退 1 的原因。这里把这类差异提前消掉。
    """
    cn_year = "".join(_CN_DIGITS[int(c)] for c in str(year))
    return (
        f"{year}年{month}月{day}日",
        f"{year}年{month:02d}月{day:02d}日",
        f"{cn_year}年{_cn_num(month)}月{_cn_num(day)}日",
        f"{year}-{month:02d}-{day:02d}",
    )


def contains(text: str, phrase: str) -> bool:
    """子串匹配，但数字边界必须干净。

    短语 "50万元" 不该在 "150万元" 里命中。门槛从 50 万改成 150 万之后，
    朴素的子串匹配会让脚本继续说 HOLDS，库里就留下一条已经过时的 verified
    断言 —— 而且是往 verified 那个方向错的，比漏验证危险得多。

    规则很窄：短语首尾是数字时，原文里紧挨着的那一位不能也是数字。
    只挡这一种，不做更多推断。
    """
    start = 0
    while True:
        i = text.find(phrase, start)
        if i < 0:
            return False
        head_ok = not (phrase[0].isdigit() and i > 0 and text[i - 1].isdigit())
        j = i + len(phrase)
        tail_ok = not (phrase[-1].isdigit() and j < len(text) and text[j].isdigit())
        if head_ok and tail_ok:
            return True
        start = i + 1


def _label(phrase) -> str:
    return " 或 ".join(phrase) if isinstance(phrase, tuple) else phrase


def check_phrases(name: str, *phrases) -> tuple[list[str], str | None]:
    """核对快照，返回 (缺失的短语, 读不到快照的原因)。**不退出。**

    多份快照的断言用它累积，最后一次性判定 —— 比如一条断言同时依赖
    《交易规则》和《融资融券交易实施细则》，就该两份都核对过再下结论。
    """
    path = root() / "sources" / name
    if not path.exists():
        return [], f"缺快照 sources/{name} —— 先把原文存下来再验证"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [], f"读不了 sources/{name}: {exc}"
    _evidence[name] = hashlib.sha256(raw).hexdigest()
    text = normalize(raw.decode("utf-8", errors="replace"))

    # 空快照报"核对短语写法"是误导 —— 问题在取数那一步，不在短语。
    if len(text) < MIN_SNAPSHOT_CHARS:
        return [], (f"sources/{name} 只有 {len(text)} 个字符 —— 八成没抽对"
                    "（扫描版 PDF？抓到的是导航页？）。先打开看一眼")

    missing = []
    for phrase in phrases:
        options = phrase if isinstance(phrase, tuple) else (phrase,)
        if not any(contains(text, normalize(o)) for o in options):
            missing.append(_label(phrase))
    return missing, None


def require_phrases(name: str, *phrases) -> None:
    """断言快照里出现了全部关键短语。

    每个"短语"可以是一个字符串，也可以是一个 tuple —— tuple 表示
    候选组，任一命中即可（同一事实的不同写法，见 date_variants）。

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
    missing, problem = check_phrases(name, *phrases)
    if problem:
        inconclusive(problem)
    if missing:
        inconclusive(
            f"sources/{name} 中找不到: " + " / ".join(missing)
            + "\n  先核对短语写法与原文是否一致（日期格式、全角半角、转文本时的换行拆字）。"
            + "\n  确认原文确实不再支持这条断言了，再手动 kb falsify。"
        )
    holds(f"sources/{name} 包含全部 {len(phrases)} 条关键短语")


def require_across(snapshots: dict[str, tuple], claim_note: str = "") -> None:
    """一条断言依赖多份快照时用它：{快照文件名: (短语, ...)}。

    全部命中才 HOLDS。任何一份缺失或任何一条短语落空 -> 不确定。
    """
    problems, missing = [], []
    for name, phrases in snapshots.items():
        miss, problem = check_phrases(name, *phrases)
        if problem:
            problems.append(problem)
        missing += [f"{name}: {m}" for m in miss]

    if problems:
        inconclusive("; ".join(problems))
    if missing:
        inconclusive(
            "找不到: " + " / ".join(missing)
            + "\n  先核对短语写法与原文是否一致；确认原文确实不再支持这条断言了，"
              "再手动 kb falsify。"
        )
    total = sum(len(v) for v in snapshots.values())
    holds(f"{len(snapshots)} 份快照共 {total} 条关键短语全部命中"
          + (f"（{claim_note}）" if claim_note else ""))
