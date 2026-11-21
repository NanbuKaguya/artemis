---
name: setup-project
description: 把一个项目接入 claude-kit：建立或精简 CLAUDE.md，建立 .claude/check.sh 快速检查，可选建立格式化脚本。新项目第一次用 Claude Code 时跑一次。
disable-model-invocation: true
---

# /setup-project：一个项目只做一次

模板在本 skill 目录的 `templates/` 下。

## 1. CLAUDE.md

- 没有 CLAUDE.md：先建议用户跑 `/init` 生成初稿，再按 `templates/CLAUDE.md` 的骨架精简。
- 已经有了：也按骨架精简。

精简时对每一行问两个问题：Claude 读代码能发现吗？它会去读吗？两个都是"会"，就删掉这一行。

- 不写架构说明。官方最佳实践明确不建议这么做，Claude 自己会去读代码。
- 写进去的应该是：快速检查和单个测试的命令、读代码发现不了的坑、和默认做法不同的约定。
- 目标 80 行以内。

## 2. `.claude/check.sh`（最重要的一步）

1. 识别项目的工具链：`package.json` 的 scripts、`pyproject.toml`、`go.mod`、`Cargo.toml`、`Makefile`。
2. 按 `templates/check.sh` 写 `.claude/check.sh`，只放 **60 秒内能跑完**的检查：lint、类型检查、单元测试。慢的集成测试不要放进来。
3. 实际跑一次，把结果和耗时给用户看。

这个文件存在之后，每次 Claude 改了文件，结束前都会自动跑它，没过就会接着修。

## 3. `.claude/format.sh`（可选）

项目有格式化工具（ruff、prettier、gofmt、rustfmt……）就按 `templates/format.sh` 建一个。
之后每次编辑完单个文件，都会自动格式化那个文件。

## 4. 个人偏好

提醒用户：个人偏好写在 `CLAUDE.local.md` 里，并把它加进 `.gitignore`。

## 5. 权限

不要一开始就手写 allowlist。建议用户用一阵子之后跑 `/fewer-permission-prompts`，它会根据实际用到的命令生成。

## 6. 收尾

- 列出新建和改动的文件。
- 告诉用户：`/context all` 可以确认 CLAUDE.md 已经加载；`/doctor prompt-audit` 可以检查各份说明之间有没有冲突。
