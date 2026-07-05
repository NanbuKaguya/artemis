# 本地 Claude Code 量化研究环境配置清单

> 目标：把 Mac 本地 Claude Code 配成「AI 量化分析与研究」的高效工作台。
> 核心思路：**数据走 API、计算走 Python、MCP 只补浏览器和批量抓取的短板。**

## 一、MCP 配置（精简到 2 个 + 1 个按需）

### 1. Playwright MCP（必装）

用途：Agent 系统的 E2E 测试；兜底抓取无 API 的登录站点。

```bash
claude mcp add playwright -- npx -y @playwright/mcp@latest
```

### 2. Firecrawl MCP（值得装）

用途：批量抓取研报、公告、财经长文并结构化载入对话。
需先到 firecrawl.dev 注册获取 API Key。

```bash
claude mcp add firecrawl -e FIRECRAWL_API_KEY=你的key -- npx -y firecrawl-mcp
```

### 3. Chrome 集成（按需）

仅当你频繁需要读取**已登录**的行情终端网页版（Wind、Choice、同花顺、
东方财富等）时启用。这是 Claude Code 的内置浏览器集成能力，在设置中
开启即可，无需单独安装 MCP server。

> 不装：Perplexity（与内置 WebSearch 重叠）、Glyph（与量化/开发无关）。
> 理由见 [`docs/mcp-evaluation.md`](./mcp-evaluation.md)。

## 二、量化数据 API（比任何 MCP 都重要）

按市场覆盖选择，全部通过 Bash 调 Python 使用：

| 库 | 覆盖范围 | 特点 |
|---|---|---|
| **akshare** | A 股/港股/期货/基金/宏观 | 免费、无需 token、接口最全，首选 |
| **tushare** | A 股为主 | 数据质量高，需注册积分，适合正式研究 |
| **baostock** | A 股历史行情 | 免费稳定，适合长周期回测数据 |
| **yfinance** | 美股/全球指数/外汇 | 免费，海外资产首选 |
| **ccxt** | 加密货币（100+ 交易所） | 统一接口，支持实盘下单 |

```bash
pip install akshare tushare baostock yfinance ccxt
```

## 三、Python 计算环境

```bash
# 建议用独立虚拟环境
python3 -m venv ~/quant-env && source ~/quant-env/bin/activate

# 数据处理与统计
pip install pandas numpy scipy statsmodels pyarrow

# 回测框架（按偏好选一个为主）
pip install vectorbt        # 向量化回测，快，适合因子批量筛选
pip install backtrader      # 事件驱动，适合策略逻辑精细模拟

# 因子与绩效分析
pip install alphalens-reloaded pyfolio-reloaded empyrical-reloaded

# 机器学习（AI 量化）
pip install scikit-learn lightgbm

# 可视化
pip install matplotlib plotly
```

可选进阶：微软 **qlib**（AI 量化全流程平台，含因子库/模型/回测），
适合系统化的 ML 选股研究：`pip install pyqlib`。

## 四、项目级配置建议（CLAUDE.md）

在量化项目根目录放 `CLAUDE.md`，让 Claude Code 每次会话自动遵守约定，
例如：

```markdown
# 量化研究约定
- 数据一律通过 akshare/tushare API 获取，禁止爬网页取行情
- 所有回测必须报告：年化收益、最大回撤、夏普、换手率
- 数据缓存到 data/ 目录（parquet 格式），避免重复请求
- 回测区间默认 2018 年至今，须包含 2018 熊市与 2020 疫情段
- 严禁未来函数：因子计算只能用 T 日及之前的数据
```

## 五、专用金融 MCP（可选探索)

若后续希望 Claude 不写代码直接查行情，可在 MCP registry 中搜索
金融数据类 server（如 yfinance-mcp、各交易所行情 MCP 等）。
选择标准：

1. 数据源是否有官方 API 背书（而非爬虫套壳）；
2. 是否只读（涉及下单的 MCP 谨慎接入，实盘交易建议保留人工确认）；
3. 维护活跃度。

## 六、典型工作流

```
研究想法
  → Claude 用 akshare 拉数据（Bash + Python）
  → 因子构建与检验（vectorbt / alphalens）
  → 回测与绩效归因（backtrader / pyfolio）
  → 需要研报/新闻佐证时用 Firecrawl 批量抓取
  → 结论写入 research/ 目录，数据缓存 parquet
```
