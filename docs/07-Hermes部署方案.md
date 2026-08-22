# 在本地 Hermes Agent 上部署 Artemis

**边界先说清楚**：本方案下 agent **只做情报，不碰交易**。
它读数据、出简报、提醒纪律问题；下单永远由你亲手做。

这不是靠提示词约束，是**结构性**的：暴露给模型的工具注册表里
根本没有写操作，`place_order` 之类的调用会返回"不存在该工具"。

---

## 一、架构

```
                    ┌──────────────────────────┐
   systemd timer ──▶│  artemis.brief           │
   08:40 / 15:30    │  事实层（不依赖 LLM）      │──▶ 简报文件
                    └────────────┬─────────────┘    + 可选推送
                                 │ facts JSON
                                 ▼
                    ┌──────────────────────────┐
                    │  本地 Hermes（可选）       │
                    │  只负责叙述，不调工具       │
                    └──────────────────────────┘

   交互式问答（你主动问）
                    ┌──────────────────────────┐
   你 ─────────────▶│  copilot.local_llm       │
                    │  run_agent() 工具循环      │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  只读工具注册表（5 个）     │
                    │  写操作不在其中             │
                    └──────────────────────────┘
```

**关键设计：事实层与叙述层分离。**
本地推理会挂——显存不够、服务没起、上下文被截断。
如果简报依赖 LLM 才能生成，你在刚重启完机器那天恰恰收不到。
所以事实层永远能出，LLM 是锦上添花不是承重墙。

---

## 二、暴露给 Hermes 的工具

| 工具 | 作用 |
|---|---|
| `check_market_session` | 是否交易日、当前时段、建议动作 |
| `screen_stocks` | 一组代码的排雷检查 |
| `discipline_review` | 临时起意占比等纪律指标 |
| `data_health` | 本地数据哪些能力已失效 |
| `system_health` | 依赖、时区、日历新鲜度 |

**刻意排除的**：

| 命令 | 理由 |
|---|---|
| `journal-add` | 写操作。**事前承诺必须由人亲手写，代笔就失去了它全部的意义** |
| `calendar-refresh` | 写操作且涉及外部请求，应由调度器而非模型触发 |

工具描述里写死了三条口径，防止模型转述时走样：

- "✓ 通过"只代表没踩那几类雷，**不代表推荐买入**
- 引用历史数据结论前必须先调 `data_health`，dead 非空则结论不可信
- 非交易日的数据是上一交易日的收盘值

---

## 三、部署步骤

### 3.1 一键安装

```bash
sudo REPO=https://github.com/NanbuKaguya/artemis.git \
     BRANCH=claude/blissful-mccarthy-xprsgj \
     bash deploy/install.sh
```

脚本做六件事：建 `artemis` 系统用户 → 拉代码到 `/opt/artemis` →
建 venv 装依赖 → 生成 `/etc/artemis/artemis.env` →
装 systemd 单元 → 跑一次自检。幂等，可重复执行。

### 3.2 配置 Hermes 端点

编辑 `/etc/artemis/artemis.env`：

```bash
ARTEMIS_LLM_BASE_URL=http://localhost:11434/v1   # Ollama
ARTEMIS_LLM_MODEL=hermes3
TZ=Asia/Shanghai
```

按服务栈选：

| 后端 | 端点 | 额外要求 |
|---|---|---|
| Ollama | `:11434/v1` | 0.5+ 才内置工具调用 |
| vLLM | `:8000/v1` | 加 `--enable-auto-tool-choice --tool-call-parser hermes` |
| LM Studio | `:1234/v1` | — |
| llama.cpp | `:8080/v1` | 加 `--jinja` 启用聊天模板的工具格式 |

**Ollama 用户必看**：24GB 显存以下默认上下文只有 4096 token，
且 OpenAI 兼容接口**不接受客户端传上下文长度**。工具签名约占 1400 token，
加上行情数据很容易超，超了会静默截断。必须在服务端设：

```bash
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
```

`health_check()` 会估算并提醒这一点。

### 3.3 验证顺序（别跳步）

```bash
# 1. 系统自检
sudo -u artemis /opt/artemis/.venv/bin/python -m artemis.service health

# 2. Hermes 连通性 + 上下文体检
sudo -u artemis /opt/artemis/.venv/bin/python -c \
  "from artemis.copilot.local_llm import LocalLLM; import json; \
   print(json.dumps(LocalLLM().health_check(), ensure_ascii=False, indent=2))"

# 3. 刷新交易日历（必做）
sudo systemctl start artemis-calendar.service

# 4. 手动跑一次简报
sudo -u artemis /opt/artemis/.venv/bin/python -m artemis.brief premarket

# 5. 确认无误后启用定时器
sudo systemctl enable --now artemis-calendar.timer
sudo systemctl enable --now artemis-brief@premarket.timer
sudo systemctl enable --now artemis-brief@postmarket.timer
sudo systemctl list-timers 'artemis*'
```

第 3 步是必做的：**没有日历缓存时，节假日会被当成交易日**。
系统会在 `basis` 字段明说降级了，但你得先看到它。

---

## 四、三个必须注意的部署陷阱

### 4.1 时区

服务器跑 UTC 而代码假设北京时间，是无人值守最隐蔽的一类故障。
代码内部用 `zoneinfo` 强制 `Asia/Shanghai`，但**日志时间戳走系统时区**——
不设 `TZ`，你看日志会以为任务跑错了时间。

`health` 命令同时报 `now_cn` 和 `now_local`，偏差一眼可见。

### 4.2 非交易日不是故障

`SuccessExitStatus=0 3` 这行不能省。退出码 3 表示"非交易日，正常跳过"。
不写它，systemd 会把每个周末都记成失败——几周之后你就不看告警了，
真故障来了也发现不了。

### 4.3 简报不该依赖 LLM

`ExecStart` 里的 `--llm` 是可选增强。Hermes 挂掉时简报照常产出，
只是少一段叙述，并且明确标注"本地模型调用失败，以上事实部分不受影响"。

---

## 五、日常使用

```bash
# 定时简报会写到这里
ls /var/lib/artemis/briefs/

# 想主动问点什么（工具循环）
sudo -u artemis /opt/artemis/.venv/bin/python -c \
  "from artemis.copilot.local_llm import run_agent; \
   print(run_agent('今天我的自选股有没有踩雷的？', verbose=True)[0])"
```

**事前承诺仍然要你手写**，这是设计而非遗漏：

```bash
sudo -u artemis /opt/artemis/.venv/bin/python -m artemis.lite log
```

---

## 六、运维

```bash
journalctl -u 'artemis-brief@*' -n 50 --no-pager     # 看日志
systemctl list-timers 'artemis*'                      # 下次触发时间
sudo systemctl start artemis-brief@premarket.service  # 手动触发一次
```

**每月检查一次日历覆盖范围**：

```bash
sudo -u artemis /opt/artemis/.venv/bin/python -m artemis.service session
```

`basis` 字段若出现 `weekday_fallback`，说明日历过期了，节假日不再可靠。
国务院办公厅通常在上一年 11–12 月公布次年节假日安排（含调休），
所以**年底那次刷新尤其重要**。

---

## 七、诚实的状态说明

| 组件 | 状态 |
|---|---|
| 事实层、工具注册表、简报、解析逻辑 | 已测试（99 项） |
| systemd 单元、install.sh | 语法校验过，**未在真实机器上跑过** |
| `qmt_source.py` / `akshare_source.py` | 写了，**从未接触真实数据源** |
| Hermes 端点交互 | 两条解析路线都有测试，但**未对真实 Hermes 实测** |

最后一项要你在本机验证：跑 `LocalLLM().health_check()`，
看 `native_tool_calls` 和 `text_tool_calls` 哪个为 true。
两个都是 false 说明模型没在用工具，多半是上下文被截断或模型不支持——
把 `health_check()` 的完整输出发给我，我来定位。
