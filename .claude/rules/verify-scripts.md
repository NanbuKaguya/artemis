---
paths:
  - "ashare-kb/verify/**"
---

# 写 / 改验证脚本时

- **脚本必须真的核对证据**：打开快照或数据、做比较。一个不打开任何文件、不做任何比较的
  脚本（`print("HOLDS: ...")`）是"我读过了"换了身衣服 —— 它会拿到 verified，doctor 全绿。
  写不出真能核对的，就 `kv.inconclusive()`，让闸关着。
- 检验的是 `if_wrong`，不是 `statement`。两者原样抄在脚本顶部，改断言就改脚本。
- 候选组放宽的是**写法**，不是事实。少一个成分照样不通过。永远不为跑通而放宽判定。
- 制度层 verified 却出现 doctor 的「没有一份快照指纹」WARN = 基本就是假脚本。要查。
- 细节（退出码契约、`require_phrases` / `require_across`、数字边界）：`ashare-kb/verify/README.md`。
