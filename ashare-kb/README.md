# ashare-kb

> 学习的载体是库，不是模型。模型是消费者和贡献者。

每个会话的 Claude 不携带上个会话的任何东西。做不到"让 Claude 不断学习"，
能做到的是：**建一个知识库，让每次会话的 Claude 被它 prime。**

这个区别决定了整个设计。如果目标是"让模型变聪明"，你会去存"理解"；
如果目标是"让库变可靠"，你会去存**可验证的断言**。只有后者可能不腐烂。

## 存断言，不存理解

"理解"不可验证，三个月后会退化成叙事。**断言可以被数据打脸。**

所以每条记录必须带 `if_wrong`：什么观测能推翻它。写不出 `if_wrong`
的东西不是断言，是感想，数据库会直接拒收。

## 三层，只有两层进库

| 层 | 内容 | 衰减 | 处理 |
|---|---|---|---|
| **制度层** `institutional` | T+1、涨跌停、融券门槛、退市/减持规则、注册制、新国九条 | 年级 | ✅ 积累，不自动衰减 |
| **结构层** `structural` | 投资者结构、中位数vs指数背离、右偏分布、供给扩张 | 季度 | ⚠️ 默认 90 天后降级为 stale，逼你重算 |
| **状态层** | 成交额、两融、估值分位、当前风格 | 日/周 | ❌ **不进库** —— `layer` 的 CHECK 直接挡在门外 |

多数"市场研究知识库"死于把状态层存了下来，半年后当知识用。
这里没有 state 这个取值，所以那条死路是走不通的。

## 来源分级 —— 整个系统的命门

| 级别 | 来源 | 能做什么 |
|---|---|---|
| L1 | 法规原文、证监会/交易所公告、上市公司公告、中证指数官方统计 | 可 verified |
| L2 | Wind/Choice/同花顺原始数据、自己算的 | 可 verified |
| L3 | 券商研报（署名+方法论） | 可 verified，须记录方法 |
| L4 | 财经媒体 | **只能是线索** |
| L5 | 自媒体、论坛、转述 | **只能是线索** |

**硬规则：L4/L5 永远不能让一条断言进入 verified。必须先回溯到 L1-L3。**

由数据库触发器执行，INSERT 和 UPDATE 两条路都堵死了 —— 少了 UPDATE 那条，
先写 lead 再改状态就能绕过去，分级形同虚设。

## 装上就能跑

```bash
./kb init          # 建库建目录；库为空时自动从账本重放
python3 seed.py    # 灌入种子断言（仅首次；全部为 lead）
./kb digest        # 生成 digest/latest.md
```

## 核心循环

```bash
# 1. 记线索 —— 状态恒为 lead，verified 不能靠写入取得
./kb lead "个人投资者贡献A股60%-70%的成交量" \
    --layer structural --tier 5 \
    --src "转述（L5）" \
    --if-wrong "交易所年鉴原始口径的数值落在该区间外"

# 2. 回溯 —— 整套系统里最重要的一个动作
./kb source strc-032b693f --tier 1 --src sources/sse-2025-tongji-nianjian.pdf

# 3. 验证 —— 只有脚本能把断言变成 verified
./kb verify strc-032b693f --script verify/strc-032b693f.py

# 4. 淘汰 —— 会话末尾跑
./kb stale

# 5. 重新生成下次会话的 prime 材料
./kb digest
```

其余命令：`falsify`（制度变了，手动打脸）、`list`、`show`、`rebuild`。

没有 cron，没有 daemon —— 机器晚上睡觉，全部手动触发。

## 三条刻意设计的硬规则

**1. verified 只能由脚本挣到。** 没有 `--manual`，没有"我读过原文了"。
人工确认是这套系统唯一可能的后门，留着它，三个月后库里就会堆满
谁也说不清凭什么的 verified 条目。L1 断言的脚本形态是核对 `sources/`
下的原文快照里有没有那几个关键短语 —— 可复核，而不是可声称。

**2. "脚本坏了" ≠ "断言错了"。** 验证脚本必须显式声明结论
（`HOLDS:` / `FALSIFIED:` 行 + 对应退出码），只看退出码不行：
Python 未捕获异常的退出码就是 1，会被读成"断言被数据打脸"，
库会自动写一块墓碑、记下一条根本不存在的教训。详见 `verify/README.md`。

**3. falsified 不删除。** 保留在库里（`status='falsified'`），
同时在 `ledger/falsified/<id>.md` 留一份人读的墓碑。
断言错了不是教训，**"我当初凭什么相信它"才是** —— 墓碑里那一节要手写。

## 每次会话

1. Claude 读 `digest/latest.md` 被 prime（契约在最前面，证据在后面）
2. 讨论中 Claude 给出任何判断 → `kb lead` 记下，标 tier
3. 会话末 `kb stale` 检查衰减，`kb digest` 重新生成
4. **Claude 的输出与已有 verified 断言冲突时，以库为准，Claude 是错的那个**

第 4 条是关键。这个库的定位是 adversary，不是模型的备忘录。

## 目录

```
ashare-kb/
├── kb                  # 命令行（bash shim）
├── kb_cli/             # 实现
├── schema.sql          # 表 + 质量门触发器
├── seed.py             # 种子断言
├── kb.sqlite           # 派生物，.gitignore 掉了
├── ledger/
│   ├── events.jsonl    # append-only，真正进 git 的状态；kb rebuild 的数据源
│   └── falsified/      # 墓碑，一条一个文件
├── sources/            # L1/L3 原文快照 —— 证据是快照不是链接
├── verify/             # 验证脚本，一条断言一个
├── digest/             # 每次会话的 prime 材料
└── tests/
```

`kb.sqlite` 不进 git：二进制文件不可 diff、不可 merge。
`ledger/events.jsonl` 进 git，`./kb rebuild` 能从它完整重建数据库。

## 它会怎么失败

**最可能的死法：变成一个只增不减的笔记堆。** 防线是 `kb stale`
和 L4/L5 的触发器。如果三个月后库里 verified 不到 20 条、lead 有 300 条，
那不是失败 —— 那是系统在正确工作，它在诚实地告诉你，关于 A 股，
能被硬证据支撑的东西本来就不多。

**第二个死法：用它度量"我读了多少"。**
health metrics measure whether the component ran, not whether it produced
valid output。这个库唯一有意义的指标是 **verified 条目数**，不是总条目数。

**第三个死法：`kb stale` 开始误报，于是你开始无视它。**
已封闭区间的历史测算（"2026H1 中位数 -14.99%"）不会腐烂，
给它 `--stale-after never`。会腐烂的是"长期""通常""目前"这类结论。
误报一多，淘汰机制就废了 —— 而淘汰机制是这个库不变成笔记堆的唯一原因。

## 测试

```bash
pytest tests/ -q
```

49 个用例，重点全在质量门上：L4/L5 能不能从 INSERT 绕、能不能从 UPDATE 绕、
能不能先挣到 verified 再把 tier 改高、空白字符串能不能冒充"有值"、
崩溃的验证脚本会不会误写墓碑、第 90 天会不会被提前判成过期。
门漏了，这个库就只是个笔记堆，而且是一个看起来很权威的笔记堆 —— 比没有更糟。
