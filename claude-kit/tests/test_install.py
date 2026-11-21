"""install.py 的回归用例。用法: python3 test_install.py <claude-kit 目录>"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(sys.argv[1]).resolve()
bad = 0


def check(name, ok, detail=""):
    global bad
    bad += not ok
    print(("ok  " if ok else "FAIL"), name, ("" if ok else detail))


def inst(*args, home):
    return subprocess.run([sys.executable, str(KIT / "install.py"), *args], capture_output=True, check=False,
                          text=True, env=dict(os.environ, HOME=str(home)))


# 用户级：已有 settings.json（有自己的 allow、deny、hook）
home = Path(tempfile.mkdtemp())
cl = home / ".claude"
cl.mkdir()
mine = {"model": "opus", "permissions": {"allow": ["Bash(npm test *)"], "deny": ["Read(**/.env)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
(cl / "settings.json").write_text(json.dumps(mine))
(cl / "CLAUDE.md").write_text("我自己的约定\n")

p = inst("--dry-run", home=home)
check("dry-run 不写任何文件", json.loads((cl / "settings.json").read_text()) == mine
      and not (cl / "hooks").exists(), p.stdout + p.stderr)

p = inst(home=home)
s = json.loads((cl / "settings.json").read_text())
check("安装成功", p.returncode == 0, p.stderr)
check("保留原有设置（model / allow / 自己的 Stop hook）",
      s["model"] == "opus" and s["permissions"]["allow"] == ["Bash(npm test *)"]
      and any(h["command"] == "say done" for g in s["hooks"]["Stop"] for h in g["hooks"]))
check("deny 去重合并（.env 只出现一次）", s["permissions"]["deny"].count("Read(**/.env)") == 1)
check("四个 hook 都装上，路径指向 $HOME/.claude",
      all(ev in s["hooks"] for ev in ("PreToolUse", "UserPromptSubmit", "PostToolUse", "Stop"))
      and '$HOME/.claude/hooks/kit.py' in json.dumps(s))
check("不碰 CLAUDE.md", (cl / "CLAUDE.md").read_text() == "我自己的约定\n")
check("规则、hook、三个 skill 都在", all((cl / f).exists() for f in [
      "rules/claude-kit.md", "hooks/kit.py", "skills/spec/SKILL.md", "skills/ship/SKILL.md",
      "skills/setup-project/SKILL.md", "skills/setup-project/templates/check.sh"]))
check("原 settings.json 有备份", any(cl.glob("settings.json.bak-*")))

before = (cl / "settings.json").read_text()
inst(home=home)
check("重复安装是幂等的", (cl / "settings.json").read_text() == before)

# 同名 skill 被用户改过：不覆盖
(cl / "skills/ship/SKILL.md").write_text("我改过的 ship\n")
p = inst(home=home)
check("用户改过的同名 skill 不被覆盖", (cl / "skills/ship/SKILL.md").read_text() == "我改过的 ship\n", p.stdout)

p = inst("--uninstall", home=home)
s = json.loads((cl / "settings.json").read_text())
check("卸载：移除 kit 的 hook，保留自己的", "kit.py" not in json.dumps(s)
      and s["hooks"]["Stop"][0]["hooks"][0]["command"] == "say done", json.dumps(s))
check("卸载：删掉 kit 文件，保留改过的 skill",
      not (cl / "hooks/kit.py").exists() and not (cl / "skills/spec").exists()
      and (cl / "skills/ship/SKILL.md").exists())

# 项目级
proj = Path(tempfile.mkdtemp())
p = inst("--project", str(proj), home=home)
s = json.loads((proj / ".claude/settings.json").read_text())
check("项目级：hook 路径用 $CLAUDE_PROJECT_DIR", "$CLAUDE_PROJECT_DIR/.claude/hooks/kit.py" in json.dumps(s), p.stderr)
check("项目级：规则在 .claude/rules/", (proj / ".claude/rules/claude-kit.md").exists())

# 坏 JSON：拒绝安装，不破坏文件
(proj / ".claude/settings.json").write_text("{坏的")
p = inst("--project", str(proj), home=home)
check("settings.json 坏了 → 拒绝安装、不改文件", p.returncode != 0 and (proj / ".claude/settings.json").read_text() == "{坏的", p.stderr)

print(f"\n{'全部通过' if not bad else f'{bad} 条失败'}")
sys.exit(1 if bad else 0)
