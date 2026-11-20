# artemis

第一个仓库

## ashare-kb

A股知识库：**存可验证的断言，不存理解**。

每个会话的 Claude 不携带上个会话的任何东西 —— 所以"让模型不断学习"做不到，
能做到的是让每次会话的 Claude 被一个库 prime。学习的载体是库，模型只是
消费者和贡献者。见 [`ashare-kb/README.md`](ashare-kb/README.md)。

```bash
cd ashare-kb && ./kb init && ./kb digest
```

`.claude/` 是给 Claude Code 的工作系统：开工自动注入 digest 和闸状态（hook），
闸关时改代码要你确认，`sources/` 不许模型直接写，`/kb-ingest` `/kb-lead` `/kb-audit` 三个入口。
