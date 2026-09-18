# ROADMAP —— 从 0 条 verified 到循环跑起来

**这个文件由人手动更新，`kb` 不管它。** 做完一步就把方框划掉。

当前状态见 `digest/latest.md` 顶部那一行。

---

## 阶段 0 · 落地

- [ ] 合并 PR，克隆到自己机器
- [ ] `./kb init` —— 从 `ledger/events.jsonl` 重放，应看到 10 条
- [ ] `./kb doctor --offline` —— 预期 `12 通过，2 警告，0 失败`

**任何 FAIL 都不要往下走。** 那说明库结构有问题，不是环境问题。

## 阶段 1 · 数据源

- [ ] `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- [ ] `.venv/bin/python -m kb_cli doctor`

用 venv 不是讲究：Debian/Ubuntu 系统 Python 上 `jsonpath` 的构建会挂在
打过补丁的 setuptools 上。

| doctor 的结果 | 含义 | 怎么办 |
|---|---|---|
| 全 OK | 通了 | 去阶段 2 |
| `FAIL 行情接口 —— 列名认不出` | akshare 改了列名 | 打印 `df.columns`，改 `verify/ashare_data.py` 里 `_extract_closes` 的候选名 |
| `WARN 取数失败` | 网络或限流 | 单独跑一次 `ak.stock_zh_a_hist` 看真实报错 |

## 阶段 2 · 第一条 verified 走制度层，别走结构层

**理由：制度层的验证循环是 10 秒，结构层是 2 小时。**
现在要调的是循环本身，不是数据管道。拿 2 小时的反馈周期去调 10 秒能调完的
东西，是最容易让人放弃的排法。

三条制度层断言的脚本都已写好并绑定，各自在等自己的快照。
**存全文，不存摘要** —— 摘要是你的转述，转述就降级成 L4 了。

```bash
./kb fetch --list                          # 还缺哪些、各给哪条断言
./kb fetch <名字> --url <原址>              # 抽文 + 记来源(sha256)
./kb fetch <名字> --from-file <下载的文件> --url <原址>   # PDF / 门户后面的
```

URL 要你自己找 —— 我不确定这四份文件的确切地址，写一个会 404 的链接
比不写更糟：它看起来像是验证过的。

- [ ] `sources/gov-2024-04-12-guojiutiao.txt` → `./kb source inst-69d8655b --src ...`
      → `./kb verify inst-69d8655b`
- [ ] `sources/sse-kechuangban-shidangxing.txt` → `inst-625f832d`
- [ ] `sources/sse-jiaoyi-guize.txt` + `sources/sse-rongzirongquan-xize.txt`
      → `inst-623b43f8`（这条要两份，见下）

### 预测一：已经作废

原来押注"第一次会退 2，因为 `2024年4月12日` 匹配不上（原文写中文数字）"。

**这条预测在代码层面被拆掉了**，不是被证伪的。`kv.date_variants()` 现在
同时接受阿拉伯数字、补零、中文数字和 ISO 四种写法，`normalize()` 还会消掉
PDF 换行和全角差异。所以它不再是一条有效预测 —— 留着会让人误以为
这个风险还在。

### 预测二：`1+N` 大概率不在国务院原文里

`inst-69d8655b` 三个成分里，标题和日期几乎必然命中，**"1+N" 未必**。
"1+N 政策体系"更像是证监会后续文件和官方解读里的提法，不一定出现在
国务院那份《若干意见》的正文中。

如果退 2 且只缺 `1+N`：**这不是脚本的问题，是断言的问题。**
说明这条断言里有一半的来源根本不是国务院原文。正确的处理不是放宽脚本，
是二选一：

- 把 "1+N" 那半拆成单独一条断言，配证监会文件的快照；或者
- 改断言只保留原文支持得住的部分，`kb falsify` 旧的、`kb lead` 新的

**不要为了让它通过而删掉 `1+N` 那一组短语。** 那是让脚本比断言宽松，
库会说 HOLDS，而实际支持的是一条更弱的断言。

### 预测三：`inst-623b43f8` 的措辞是猜的

T+1 那几组候选短语是照常见写法写的，交易所规则的实际措辞未必是其中任何一种。
退 2 之后打开快照照抄实际写法即可 —— **改短语是对的，改 `if_wrong` 不是**：
断言没变，只是找它的方式变了。

另外这条断言本身是复合的（T+1 约束 + 融券还券路径），没有任何一份原文会把
两件事写成一句话。脚本只核对两份原文里各自的规则成分都还在，说 HOLDS 的意思是
"规则层面这条路仍然通"。觉得这个口径太松，就把断言拆成两条分别验证 ——
而不是让脚本假装验证了一个它其实是推出来的结论。

## 阶段 3 · 结构层，先跑小的那个

先跑 `strc-1bff2efa`（2026H1 单区间，已封闭），**不要**先跑
`strc-6045eb4e`（4 个季度 ≈ 4 倍时间）。

- [ ] `./kb source strc-1bff2efa --tier 2 --src "akshare 自算，见 verify/strc-1bff2efa.py"`
- [ ] `.venv/bin/python -m kb_cli verify strc-1bff2efa`

第一次一到两小时，逐只缓存在 `.cache/`，中断可续。
跑完之后 `strc-6045eb4e` 能复用大部分缓存。

- [ ] `strc-6045eb4e` 中位数 vs 中证全指，4 个季度

**三种结果，最有价值的是第二种：**

- **HOLDS** → 第一条结构层 verified
- **FALSIFIED** → 中位数偏离超过 1 个百分点。一条被广泛转述的数字被自己的
  数据打脸了。去 `ledger/falsified/strc-1bff2efa.md` 把「教训」那节写了 ——
  不是写"这个数字错了"，是写"我当初凭什么相信一条没有原始出处的 Wind 转述"
- **INCONCLUSIVE** → 看哪一步断的；退 2 永远不会伤到库

## 阶段 4 · 把循环用起来

每次开会话：把 `digest/latest.md` 贴给 Claude。
讨论中 Claude 给判断 → `kb lead` 记下、标 tier。
会话末 `kb stale`。digest 自动刷新，不用管。
每隔一阵 `./kb doctor`。

---

## 现实预期

那三条 L5 —— 散户亏损占比 79-82%、普跌天数 28 vs 4、散户贡献 60-70% 成交量
—— **大概率永远到不了 verified**，因为原始统计根本不公开。它们会一直躺在
lead 里，这是正确的：库在诚实地告诉你，那些数字你其实并不知道。

半年后 verified 到 5 条就已经不错。

**如果半年后 `ledger/falsified/` 还是空的，要怀疑的不是命中率，
是 `if_wrong` 写得太软。** 一条从来不可能被推翻的断言，和一条感想没有区别。
