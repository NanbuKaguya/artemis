#!/usr/bin/env python3
"""闸 —— CLAUDE.md 那道硬闸的单一真相源。纯标准库。

    gate.py status    人读：闸开着还是关着，凭什么
    gate.py session   SessionStart hook：kb init（如需）+ doctor 摘要 + 闸 + digest。
                      stdout 进模型上下文 —— 这就是"开工前先读 digest"的机械版
    gate.py pretool   PreToolUse hook：stdin 读一次工具调用，stdout 写决定

判据（与 CLAUDE.md 一致，改一处必须改另一处）：
    关  ⇐  verified == 0
    关  ⇐  最近一次 verified 增加之后，已有 ≥ 3 个提交改了 ashare-kb 的代码
    代码 = ashare-kb 下的 *.py、*.sql、kb。按扩展名，不按目录 —— verify/README.md 不是代码。

这个脚本只做三件事：算闸、在边界上把决定交给人、挡住往 sources/ 里直接写字节。
它刻意不做别的。门越多，越像在建它而不是用它。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
KB = REPO / "ashare-kb"
LEDGER_REL = "ashare-kb/ledger/events.jsonl"
# git 默认 pathspec 里 * 会跨过 /，所以 'ashare-kb/*.py' 就是递归的。
# 别写成 'ashare-kb/**/*.py' —— 那个要求中间至少有一层目录，会漏掉 seed.py。
CODE_PATHSPEC = ["ashare-kb/*.py", "ashare-kb/*.sql", "ashare-kb/kb"]
CLOSE_AFTER = 3


# ---------------------------------------------------------------- 闸的判据

def _git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else ""


def _verified(ledger_text: str) -> int:
    """重放账本。每个事件都带着动作之后的完整行，所以只需取最后一个状态。"""
    status: dict[str, str] = {}
    for line in ledger_text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        row = ev.get("row") or {}
        if ev.get("claim_id") and row.get("status"):
            status[ev["claim_id"]] = row["status"]
    return sum(1 for s in status.values() if s == "verified")


def gate() -> dict:
    path = REPO / LEDGER_REL
    now = _verified(path.read_text(encoding="utf-8")) if path.exists() else 0
    if now == 0:
        return {"open": False, "verified": 0, "since": None,
                "why": "verified = 0 —— 这个库还没挣到任何东西"}

    at_head = _verified(_git("show", f"HEAD:{LEDGER_REL}"))
    if now > at_head:   # 增加还没提交：刚挣到，计数从零开始
        return {"open": True, "verified": now, "since": 0, "why": "verified 刚增加（尚未提交）"}

    rise = None
    for c in _git("log", "--format=%H", "--", LEDGER_REL).split():
        if _verified(_git("show", f"{c}:{LEDGER_REL}")) > _verified(_git("show", f"{c}^:{LEDGER_REL}")):
            rise = c
            break
    rng = f"{rise}..HEAD" if rise else "HEAD"
    n = len(_git("rev-list", rng, "--", *CODE_PATHSPEC).split())
    if n >= CLOSE_AFTER:
        return {"open": False, "verified": now, "since": n,
                "why": f"verified 上次增加之后已有 {n} 个提交改了代码而它没再增加"}
    return {"open": True, "verified": now, "since": n,
            "why": f"verified 上次增加之后 {n}/{CLOSE_AFTER} 个代码提交"}


def status_text(g: dict) -> str:
    head = "🟢 闸开着" if g["open"] else "⛔ 闸关着"
    lines = [f"{head} · verified {g['verified']} · {g['why']}"]
    if not g["open"]:
        lines.append("  关着时：不改 ashare-kb 下的 *.py / *.sql / kb。排查照做，发现写进 "
                     "ROADMAP.md「待修（闸开之后）」。")
    return "\n".join(lines)


# ---------------------------------------------------------------- SessionStart

def _kb(*args: str) -> str:
    r = subprocess.run([str(KB / "kb"), *args], cwd=KB, capture_output=True, text=True,
                       timeout=60, check=False)
    return (r.stdout + r.stderr).strip()


def session() -> None:
    out = ["# 会话开工块（.claude/hooks/gate.py session 自动生成）", ""]
    if not (KB / "kb.sqlite").exists():   # kb.sqlite 不进 git，新克隆必然没有
        out.append("kb init: " + _kb("init").splitlines()[0])
    doc = [l for l in _kb("doctor", "--offline").splitlines()
           if l.startswith(("FAIL", "WARN")) or "项检查" in l]
    out += ["## doctor --offline", *doc, ""]
    g = gate()
    out += ["## 闸", status_text(g), ""]
    if g["verified"] == 0:
        out += ["## 唯一能让指标动的动作",
                "把原文快照弄进 sources/（用户提供 / 在用户机器上从发布机构取），走 /kb-ingest。",
                "远程沙箱取不到 gov.cn 和交易所 —— 别重新发现这件事。", "",
                _kb("fetch", "--list"), ""]
    digest = KB / "digest" / "latest.md"
    if digest.exists():
        out += ["## digest/latest.md（你被 prime 的材料）", "", digest.read_text(encoding="utf-8")]
    print("\n".join(out))


# ---------------------------------------------------------------- PreToolUse

PROVENANCE = (
    "证据边界：这一步会改变断言的来源或状态。批准前请确认 —— "
    "① 快照的每个字节来自模型之外，且能指着一个机构说「是它发布的」（GitHub 镜像 = L5）；"
    "② --url 是你给的或发布机构的原址；③ 验证脚本真的打开了快照并比对短语，不是一行 print。"
)
KB_BOUNDARY = re.compile(r"(?:(?:^|[\s/;&|(])kb|kb_cli)\s+(fetch|source|verify|falsify)\b(?!\s+--list)")
REDIRECT = re.compile(r"(?<![0-9&])>>?\s*([^\s;&|<>]+)")
# 改所有参数的（sed -i / perl -i / tee / mv）和只改最后一个参数的（cp）
WRITE_ALL = re.compile(r"(?:^|[\s;&|(])(?:sed\s+-[a-zA-Z]*i|perl\s+-[a-zA-Z]*i|tee|mv)\b([^;&|]*)")
WRITE_LAST = re.compile(r"(?:^|[\s;&|(])cp\b([^;&|]*)")


def _decide(kind: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": kind,
        "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)


def _rel(p: str, cwd: Path) -> str | None:
    """相对仓库根的路径；仓库外返回 None。裸相对路径也试一下 ashare-kb/ 底下。"""
    p = p.strip("'\"")
    if not p:
        return None
    for base in (cwd, KB):
        q = (base / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
        try:
            rel = q.relative_to(REPO).as_posix()
        except ValueError:
            continue
        if rel.startswith("ashare-kb/"):
            return rel
    return None


def _is_snapshot(rel: str) -> bool:
    return rel.startswith("ashare-kb/sources/") and not rel.endswith("README.md")


def _is_code(rel: str) -> bool:
    return rel.endswith((".py", ".sql")) or rel == "ashare-kb/kb"


def _check_paths(paths: list[str], cwd: Path, via: str) -> None:
    rels = [r for r in (_rel(p, cwd) for p in paths) if r]
    if any(_is_snapshot(r) for r in rels):
        _decide("deny", f"sources/ 的每个字节必须来自模型之外。不要用 {via} 往里写。"
                "用户给的原文先原样存到 scratchpad，再 `./kb fetch <名> --from-file <文件> --url <原址>`。"
                "见 /kb-ingest。")
    code = [r for r in rels if _is_code(r)]
    if code:
        g = gate()
        if not g["open"]:
            _decide("ask", f"{status_text(g)}\n要改：{', '.join(code)}。"
                    "只有你明确要这么做时才批准 —— 产出侧还是零，改代码不会让它动。")


def pretool() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
    cwd = Path(data.get("cwd") or REPO)

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        if p:
            _check_paths([p], cwd, tool)
        return

    if tool == "Bash":
        cmd = inp.get("command", "")
        if KB_BOUNDARY.search(cmd):
            _decide("ask", PROVENANCE)
        targets = REDIRECT.findall(cmd)
        for args in WRITE_ALL.findall(cmd):
            targets += [a for a in args.split() if not a.startswith("-")]
        for args in WRITE_LAST.findall(cmd):
            targets += [a for a in args.split() if not a.startswith("-")][-1:]
        _check_paths(targets, cwd, "shell")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if mode == "session":
            session()
        elif mode == "pretool":
            pretool()
        else:
            print(status_text(gate()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 —— hook 绝不能把会话弄坏；坏了就说出来，不做决定
        print(f"gate.py {mode} 出错：{exc!r} —— 手动跑 `python3 .claude/hooks/gate.py status`",
              file=sys.stderr)


if __name__ == "__main__":
    main()
