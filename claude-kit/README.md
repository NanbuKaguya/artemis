# claude-kit

一套通用的 Claude Code 工作系统，所有项目都能用，和 `ashare-kb/` 无关。

设计原则只有一条：**Claude Code 已经内置的不重造**。这里只补内置没有的四样东西：

| 部件 | 作用 | 生效方式 |
|---|---|---|
| `rules/claude-kit.md` | 工作约定：任务分级、完成要有证据、改动要小、卡住怎么办 | 每次会话自动加载 |
| `hooks/kit.py` | 改了文件就自动跑检查，没过不让结束；拦危险的 git 和 rm 命令；可选自动格式化 | 由 harness 执行，模型绕不开 |
| `settings.json` | 密钥文件不进对话（deny 规则在任何权限模式下都有效） | 由 harness 执行 |
| 三个 skill | `/spec` 大任务先写规格、`/ship` 交付成 PR、`/setup-project` 新项目接入 | 你手动调用 |

完整说明和可视化手册见 PR 描述里的链接。

## 安装

需要 Python 3.8+ 和 git。

```bash
python3 claude-kit/install.py --dry-run            # 先看会做什么
python3 claude-kit/install.py                      # 装到 ~/.claude，本机所有项目生效
python3 claude-kit/install.py --project <仓库>      # 装到 <仓库>/.claude，随仓库提交
python3 claude-kit/install.py --uninstall          # 卸载
```

**用 Claude Code 网页版（云端会话）的话，用 `--project`。** 云端容器每次都是新的，`~/.claude`
不会保留，只有提交进仓库的 `.claude/` 会跟着走。

安装器不覆盖你已有的东西：

- `settings.json` 是合并：只追加条目，改之前先备份。
- 规则写到 `rules/claude-kit.md`，不碰你的 CLAUDE.md。
- 你改过的同名 skill 会跳过（加 `--force` 才覆盖，覆盖前也会备份）。

## 装完之后

1. 在项目里启动 `claude`，第一次会出现信任对话框，接受它。不信任的目录不会加载项目里的规则和 skill。
2. 跑一次 `/setup-project`。它会精简 CLAUDE.md，并建立 `.claude/check.sh`。
3. 用 `/context all` 确认 `rules/claude-kit.md` 出现在 Memory files 里，用 `/hooks` 确认四个 hook 都在。

## 项目里的两个约定文件

| 文件 | 有它会怎样 | 没有会怎样 |
|---|---|---|
| `.claude/check.sh` | 每次 Claude 改了文件，结束前自动跑；没过就让它接着修（每次最多拦一次，不会死循环） | 不跑检查，Claude 会按约定先问你怎么验证 |
| `.claude/format.sh` | 每次编辑后格式化那个文件 | 什么都不做 |

## 自检

```bash
python3 claude-kit/tests/test_kit.py claude-kit        # hook：48 个用例
python3 claude-kit/tests/test_install.py claude-kit    # 安装器：15 个用例
```

## 刻意没有做的

| 想做的 | 为什么不做 | 用什么代替 |
|---|---|---|
| 审查子代理 | 已经内置 | `/code-review`（用新上下文审查） |
| 交接笔记 | 已经内置 | `/rename` + `claude --resume`、`/compact <重点>` |
| 开工时注入 git 状态 | 已经在系统提示里 | 不需要 |
| 预置一大串 allowlist | 内置的工具会根据你的实际用法生成 | `/fewer-permission-prompts` |
| 探索、规划子代理 | 已经内置 | Explore、Plan、plan mode |
| 并行开发脚手架 | 已经内置 | `claude -w <名>`、`/batch` |
| 在 CLAUDE.md 里写架构 | 官方最佳实践明确不建议 | Claude 自己读代码 |
