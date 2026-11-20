---
name: kb-ingest
description: 把用户提供的原文（他粘贴的文本、他给的文件、或他指定的发布机构 URL）存成 ashare-kb/sources/ 快照，并走完 source → verify。这是唯一能让 verified 增加的动作。用户贴来法规/公告原文、给出下载的 PDF、或说"去取这份文件"时使用。
---

# kb-ingest —— 唯一能开闸的动作

## 0. 先判来源（过不了就停，改走 /kb-lead）

判据只有一个：**出了问题，能不能指着一个机构说"是它发布的"？**

| 来源 | 能进 sources/ 吗 |
|---|---|
| 用户粘贴 / 上传 / 指定的 | ✅ 他在担保出处。URL 记他给的 |
| 在用户机器上 `kb fetch --url <发布机构原址>` 直接取回 | ✅ 字节直接来自发布机构 |
| GitHub / 镜像 / 博客上的"全文" | ❌ L5。没有保管链，借第三方洗了一道 |
| 你记得的、你"忠实复述"的 | ❌ 一个字都不行 |

拿不到原文时，**闸关着就是正确状态**。零产出是诚实的；
一条伪造证据撑起来的 verified 比零产出坏得多。

## 1. 落地（在 ashare-kb/ 下）

```bash
./kb fetch --list                      # 快照名 ↔ 断言 id
```

- 用户粘贴的文本：**原样**写到 scratchpad 里的一个文件（不是 sources/ —— hook 会挡）。
  不改字、不补漏、不排版。
- 然后：

```bash
./kb fetch <快照名> --from-file <那个文件> --url <用户给的原址>
./kb source <id> --tier 1 --src sources/<快照名>
./kb verify <id>
```

`fetch` / `source` / `verify` 每一步 hook 都会请用户确认。这是故意的：
来源的担保人是他，不是你。

## 2. 读结果

- **HOLDS** → verified +1。接着跑 `./kb doctor --offline` 和
  `python3 .claude/hooks/gate.py status`，把 `ledger/`、`sources/`、`digest/` 一起提交。
- **退 2，缺短语** → 打开快照看原文实际怎么写。
  - 措辞是猜的（ROADMAP 预测三）→ 改短语的**找法**可以。
  - 少了一个**成分**（预测二：`1+N` 可能不在国务院原文里）→ 不是脚本的问题，是断言的问题：
    拆成两条，或 `kb falsify` 旧的 + `kb lead` 新的。
  - **永远不要为了通过而放宽脚本或删掉成分。**
  - 改 `verify/*.py` 会触发闸的确认 —— 让用户看见，那是对的。
- **快照 < 200 字** → 抽错了（扫描版 PDF？导航页？），不是短语问题。

## 3. 汇报

只报一个数：`verified: N`（之前是几）。不报测试数、不报行数。
