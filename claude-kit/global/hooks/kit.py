#!/usr/bin/env python3
"""claude-kit 的全部 hook，一个文件。纯标准库，Python 3.8+。

    kit.py guard      PreToolUse(Bash)  拦危险命令：force push 主干、rm -rf 根目录、丢弃未提交改动、碰密钥
    kit.py snapshot   UserPromptSubmit  记下这一轮开始时工作区的指纹
    kit.py stop       Stop              这一轮改过文件 且 项目有 .claude/check.sh → 跑它；没过就让 Claude 接着修
    kit.py format     PostToolUse       项目有 .claude/format.sh → 对刚改的文件跑一次；从不阻塞

刻意没有的：开工时注入 git 状态（Claude Code 已经放进系统提示了）、交接笔记
（用 /rename + claude --resume，或 /compact <重点>）。

两条底线：
  1. hook 坏了绝不能把会话弄坏 —— 任何异常都吞掉、在 stderr 说一声、不做决定。
  2. 一个会误报的检查会训练人无视它 —— 宁可漏拦顺手的写法，也不拦正常操作。
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

PROTECTED = {"main", "master"}
SECRET_GLOBS = [".env", ".env.local", ".env.*.local", ".env.production",
                "*.pem", "*.key", "id_rsa*", "id_ed25519*", "credentials.json"]
SECRET_OK = {".env.example", ".env.sample", ".env.template"}
SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<"}
CHECK = ".claude/check.sh"
FORMAT = ".claude/format.sh"


# ---------------------------------------------------------------- 公共

def _stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def _root(data: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _decide(kind: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": kind,
        "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)


# ---------------------------------------------------------------- guard

def _commands(cmd: str, depth: int = 0) -> list[list[str]] | None:
    """按 shell 词法切成简单命令。引号里的东西不是命令。切不开就返回 None（不做决定）。"""
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
    except ValueError:
        return None
    cmds, cur = [], []
    for t in toks:
        if t in SEPARATORS:
            cmds.append(cur)
            cur = ["|"] if t in ("|", "|&") else []   # 记住"我在管道后面"
        else:
            cur.append(t)
    cmds.append(cur)
    out = []
    for words in cmds:
        piped = bool(words) and words[0] == "|"
        words = [w for i, w in enumerate(words[1 if piped else 0:])
                 if w not in REDIRECTS]
        while words and re.match(r"^[A-Za-z_]\w*=", words[0]):      # FOO=bar cmd
            words = words[1:]
        while words and words[0] in ("sudo", "command", "exec", "nohup", "time"):
            words = words[1:]
        if not words:
            continue
        name = os.path.basename(words[0])
        if name in ("bash", "sh", "zsh") and "-c" in words and depth < 2:
            k = words.index("-c")
            inner = _commands(words[k + 1], depth + 1) if k + 1 < len(words) else None
            out += inner or []
            continue
        out.append((["|"] if piped else []) + words)
    return out


def _is_secret(tok: str) -> bool:
    base = os.path.basename(tok.rstrip("/"))
    if base in SECRET_OK:
        return False
    return any(fnmatch.fnmatch(base, g) for g in SECRET_GLOBS)


def _git_verdict(args: list[str], root: Path) -> tuple[str, str] | None:
    if not args:
        return None
    sub, rest = args[0], args[1:]
    flags = {a for a in rest if a.startswith("-")}
    if "--no-verify" in flags or ("-n" in flags and sub == "commit"):
        return "ask", "跳过了 git hook（--no-verify）。只有你明确要这么做时才批准。"
    if sub == "push":
        force = flags & {"-f", "--force", "--force-with-lease", "--force-if-includes"} \
            or any(a.startswith("+") for a in rest if not a.startswith("-"))
        refs = [a.lstrip("+").split(":")[-1] for a in rest if not a.startswith("-")][1:]
        current = _git(root, "symbolic-ref", "--short", "-q", "HEAD").strip()   # 还没有提交的仓库也认得
        hits_main = any(r in PROTECTED for r in refs) or (not refs and current in PROTECTED)
        if force and hits_main:
            return "deny", "不要 force push 到主干。要撤销主干上的提交，用 git revert 开一个 PR。"
        if force:
            return "ask", "force push 会改写远端历史。确认这个分支只有你在用再批准。"
        if hits_main:
            return "ask", "这会直接推到主干，没有经过 PR。确认是你要的再批准。"
    if sub == "reset" and "--hard" in flags:
        return "ask", "git reset --hard 会丢掉所有未提交改动。"
    if sub == "clean" and any(re.match(r"^-[a-zA-Z]*f", f) for f in flags):
        return "ask", "git clean -f 会删掉未跟踪的文件，删了找不回来。"
    if sub in ("checkout", "restore") and ("--" in rest or "." in rest) and "--staged" not in flags:
        return "ask", f"git {sub} 这种写法会丢掉工作区里的未提交改动。"
    if sub == "branch" and "-D" in flags:
        return "ask", "git branch -D 会删掉没合并的分支。"
    if sub == "stash" and rest[:1] and rest[0] in ("drop", "clear"):
        return "ask", "会永久丢掉 stash 里的改动。"
    return None


def guard(data: dict) -> None:
    if data.get("tool_name") != "Bash":
        return
    root = _root(data)
    cmds = _commands((data.get("tool_input") or {}).get("command", ""))
    if not cmds:
        return
    home = str(Path.home())
    asks: list[str] = []
    fetched = False
    for words in cmds:
        piped = words[0] == "|"
        if piped:
            words = words[1:]
        name, args = os.path.basename(words[0]), words[1:]
        if name in ("curl", "wget"):
            fetched = True
        if piped and fetched and name in ("sh", "bash", "zsh") and not [a for a in args if not a.startswith("-")]:
            asks.append("把下载的脚本直接交给 shell 执行。先下载、读一遍再跑。")
        if name == "rm":
            flags = "".join(a.lstrip("-") for a in args if a.startswith("-") and not a.startswith("--"))
            recursive = "r" in flags.lower() or "--recursive" in args
            targets = [a for a in args if not a.startswith("-")]
            danger = {"/", "/*", "~", "~/", "~/*", ".", "./", "..", "*", home, home + "/"}
            if recursive and any(t in danger for t in targets):
                _decide("deny", f"rm -r 的目标是 {' '.join(targets)}，范围太大。写出具体的目录。")
        if name == "git":
            v = _git_verdict(args, root)
            if v and v[0] == "deny":
                _decide(*v)
            if v:
                asks.append(v[1])
        secrets = [a for a in args if _is_secret(a)]
        if secrets:
            asks.append(f"命令碰到了密钥文件 {', '.join(secrets)}，内容会进入对话。")
    if asks:
        _decide("ask", " ".join(dict.fromkeys(asks)))


# ---------------------------------------------------------------- snapshot / stop

def _fingerprint(root: Path) -> str:
    """工作区指纹：哪些文件有改动、各自的大小和修改时间。只看 git 认得的范围。"""
    h = hashlib.sha256()
    for entry in _git(root, "status", "--porcelain=v1", "-z", "-uall").split("\0"):
        if len(entry) < 4:
            continue
        path = root / entry[3:]
        try:
            st = path.stat()
            h.update(f"{entry}|{st.st_size}|{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"{entry}|gone\n".encode())
    return h.hexdigest()


def _state(data: dict) -> Path:
    sid = re.sub(r"[^\w-]", "", str(data.get("session_id") or "nosession"))[:80]
    return Path(tempfile.gettempdir()) / f"claude-kit-{sid}.fp"


def snapshot(data: dict) -> None:
    root = _root(data)
    if _git(root, "rev-parse", "--git-dir"):
        _state(data).write_text(_fingerprint(root))


def stop(data: dict) -> None:
    if data.get("stop_hook_active"):
        return                                   # 已经被拦过一次了：不再拦，免得死循环
    root = _root(data)
    check = root / CHECK
    if not check.exists() or not _git(root, "rev-parse", "--git-dir"):
        return
    state = _state(data)
    before = state.read_text() if state.exists() else None
    now = _fingerprint(root)
    if before == now or (before is None and not _git(root, "status", "--porcelain")):
        return                                   # 这一轮没改文件（只是聊天、只读代码）：不跑
    limit = int(os.environ.get("CLAUDE_KIT_CHECK_TIMEOUT", "300"))
    try:
        r = subprocess.run(["bash", str(check)], cwd=root, capture_output=True,
                           text=True, timeout=limit, check=False)
        code, output = r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        code, output = -1, f"超过 {limit} 秒没跑完。check.sh 应该只放快速检查。"
    state.write_text(_fingerprint(root))
    if code == 0:
        return
    tail = "\n".join(output.strip().splitlines()[-60:])
    sys.stderr.write(
        f"{CHECK} 没通过（退出码 {code}）。先修好再结束，并把修完后的检查结果贴出来。\n"
        "如果失败是预期的（比如用户只让你先写测试），说明原因后结束即可。\n"
        "不要为了让它通过而删测试、跳过测试或放宽断言。\n\n" + tail + "\n")
    sys.exit(2)


# ---------------------------------------------------------------- format

def fmt(data: dict) -> None:
    root = _root(data)
    script = root / FORMAT
    path = (data.get("tool_input") or {}).get("file_path")
    if script.exists() and path:
        subprocess.run(["bash", str(script), path], cwd=root, capture_output=True,
                       timeout=30, check=False)


# ---------------------------------------------------------------- main

MODES = {"guard": guard, "snapshot": snapshot, "stop": stop, "format": fmt}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        sys.stderr.write(f"用法: kit.py {{{'|'.join(MODES)}}}\n")
        return
    try:
        MODES[mode](_stdin())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 —— hook 绝不能把会话弄坏
        sys.stderr.write(f"claude-kit {mode} 出错（已忽略）：{exc!r}\n")


if __name__ == "__main__":
    main()
