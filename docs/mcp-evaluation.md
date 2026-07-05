# 本地 Claude Code 接入 MCP 的评估与决策记录

> 场景：Mac 本地部署的 Claude Code
> 主要用途：① AI Agent 工作系统架构设计与实施；② AI 量化投资分析与研究
> 评估日期：2026-07-05

## 一、评估对象

社区推荐的「5 大关键 MCP 服务器」：

1. **Perplexity MCP** —— 实时全网搜索
2. **Playwright MCP** —— 浏览器自动化（填表单、上传、测试 Web 应用）
3. **Firecrawl MCP** —— 抓取任意网站内容并加载到对话
4. **Glyph MCP** —— 连接数百个图像/视频生成模型
5. **Chrome MCP（内置）** —— 查看并操作本地 Chrome 中已打开的内容

## 二、评估基准线

Claude Code 本地版**已内置**以下能力，任何 MCP 都要先和它们比增量价值：

- `WebSearch`：实时联网搜索
- `WebFetch`：抓取并阅读单个网页
- `Bash` + 完整文件读写：可直接调用 Python 生态（数据 API、回测、建模）

**原则：MCP 不是越多越好。** 每接一个都占用工具上下文、扩大权限面、
增加 Agent 选工具时的决策噪音。同质工具（如两个浏览器控制器）堆在一起
会互相稀释。

## 三、逐项结论

| MCP | 对业务①（Agent 开发） | 对业务②（量化研究） | 结论 |
|---|---|---|---|
| Playwright | ✅ E2E 测试、验证浏览器工具链 | 🟡 兜底爬无 API 的登录站 | **必装** |
| Firecrawl | 🔸 用处不大 | ✅ 批量抓研报/公告/财经长文 | **值得装** |
| Chrome MCP | 🔸 用处不大 | 🟡 仅当频繁读已登录的行情终端网页版（Wind/Choice/同花顺等） | **按需** |
| Perplexity | 🔸 与内置 WebSearch 高度重叠 | 🔸 同左，边际收益低 | **可砍** |
| Glyph | ❌ 无关 | ❌ 无关 | **不装** |

### 关键取舍说明

**Chrome MCP vs Playwright（同质冲突）**
两者都是浏览器控制，分工是：

- Chrome MCP = 用**本人登录态**操作已打开的页面 → 人机协作、一次性操作
- Playwright = **无状态、可脚本化、可复现** → E2E 测试、CI、批量自动化

业务①的主线是开发和测试，Playwright 是正确选择；Chrome MCP 只在
业务②需要读认证态行情页面时才加，避免两个浏览器工具并存造成决策噪音。

**Perplexity 为什么砍**
它提供的「带引用的综合答案」，内置 WebSearch + WebFetch 组合已能覆盖
（搜索 → 抓原文 → 综合），重叠度最高、增量最低。

## 四、更重要的盲点：量化真正缺的不在这 5 个里

量化研究的命脉是**结构化数据源 + 计算环境**，而非网页抓取：

1. **数据获取**应走数据 API（akshare / tushare / yfinance / ccxt 等），
   通过 Bash 调 Python 获取——稳定、结构化、可复现。浏览器类 MCP 爬行情
   既脆又慢，只作为「无 API 数据源」的兜底。
2. **回测/因子/建模**用纯 Python + Bash 即可，不需要任何 MCP。
3. 若要为量化加 MCP，应找**专用金融数据类 MCP**，而非通用爬虫。

详见配套文档：[`docs/quant-claude-code-setup.md`](./quant-claude-code-setup.md)

## 五、最终决策

```
必装：Playwright MCP
值得：Firecrawl MCP
按需：Chrome MCP（仅当频繁读认证态行情页面）
砍掉：Perplexity MCP、Glyph MCP
优先级更高的非 MCP 事项：配好量化数据 API + Python 回测环境
```
