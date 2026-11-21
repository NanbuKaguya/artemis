#!/usr/bin/env python3
"""安装 / 卸载 claude-kit。纯标准库，Python 3.8+。

    python3 install.py                   装到 ~/.claude，本机所有项目生效
    python3 install.py --project DIR     装到 DIR/.claude，随仓库走（云端会话用这个）
    python3 install.py --uninstall [--project DIR]
    任何时候加 --dry-run，只打印会做什么。

不覆盖你已有的东西：
  - settings.json 是合并：只追加 claude-kit 的 deny 规则和 hook；改之前先备份
  - 规则写到 rules/claude-kit.md，不碰你的 CLAUDE.md
  - 同名 skill 已存在且内容不同：跳过并提示；加 --force 才覆盖（覆盖前备份）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent / "global"
MARK = "/hooks/kit.py\""          # 用来认出 claude-kit 自己的 hook 条目
STAMP = time.strftime("%Y%m%d-%H%M%S")


def digest(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")) if p.is_dir() else [p]:
        if f.is_file():
            h.update(f.relative_to(p if p.is_dir() else p.parent).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


class Installer:
    def __init__(self, target: Path, ref: str, dry: bool, force: bool):
        self.target, self.ref, self.dry, self.force = target, ref, dry, force
        self.log: list[str] = []

    def say(self, msg: str) -> None:
        self.log.append(msg)
        print(("[dry-run] " if self.dry else "") + msg)

    def backup(self, p: Path) -> None:
        if p.exists():
            b = p.with_name(f"{p.name}.bak-{STAMP}")
            self.say(f"备份 {p} → {b.name}")
            if not self.dry:
                (shutil.copytree if p.is_dir() else shutil.copy2)(p, b)

    def put(self, src: Path, dst: Path, overwrite_own: bool) -> None:
        if dst.exists() and digest(src) == digest(dst):
            self.say(f"已是最新 {dst}")
            return
        if dst.exists() and not (overwrite_own or self.force):
            self.say(f"跳过 {dst}：已存在且内容不同（加 --force 覆盖，会先备份）")
            return
        self.backup(dst)
        self.say(f"写入 {dst}")
        if self.dry:
            return
        if dst.is_dir():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    def kit_settings(self) -> dict:
        text = (KIT / "settings.json").read_text(encoding="utf-8").replace("@KIT@", self.ref)
        return json.loads(text)

    def load_settings(self) -> tuple[Path, dict]:
        path = self.target / "settings.json"
        if not path.exists():
            return path, {}
        try:
            return path, json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            sys.exit(f"{path} 不是合法 JSON（{exc}），先修好它再装。")

    def save_settings(self, path: Path, data: dict) -> None:
        self.backup(path)
        self.say(f"写入 {path}")
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------ install

    def install(self) -> None:
        self.put(KIT / "hooks" / "kit.py", self.target / "hooks" / "kit.py", overwrite_own=True)
        self.put(KIT / "rules" / "claude-kit.md", self.target / "rules" / "claude-kit.md", overwrite_own=True)
        for skill in sorted((KIT / "skills").iterdir()):
            self.put(skill, self.target / "skills" / skill.name, overwrite_own=False)

        path, data = self.load_settings()
        kit = self.kit_settings()
        perms = data.setdefault("permissions", {})
        deny = perms.setdefault("deny", [])
        added = [d for d in kit["permissions"]["deny"] if d not in deny]
        deny += added
        hooks = data.setdefault("hooks", {})
        n = 0
        for event, groups in kit["hooks"].items():
            have = {h.get("command") for g in hooks.get(event, []) for h in g.get("hooks", [])}
            for g in groups:
                if not any(h["command"] in have for h in g["hooks"]):
                    hooks.setdefault(event, []).append(g)
                    n += 1
        if added or n:
            self.say(f"settings.json：追加 {len(added)} 条 deny 规则、{n} 个 hook")
            self.save_settings(path, data)
        else:
            self.say("settings.json：已包含 claude-kit 的全部条目")

    # ------------------------------------------------------------ uninstall

    def uninstall(self) -> None:
        for p in [self.target / "hooks" / "kit.py", self.target / "rules" / "claude-kit.md"]:
            if p.exists():
                self.say(f"删除 {p}")
                if not self.dry:
                    p.unlink()
        for skill in sorted((KIT / "skills").iterdir()):
            dst = self.target / "skills" / skill.name
            if dst.exists() and digest(dst) == digest(skill):
                self.say(f"删除 {dst}")
                if not self.dry:
                    shutil.rmtree(dst)
            elif dst.exists():
                self.say(f"保留 {dst}：内容和 claude-kit 的版本不同，可能是你改过的")
        path, data = self.load_settings()
        if not data:
            return
        kit = self.kit_settings()
        deny = data.get("permissions", {}).get("deny", [])
        data.get("permissions", {})["deny"] = [d for d in deny if d not in kit["permissions"]["deny"]]
        for event, groups in list(data.get("hooks", {}).items()):
            keep = [g for g in groups if not any(MARK in h.get("command", "") for h in g.get("hooks", []))]
            if keep:
                data["hooks"][event] = keep
            else:
                del data["hooks"][event]
        self.say("settings.json：移除 claude-kit 的 deny 规则和 hook")
        self.save_settings(path, data)


def main() -> None:
    ap = argparse.ArgumentParser(description="安装 / 卸载 claude-kit")
    ap.add_argument("--project", metavar="DIR", help="装到 DIR/.claude（随仓库提交）")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="覆盖同名但内容不同的 skill（先备份）")
    a = ap.parse_args()
    if a.project:
        root = Path(a.project).resolve()
        if not root.is_dir():
            sys.exit(f"{root} 不是目录")
        target, ref = root / ".claude", "$CLAUDE_PROJECT_DIR/.claude"
    else:
        target, ref = Path.home() / ".claude", "$HOME/.claude"
    inst = Installer(target, ref, a.dry_run, a.force)
    inst.uninstall() if a.uninstall else inst.install()
    if not a.uninstall and not a.dry_run:
        print("\n完成。下一步：在项目里启动 claude，跑一次 /setup-project。")
        print("用 /hooks 能看到已加载的 hook；/context all 能确认规则文件已加载。")


if __name__ == "__main__":
    main()
