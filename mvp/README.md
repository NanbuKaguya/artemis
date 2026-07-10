# 抖音电商 Agent 系统 · MVP（P1：选品 + 内容 Copilot）

一个**已跑通的** AI 电商选品与内容助手：自动发现候选品 → 七维评分 → 独立复核 → 生成标题/卖点/详情/脚本（过合规闸）→ 出日报 + 人工闸门。

> 本目录是《[抖音电商Agent系统架构.md](../抖音电商Agent系统架构.md)》第八部分 P1 阶段的可运行实现。
> 想继续升级？给 AI 编码代理看的规格在仓库根目录 [`AGENTS.md`](../AGENTS.md)。

## 快速开始（无需任何 API Key）

```bash
cd mvp
python3 run_demo.py            # 端到端跑一遍，输出选品日报
python3 tests/test_core.py     # 核心引擎测试 9/9
```

无 Key 时 LLM 自动回退为确定性模板，demo 仍完整可跑。要启用真实生成/推送：

```bash
cp .env.example .env           # 填 ANTHROPIC_API_KEY / FEISHU_WEBHOOK 等
```

## 它做了什么

| 步骤 | 模块 | 自动化 |
|---|---|---|
| ① 爆品发现（硬门槛过滤） | `agents/hunter.py` | 全自动 |
| ② 七维评分（确定性引擎） | `scoring.py`+`margin.py`+`agents/scorer.py` | 全自动 |
| ③ Critic 独立复核（反幻觉） | `agents/critic.py` | 全自动 |
| ④ 终选 | 人工闸门 | **人** |
| ⑤ 内容生成（过合规闸） | `agents/copywriter.py`+`compliance.py` | 全自动生成 |
| ⑥ 内容复核 + 日报 + 闸门 | `agents/critic.py`+`notify.py` | 全自动 |

## 设计红线（详见 AGENTS.md §1）

- **金额/评分走代码，不走 LLM**（防幻觉）。
- **合规硬闸只拦不放行**；发布/花钱/合规留人工。
- **数据闭环校准权重**（`memory.py`）——越用越准。
