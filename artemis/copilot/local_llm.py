"""本地 LLM 客户端（Hermes 系列 / 任何 OpenAI 兼容端点）。

只用标准库 urllib —— 本地端点不值得为它加一个 HTTP 依赖。

支持的后端：任何实现 /v1/chat/completions 的服务
  Ollama       http://localhost:11434/v1   （需 0.5+）
  vLLM         http://localhost:8000/v1    （建议加 --enable-auto-tool-choice --tool-call-parser hermes）
  LM Studio    http://localhost:1234/v1
  llama.cpp    http://localhost:8080/v1    （需 --jinja 以启用聊天模板的工具格式）

**工具调用有两条路，必须都支持**，因为走哪条取决于你的服务栈：
  A. 服务端已解析 → 返回标准的 message.tool_calls 数组
  B. 服务端未解析 → 模型的 <tool_call>{...}</tool_call> 原样出现在 content 里
Ollama 和 llama.cpp 在不同版本/配置下表现不一，所以两条都解析。
只做 A 会在某些栈上静默拿不到工具调用 —— 模型看起来"不会用工具"，
实际是你没接住它。

一个常见的坑：Ollama 在 24GB 显存以下默认上下文只有 4096 token，
且 OpenAI 兼容接口**不接受客户端传 context length**。工具签名加上
行情数据很容易超，超了就静默截断。必须在服务端设 OLLAMA_CONTEXT_LENGTH。
health_check() 会估算并提醒。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

from .tools import dispatch, render_hermes_system, render_openai_tools, tool_names

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


class LocalLLMError(RuntimeError):
    pass


@dataclass
class LocalLLM:
    """OpenAI 兼容端点的极简客户端。"""

    base_url: str = field(default_factory=lambda: os.environ.get(
        "ARTEMIS_LLM_BASE_URL", "http://localhost:11434/v1"))
    model: str = field(default_factory=lambda: os.environ.get(
        "ARTEMIS_LLM_MODEL", "hermes3"))
    api_key: str = field(default_factory=lambda: os.environ.get(
        "ARTEMIS_LLM_API_KEY", "not-needed"))
    timeout: int = 300          # 本地推理慢，超时要给足
    temperature: float = 0.2    # 情报任务要稳定，不要创造力
    max_tokens: int = 2048
    native_tools: bool = True   # 端点是否支持原生 tools 参数

    # ---------------------------------------------------------------- HTTP
    def _post(self, path: str, payload: dict) -> dict:
        url = self.base_url.rstrip("/") + path
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise LocalLLMError(f"HTTP {e.code} from {url}: {body}") from e
        except urllib.error.URLError as e:
            raise LocalLLMError(
                f"连不上 {url}：{e.reason}。\n"
                f"检查：1) 推理服务是否在跑  2) ARTEMIS_LLM_BASE_URL 是否正确\n"
                f"   Ollama 默认 http://localhost:11434/v1，vLLM 默认 http://localhost:8000/v1"
            ) from e

    def chat(self, messages: list[dict], use_tools: bool = True) -> dict:
        payload: dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": self.temperature, "max_tokens": self.max_tokens,
        }
        if use_tools and self.native_tools:
            payload["tools"] = render_openai_tools()
            payload["tool_choice"] = "auto"
        return self._post("/chat/completions", payload)

    # ---------------------------------------------------------------- 体检
    def health_check(self) -> dict:
        """连通性 + 上下文长度体检。跑 agent 之前先跑它。"""
        out: dict[str, Any] = {"base_url": self.base_url, "model": self.model}
        try:
            r = self.chat([{"role": "user", "content": "回复 OK 两个字符"}], use_tools=False)
            out["reachable"] = True
            out["reply"] = (r.get("choices", [{}])[0]
                            .get("message", {}).get("content", ""))[:50]
            usage = r.get("usage") or {}
            out["usage"] = usage
        except LocalLLMError as e:
            out["reachable"] = False
            out["error"] = str(e)
            return out

        # 估算系统提示 + 工具签名的 token 占用（粗算：中文约 1.5 字符/token）
        sys_len = len(render_hermes_system())
        est = int(sys_len / 1.5) + 400
        out["system_prompt_chars"] = sys_len
        out["estimated_prompt_tokens"] = est
        out["warnings"] = []
        if est > 3000:
            out["warnings"].append(
                f"工具签名约占 {est} token。Ollama 在 24GB 显存以下默认上下文仅 4096，"
                f"且 OpenAI 兼容接口不接受客户端设置上下文长度 —— "
                f"请在服务端设 OLLAMA_CONTEXT_LENGTH=16384 或更高，否则会静默截断。"
            )
        # 检测是否支持原生 tools
        try:
            r2 = self.chat([{"role": "user", "content": "现在是不是交易日？"}], use_tools=True)
            msg = r2.get("choices", [{}])[0].get("message", {})
            out["native_tool_calls"] = bool(msg.get("tool_calls"))
            out["text_tool_calls"] = bool(TOOL_CALL_RE.search(msg.get("content") or ""))
        except LocalLLMError as e:
            out["warnings"].append(f"带工具的请求失败：{str(e)[:120]}")
            out["native_tool_calls"] = False
        return out


# --------------------------------------------------------------------------
# 工具调用解析：两条路都要接住
# --------------------------------------------------------------------------
def extract_tool_calls(message: dict) -> list[dict]:
    """从模型返回里抽出工具调用。

    路线 A：服务端已解析 → message["tool_calls"]
    路线 B：服务端未解析 → content 里的 <tool_call>{...}</tool_call>

    只实现 A 会在 Ollama / llama.cpp 的某些配置下拿不到任何调用，
    表现为"模型不会用工具"，实际是没接住。
    """
    calls: list[dict] = []

    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        raw = fn.get("arguments")
        try:
            argsc = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            argsc = {}
        calls.append({"id": tc.get("id", f"call_{len(calls)}"),
                      "name": fn.get("name", ""), "arguments": argsc,
                      "source": "native"})

    content = message.get("content") or ""
    for i, m in enumerate(TOOL_CALL_RE.finditer(content)):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        name = obj.get("name", "")
        if any(c["name"] == name for c in calls):
            continue          # 已从 native 拿到，不重复
        calls.append({"id": f"text_{i}", "name": name,
                      "arguments": obj.get("arguments") or {},
                      "source": "text"})
    return calls


def strip_tool_calls(content: str) -> str:
    """把 <tool_call> 块从正文里去掉，剩下的才是给人看的话。"""
    return TOOL_CALL_RE.sub("", content or "").strip()


# --------------------------------------------------------------------------
# Agent 循环
# --------------------------------------------------------------------------
@dataclass
class TurnLog:
    """一轮的执行记录。情报任务必须可追溯：
    用户看到的每个数字，都要能追到是哪次工具调用返回的。"""

    round: int
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    assistant_text: str = ""


def run_agent(
    user_prompt: str,
    llm: LocalLLM | None = None,
    max_rounds: int = 6,
    verbose: bool = False,
) -> tuple[str, list[TurnLog]]:
    """跑一轮情报任务。返回 (最终回答, 完整执行记录)。

    max_rounds 是硬上限：本地模型在工具调用上更容易陷入循环
    （反复调同一个工具），必须卡死轮数而不是指望它自己停。
    """
    llm = llm or LocalLLM()
    messages: list[dict] = [
        {"role": "system", "content": render_hermes_system()},
        {"role": "user", "content": user_prompt},
    ]
    logs: list[TurnLog] = []

    for rnd in range(1, max_rounds + 1):
        resp = llm.chat(messages)
        msg = resp.get("choices", [{}])[0].get("message", {})
        content = msg.get("content") or ""
        calls = extract_tool_calls(msg)
        log = TurnLog(round=rnd, tool_calls=calls,
                      assistant_text=strip_tool_calls(content))

        if not calls:
            logs.append(log)
            if verbose:
                print(f"[round {rnd}] 无工具调用，结束")
            return log.assistant_text or content, logs

        messages.append({"role": "assistant", "content": content,
                         **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {})})

        for c in calls:
            result = dispatch(c["name"], c["arguments"])
            log.tool_results.append({"name": c["name"], "result": result})
            if verbose:
                print(f"[round {rnd}] {c['name']}({c['arguments']}) "
                      f"-> ok={result.get('ok')} [{c['source']}]")

            if c["source"] == "native":
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "name": c["name"],
                                 "content": json.dumps(result, ensure_ascii=False)})
            else:
                # 文本路线：按 Hermes 约定回填 <tool_response>
                messages.append({
                    "role": "user",
                    "content": f"<tool_response>\n"
                               f"{json.dumps(result, ensure_ascii=False)}\n"
                               f"</tool_response>",
                })
        logs.append(log)

    # 达到轮数上限：不要静默返回半成品
    return ("（达到最大工具调用轮数仍未收敛。本地模型在工具调用上容易循环，"
            "请检查执行记录中是否反复调用同一工具。）"), logs
