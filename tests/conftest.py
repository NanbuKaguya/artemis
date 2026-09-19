"""让每次测试运行都说清：绿灯覆盖的是哪一部分代码。

为什么需要这个：结局 C 决定了只跑 lite 的几条命令，于是仓库里约三分之二
的代码在那条路径上永不加载。"148 passed" 会让人以为整个系统被验证过了 ——
它只证明逻辑自洽，不证明你每天用的那条路是对的，更不证明数据是对的。

这行汇总不是装饰。它是防止下一个人（包括几周后的我们自己）
把测试数量当成信心来源。
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 结局 C 的日常命令（watch / log / review / audit）会加载到的模块
LIVE = {
    "lite.py", "config.py", "rules.py", "calendar.py", "doctor.py",
    "review/journal.py", "guard/rules.py", "data/preflight.py",
    "data/schema.py", "data/synthetic.py",
}


def _split() -> tuple[int, int]:
    live = dormant = 0
    for p in (ROOT / "artemis").rglob("*.py"):
        rel = p.relative_to(ROOT / "artemis").as_posix()
        n = len(p.read_text(encoding="utf-8").splitlines())
        if rel in LIVE:
            live += n
        elif rel != "__init__.py":
            dormant += n
    return live, dormant


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    live, dormant = _split()
    tot = live + dormant or 1
    terminalreporter.write_sep("-", "覆盖范围的诚实说明")
    terminalreporter.write_line(
        f"每天真正会跑的代码 {live} 行 ({live/tot*100:.0f}%)；"
        f"结局 C 下永不加载 {dormant} 行 ({dormant/tot*100:.0f}%)。")
    terminalreporter.write_line(
        "绿灯只说明逻辑自洽。数据是否正确，要靠 `artemis watch` 每次打印的"
        "数据凭证，以及在真机上跑出来的缺失率。")
