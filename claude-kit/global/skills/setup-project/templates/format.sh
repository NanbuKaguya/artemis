#!/usr/bin/env bash
# 编辑后格式化单个文件。$1 是刚改过的文件。失败不会打断 Claude。
f="$1"
case "$f" in
  # *.py) ruff format -q "$f" ;;
  # *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.md) npx --no-install prettier -w "$f" >/dev/null ;;
  # *.go) gofmt -w "$f" ;;
  # *.rs) rustfmt -q "$f" ;;
  *) : ;;
esac
