# Artemis — A 股 AI 量化投资工作系统

> 一个把"少亏钱"放在"多赚钱"前面的个人量化系统。

## 为什么是这个顺序

亏 50% 需要赚 100% 才回本。对个人投资者而言，控制左尾的边际收益远高于
提升右尾 —— 而且前者主要靠纪律和规则，后者要跟全市场最聪明的钱竞争。

这个系统的每一层都是按"能挡住多少亏损"排序的，不是按"能贡献多少收益"：

```
L7  复盘与纪律     ← 管住你自己（对散户，这一层往往贡献最大）
L6  风控           ← 止损、回撤熔断、拥挤度监控
L5  执行           ← T+1 / 涨跌停 / 停牌 / 真实成本
L4  组合构建       ← 分散度、行业约束、缓冲带降换手
L3  选股 alpha     ← 因子（唯一需要"比别人聪明"的一层，放在最后）
L2  择时           ← 市场状态 → 总仓位
L1  排雷           ← ST / 退市 / 流动性 / 财务地雷
L0  数据           ← point-in-time、防未来函数
```

**注意 L3 的位置。** 大多数人从这一层开始，也止步于这一层 —— 这是散户量化
最常见的失败路径。

## 快速开始

```bash
pip install -r requirements.txt

# 1. 跑通全流程（用内置合成市场，无需任何数据源）
python scripts/run_pipeline.py

# 2. 策略上线评审 —— 五道闸门
python scripts/validate_strategy.py

# 3. 盘前清单 / 盘后复盘
python scripts/premarket.py
python scripts/postmarket.py

# 4. 因子挖掘流水线（接真实数据后的主战场）
python scripts/demo_pit_impact.py    # 看清 PIT 错误的代价
python scripts/mine_factors.py       # 挖掘 + FDR 筛选 + 多重检验惩罚

# 5. 回归测试（摩擦 + PIT 正确性）
python -m pytest tests/ -q
```

接真实数据（在你本机）：

**第一件事是体检，不是回测。** 缺列造成的失效是静默的：
排雷规则会返回"剔除 0%"、中性化会返回一条正常序列，都不报错。

```python
from artemis.data.preflight import report, assert_ready
print(report(bars))          # 每项能力是活的、残的、还是死的
assert_ready(bars)           # 硬闸门：关键能力失效直接抛错
```

```python
from artemis.data.akshare_source import AkshareSource, doctor
print(doctor())              # 先体检：当前 akshare 版本有哪些能力可用

src = AkshareSource()
codes = src.stock_list()["code"].tolist()
bars = src.daily_bars(codes[:100], "2018-01-01", "2026-08-01")

from artemis.data.store import BarStore
BarStore("./data_cache").write(bars)
```

## 模块地图

| 模块 | 作用 | 关键点 |
|---|---|---|
| `artemis/rules.py` | A 股"物理定律" | 分板块涨跌停、最小交易单位、完整成本模型 |
| `artemis/config.py` | 风险参数中枢 | 默认值一律保守；`turnover_budget()` 算换手预算 |
| `artemis/data/` | 数据契约与缓存 | 合成市场用于测试，AkShare 适配器用于实盘 |
| `artemis/guard/` | 排雷层 | 每条规则可用 `audit()` 度量价值 |
| `artemis/regime/` | 择时层 | 多信号投票 → 目标总仓位 |
| `artemis/alpha/` | 因子库与评估 | 因子必须写清经济逻辑才允许注册 |
| `artemis/alpha/mining.py` | 因子挖掘 | FDR + HLZ 门槛 + 冗余检验，专治"挖掘=多重检验" |
| `artemis/alpha/research_log.py` | 研究日志 | 自动记录每次试验，按公式指纹去重 |
| `artemis/data/fundamentals.py` | 财务 PIT 引擎 | 公告日对齐、累计转单季、追溯调整 |
| `artemis/data/ingest.py` | 规模化落地 | 增量 + 并发限流 + 断点续传 |
| `artemis/data/preflight.py` | 数据体检 | 接真实数据第一件事：找出会静默失效的能力 |
| `artemis/data/level2.py` | L2 契约与聚合 | 逐笔→日频特征，处理沪深撤单编码不对称 |
| `artemis/data/qmt_source.py` | QMT 适配器 | 能力探测，无 L2 权限自动退回 L1 |
| `artemis/execution/cost.py` | 执行成本 | 挂单决策（含逆向选择）+ 滑点归因 |
| `artemis/portfolio/` | 组合构建 | 等权 + 硬约束 + 缓冲带 |
| `artemis/backtest/` | 带摩擦回测 | T+1、涨跌停、停牌、退市清算、真实成本 |
| `artemis/validate/` | 反过拟合 | 五道闸门：样本外/前推/随机对照/参数高原/PBO+DSR |
| `artemis/risk/` | 风控 | 止损、回撤熔断、冷却期 |
| `artemis/review/` | 复盘与纪律 | 事前承诺、收益归因、纪律评分 |
| `artemis/copilot/` | AI 研究助手 | 只做研究和质检，不做预测和下单 |

## 三条不可协商的规则

1. **回测引擎的摩擦不许调松。** `tests/test_frictions.py` 会拦住这类改动。
   任何让回测变好看的"简化"，都是在预支你的实盘亏损。

2. **五道闸门全过才允许上实盘。** `scripts/validate_strategy.py` 默认拒绝。
   你要拿证据说服它，不是它来讨好你。

3. **挖掘阶段的筛选不替代上线闸门。** 挖掘筛"因子有没有信息"，
   闸门筛"策略能不能赚钱"，用的是不同的证据，都得过。

4. **AI 不做交易员。** LLM 提假设、做排雷、做复盘、做魔鬼代言人；
   裁决权永远在数据和回测。

## 重要声明

本项目是**研究与工程框架**，不是投资建议，不构成任何收益承诺。
内置的因子只是示例，在真实市场中的表现需要你自己用真实数据验证。
量化投资有亏损风险，历史回测不代表未来收益。

自 2025 年 7 月 7 日起，沪深北交易所《程序化交易管理实施细则》施行，
使用程序化交易需向券商报告。高频认定标准为单账户每秒申报/撤单 300 笔以上，
或全日 20000 笔以上 —— 本系统的日频调仓远低于该门槛，但**报告义务仍需履行**。
