# RUNBOOK — 人类操作手册：如何安排本地 Codex 落实本方案

> 这份文件是**给你（人类项目主）看的**。Codex 的规格书在 `AGENTS.md`，战略蓝图在
> `抖音电商Agent系统架构.md`。本手册回答一个问题：**每天怎么派活、怎么验收、
> 你自己要做什么。**

---

## 第 0 步：一次性准备（约 15 分钟）

```bash
# 1. 把仓库拉到 Mac 本地
git clone https://github.com/NanbuKaguya/artemis.git && cd artemis

# 2. 确认地基是活的（Python 3.11+，零依赖）
cd mvp
python3 run_demo.py            # 应看到选品日报 + 合规拦截 + 人工闸门
python3 tests/test_core.py     # 9/9
python3 tests/test_p2.py       # 10/10

# 3. 在仓库根目录启动 Codex（它会自动读 AGENTS.md）
```

**基线不绿就不要开工**——任何一步失败先解决环境问题。

---

## 派活的核心原则（决定成败的三条）

1. **一次只派一个编号**。`TODO(Codex-1)` 到 `TODO(Codex-13)` 就是任务队列，
   一个编号 = 一次 Codex 会话 = 一个 commit。不要说"把 P2 都做了"——
   大任务会让它自由发挥，小任务让它精确填空。
2. **每次会话结束你只做两件事**：跑测试（三条命令全绿）+ 看 diff 的红线（见下方巡检表）。
   不用逐行读代码，红线没破、测试全绿就 merge。
3. **凭证永远你亲手放进 `.env`**，不要贴进对话里。Codex 缺凭证时必须保持
   mock/dry-run 回退，它若"造数据绕过"，直接打回。

---

## 给 Codex 的话术模板（直接复制粘贴）

**开工第一句（每次新会话都先说）：**

```
读 AGENTS.md，先跑 mvp/tests/test_core.py 和 mvp/tests/test_p2.py 确认基线全绿，
然后只做 TODO(Codex-N)，不要动其他任何 TODO。
做完跑两个测试文件 + run_demo.py 防回归，一个 commit，
commit message 说清楚做了什么、为什么这样做。
```

**它想越权时（比如想改契约、想跳过闸门）：**

```
停。这违反 AGENTS.md §1 的信条/红线。回到 TODO(Codex-N) 的 docstring 步骤，
只做填空。如果你认为契约本身有问题，把理由写在 commit message 里等我拍板，
不要自行修改。
```

**验收通过后：**

```
很好。更新 AGENTS.md §3 里对应条目为已完成 [x]，然后停下等我派下一个编号。
```

---

## 四周排期（对应蓝图第八部分，按你的节奏可伸缩）

| 周 | 派给 Codex 的任务 | 你要同步做的事（Codex 做不了）|
|---|---|---|
| **W1** P1收尾 | ① `llm.py` 接真实 LLM（reasoning/bulk 分层路由）② copywriter 结构化输出 ③ 飞书可交互卡片 | 申请 ANTHROPIC_API_KEY（或通义/DeepSeek）；建飞书群机器人拿 webhook，都放 `.env` |
| **W2** 数据源 | Codex-1→2→3（蝉妈妈）、Codex-4→5（1688 补齐） | **购买蝉妈妈 API 套餐**；1688 开放平台注册应用；把 token 放 `.env` |
| **W3** 抖店上架 | Codex-6→7→8（客户端）、Codex-9（listing 接真实 API） | **抖店开放平台注册自研应用 + 店铺授权**（需要你有抖店店铺）；验收时亲手在后台点一次"上架" |
| **W4** 监控+编排 | Codex-10→11（监控/熔断定时）、Codex-12→13（评论洞察）、切换 LangGraph | 定熔断阈值（退款率/ROI 底线是**经营决策**）；开始每天看飞书日报，把"采用/否决"的判断记下来——这是 P3 权重校准的原料 |

W4 之后进入 P3（实盘回流、归因、优化、A/B），届时让 Codex 按 AGENTS.md §3 P3 清单继续，
模式完全相同。

---

## 每次验收的巡检表（30 秒）

```bash
cd mvp && python3 tests/test_core.py && python3 tests/test_p2.py && python3 run_demo.py
```

然后 `git diff` 只盯这五条红线：

- [ ] `doudian/client.py` 里 `status == 1` 的断言还在（发布红线）
- [ ] 没有出现任何模拟点击/RPA 刷后台的代码（合规红线）
- [ ] 金额/评分没有交给 LLM 算（搜 diff 里有没有让 LLM 输出数字再解析使用）
- [ ] 新的对外动作（发消息/写 API/花钱）前面有 `request_human_gate`
- [ ] 外部请求都套了 `RateLimiter`，没有裸循环请求

五条全过 → merge。任何一条破了 → 整个 commit 打回重做，不要修修补补。

---

## 哪些决策永远是你的（Codex/Agent 无权代替）

| 决策 | 时点 |
|---|---|
| 买哪家数据 API、什么套餐 | W2 前 |
| 做哪个类目、风险偏好、单品测试预算 | 随时（写进日报目标）|
| 供应商选择/验样/签约/打款 | 每个品 |
| 商品**发布**（后台点上架） | 每个品 |
| 千川投放的每一笔预算 | 每个计划 |
| 熔断阈值、目标毛利率 | W4 定，之后按季调 |

---

## 常见坑（提前避开）

- **别让 Codex 一次重构多个文件**——契约（models/base/闸门）是系统的骨头，动骨头必须你先点头。
- **别跳过 dry-run 直接联调真实 API**——每个数据源先用 mock 测通逻辑，再换真 token，出错时才分得清是代码错还是接口错。
- **别把 `.env` 提交进 git**（`.gitignore` 已挡，但注意别 `git add -f`）。
- **测试变红先怀疑新代码，不是先改测试**——测试锚定的是红线，改测试=改红线=需要你拍板。
- **每周把 `data/memory.json` 备份一份**——那是系统"越用越准"的资产。
