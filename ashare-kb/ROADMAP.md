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

- [ ] 取国九条全文存成 `sources/gov-2024-04-12-guojiutiao.txt`
      （存**全文**，不存摘要 —— 摘要是转述，转述就降级成 L4 了）
- [ ] `./kb source inst-69d8655b --src sources/gov-2024-04-12-guojiutiao.txt`
- [ ] `./kb verify inst-69d8655b`

### 一条可证伪的预测

**预测：第一次会退 2（不确定），原因是 `2024年4月12日` 这个短语匹配不上。**

国务院文件正文里日期常写成"二〇二四年四月十二日"，或者印发日期根本不在
正文而在文末落款/文号里。

这条预测本身是可证伪的 —— 如果第一次就退 0，说明预测错了，把这行改掉别留着。
留着一条从没被检验的预测，和留着一条感想没有区别。

**看到退 2 之后**：打开快照找原文实际写法，改 `verify/inst-69d8655b.py`
里的 `PHRASES`，重跑。

这一步真正的产出**不是多一条 verified，是搞清楚 L1 断言的短语该怎么挑。**
搞清楚了，剩下两条制度层断言各自 10 行脚本就能复制：

- [ ] `inst-623b43f8` T+1 与融券变相 T+0（上交所/深交所交易规则）
- [ ] `inst-625f832d` 科创板 50万+24个月门槛（上交所适当性规定）

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
