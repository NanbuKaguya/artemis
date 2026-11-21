#!/usr/bin/env bash
# 本项目的快速检查。要求：60 秒内跑完；通过退出 0，不通过退出非 0。
# 每次 Claude 改了文件，结束前会自动跑它（claude-kit 的 Stop hook）；/ship 提交前也会跑。
# 只放快的：lint、类型检查、单元测试。慢的集成测试放到 CI。
set -euo pipefail
cd "$(dirname "$0")/.."

# 按项目保留一组，删掉其余的：

# Node / TypeScript
# npm run -s lint
# npx --no-install tsc --noEmit
# npm test --silent

# Python
# ruff check .
# pytest -q -x

# Go
# go vet ./...
# go test ./...

# Rust
# cargo clippy -q -- -D warnings
# cargo test -q
