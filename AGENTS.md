# AGENTS.md — 交接给本地 Codex 的升级规格书

> 这份文件是**给 AI 编码代理（本地 Codex）读的**。你（Codex）接手本仓库后，先读完本文件，再动代码。
> 目标：把当前"可运行的 P1 地基"升级为《架构蓝图》描述的**世界顶级、可盈利的抖音电商 Agent 操作系统**。
> 人类看的说明在 `mvp/README.md`；完整战略设计在 `抖音电商Agent系统架构.md`。

---

## 0. 你现在拿到了什么（30 秒建立心智模型）

一个**已经端到端跑通**的抖音电商「选品 + 内容」Copilot（蓝图第八部分的 P1 阶段）：

```
mvp/
├── run_demo.py              # 端到端入口：python3 run_demo.py（无需任何 Key 即可跑）
├── src/
│   ├── models.py            # 数据模型（dataclass，零依赖）
│   ├── margin.py            # 利润引擎（确定性代码，绝不用 LLM 算钱）★
│   ├── scoring.py           # 七维选品评分引擎（确定性、可校准）★
│   ├── compliance.py        # 合规硬闸（极限词/资质，只拦不放行）★
│   ├── memory.py            # 权重校准+经验沉淀（系统"越用越准"的护城河）
│   ├── llm.py               # LLM 多模型路由 + 离线回退
│   ├── notify.py            # 飞书/企微推送 + 人工闸门
│   ├── orchestrator.py      # 纯 Python 编排（现在跑的就是它）
│   ├── graph.py             # 生产编排：LangGraph 有状态图（带 HITL/检查点）★
│   └── agents/
│       ├── hunter.py        # ① 爆品发现（硬门槛过滤）
│       ├── scorer.py        # ② 选品评分（调用 margin+scoring+LLM理由）
│       ├── copywriter.py    # ③ 内容文案（过合规闸）
│       └── critic.py        # 质检评审（独立反幻觉复核）
├── data/mock_products.json  # 8 个仿真商品（覆盖爆品/红海/负毛利/衰退/违规 各路径）
└── tests/test_core.py       # 确定性引擎测试（9 个，全绿）
```

**验证它是活的**：
```bash
cd mvp
python3 run_demo.py          # 看到 Top 榜 + 合规拦截 + 人工闸门
python3 tests/test_core.py   # 9/9 通过
```

---

## 1. 不可违背的设计信条（升级时永远保留，违反=架构退化）

这三条是系统的**灵魂**，任何升级都不能破坏。写新代码前用它们自检：

1. **能力全自动，风险全人工。**
   AI 干完 90% 的脑力活和物料活；但**花钱（投放/囤货）、发布（对外承诺）、合规（资质/广告法）** 三类动作必须留人工闸门。
   → 你新增任何"自动执行对外动作"的功能时，**必须挂在 `notify.request_human_gate` 之后**，不能绕过。

2. **一切数值走代码，一切产出过 Critic。**
   利润、ROI、评分**永远在 `margin.py`/`scoring.py` 里用确定性代码算，绝不交给 LLM 心算**（防幻觉第一红线）。
   LLM 只做：取数、归纳、生成文本、解释理由。
   → 你若让 LLM 输出了一个"数字"，停下来，把它改成代码计算。

3. **数据闭环是唯一护城河。**
   选品打分 → 实盘验证 → 权重校准（`memory.calibrate_weights`）→ 特征沉淀。
   → 你做的每个新 Agent，都要想"它的产出如何回流校准"，否则就是静态工具。

**同样重要——永远不要做的事（做了会封店/亏钱/违法）：**
- ❌ 用 Playwright/RPA **模拟点击批量刷抖店后台**做写操作。写操作**只走抖店开放平台官方 API**，无 API 的做成"人工一键"半自动。
- ❌ 让 Agent **自动加大投放预算"救场"**。亏损时熔断只能"暂停"，加码永远人工。
- ❌ 违规爬取 / 抓个人隐私数据。数据优先用**付费合规第三方 API + 自有店铺官方 API**。
- ❌ 让 LLM 的语义判断**放行**合规——合规是"词库/规则硬匹配拦截在前"，LLM 只能"补充发现问题"，不能"批准通过"。

---

## 2. 代码约定（照着现有风格写，别引入新范式）

- **语言/风格**：Python 3.11+，`from __future__ import annotations`，类型注解齐全，中文注释解释"为什么"。
- **零依赖优先**：核心引擎（margin/scoring/compliance/models）**不引入第三方库**，保证离线可测。重依赖（langgraph/anthropic/pg）只在生产路径按需 import，且 import 失败不能拖垮离线 demo。
- **确定性与随机分离**：能写成纯函数、可单测的逻辑，绝不塞进 LLM prompt。
- **每个 Agent 遵循七元组**：职责/输入/思考/工具/输出/验证/协作（见蓝图第三部分），文件顶部 docstring 写清楚。
- **产出必带 schema**：新增产出用 `models.py` 里的 dataclass，Critic 能据此校验。
- **测试先行**：新增确定性逻辑，先在 `tests/test_core.py` 加断言（可直接 `python3 tests/test_core.py` 跑，不依赖 pytest）。
- **提交粒度**：一个 Agent / 一个引擎一个 commit，信息说清"为什么"。

---

## 3. 升级 backlog（按优先级，从这里开始往下建）

> 每项都标了 **[验收标准]**。做完一项，跑 `run_demo.py` + 测试确认不回归，再做下一项。

### P1 收尾（把地基坐实）
- [ ] **接真实 LLM**：在 `llm.py` 取消注释启用 Anthropic/通义路由；`reasoning` 走强模型、`bulk` 走性价比模型。[验收] 有 Key 时 scorer 理由/copywriter 文案为真实生成且仍过合规闸。
- [ ] **结构化内容输出**：`copywriter._llm_pack` 改用函数调用/JSON 模式，解析出 titles/points/detail/script 分字段（现在 LLM 结果整段塞进 detail）。[验收] 合规闸能逐字段检查。
- [ ] **飞书可交互卡片**：`notify` 增加"通过/驳回"按钮回调（需一个轻量 Web 服务接 webhook）。[验收] 人在飞书点按钮即可回写终选结果。

### P2（决策级选品 + 半自动上架 + 监控，蓝图 8.2）
- [ ] **数据源接入层** `src/datasources/`：封装蝉妈妈/飞瓜（付费 API）+ 巨量算数 + 抖店开放平台（自有店铺）。统一映射到 `models.Product`。**限频、缓存、去重、带时间戳**。[验收] `hunter` 从真实源取数替换 mock，可回退 mock。
- [ ] **评论洞察 Agent** `agents/voc.py`：抓竞品评论→情感/主题聚类→输出痛点/卖点缺口，喂给 scorer 的 content 维度与 copywriter。[验收] copywriter 卖点来自真实差评而非模板。
- [ ] **竞争分析 Agent** `agents/competition.py`：把 `scoring._competition_score` 升级为独立 Agent，产出价格带机会图。[验收] 蓝海判定有价格带空隙依据。
- [ ] **供应链评估 Agent** `agents/supply.py`：1688 开放平台 API 比价 + 稳定性评分，标记"需人工验样/签约"。[验收] 输出必带人工事项清单。
- [ ] **半自动上架** `agents/listing.py` + `src/doudian/`：组装商品草稿 → 抖店开放平台**商品 API 写草稿态** → `request_human_gate("发布")`。[验收] 只到草稿，发布必须人点。**严禁 RPA 刷后台。**
- [ ] **监控 Agent** `agents/monitor.py`：接自有店铺罗盘/千川，盯 GMV/转化/退款/ROI，阈值熔断+飞书预警。[验收] 退款率超阈值自动"暂停"提醒（绝不自动加投）。
- [ ] **切到 LangGraph**：`run_demo` 生产路径改用 `graph.py`（检查点/HITL/条件路由）。[验收] 人工闸门用 `interrupt` 真实挂起，可 resume。

### P3（闭环校准 + 优化，走向"AI 运营员工"，蓝图 8.3）
- [ ] **实盘回流** `agents/diagnose.py` + 定时任务：把上架品的真实成败写回 `memory.record_outcome`。[验收] `memory.calibrate_weights` 在 ≥10 样本后自动调权。
- [ ] **归因诊断 Agent**：掉量/亏损时定位（流量/转化/履约），给根因链。
- [ ] **策略优化 Agent** `agents/optimizer.py`：出调价/调品/调投放建议，**花钱建议进人工闸**。
- [ ] **A/B 实验框架** `src/experiment.py`：内容/主图/价格多版本自动测、自动读结论、回流 memory。
- [ ] **爆品特征库**：把 `memory.winning_features` 升级为向量库检索，选品时优先匹配历史成功特征。

### 横切（任何阶段都可做）
- [ ] **可观测**：全链路 audit log（哪个 Agent 因何数据做了何决策）+ 成本监控。
- [ ] **合规词库外置**：`compliance.py` 的词库改为可热更新的外部文件 + 定期同步。
- [ ] **多店/多品并行**：orchestrator 支持批量并行管理 N 个品/店（这是人效 5-10 倍的关键）。

---

## 4. 你接手时的建议动作顺序

1. 跑 `python3 mvp/run_demo.py` 和 `python3 mvp/tests/test_core.py`，确认地基是活的。
2. 通读 `抖音电商Agent系统架构.md`（战略）+ 本文件（工程规格）。
3. 从 **P1 收尾** 第一项开始，逐项按 backlog 推进，每项做完跑 demo+测试防回归。
4. 每加一个 Agent，回到 §1 三信条自检；每写一个数字，回到"走代码不走 LLM"自检。
5. 有架构级分歧（如是否做无货源、是否自建投放）时，**这属于人类战略决策**，不要自行决定——在 commit/PR 里标注出来等人拍板。

---

## 5. 一句话交接

> 你拿到的是一台**已经点火、能自己跑一圈的发动机**（P1 选品+内容 Copilot）。
> 你的工作不是重造，而是**沿着 §3 backlog 往上叠**，把它从"选品助手"升级为"AI 电商运营员工"，
> 全程守住 §1 的三条信条和四条红线。**能力尽管自动化，风险务必留给人。**
