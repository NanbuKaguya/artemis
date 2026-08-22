"""本地 LLM 集成层的回归测试。

两个重点：
1. **只读边界是结构性的** —— 不是靠模型听话，是靠没东西可调
2. **工具调用两条解析路线都要接住** —— 只做一条会在某些服务栈上
   表现为"模型不会用工具"，实际是没接住
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.brief import Brief, build_facts, render_text
from artemis.copilot.local_llm import (
    LocalLLM, LocalLLMError, extract_tool_calls, strip_tool_calls,
)
from artemis.copilot.tools import (
    EXCLUDED, READONLY_COMMANDS, TOOLS, dispatch,
    render_hermes_system, render_openai_tools, tool_names,
)


# ---------------------------------------------------------------- 只读边界
def test_registry_contains_only_readonly_commands():
    """结构性保证：注册表里不能有写操作。"""
    for t in TOOLS:
        assert t.command in READONLY_COMMANDS, f"{t.name} 指向非只读命令 {t.command}"


def test_write_commands_explicitly_excluded():
    assert "journal-add" in EXCLUDED
    assert "journal-add" not in tool_names()


def test_hallucinated_trading_tool_has_nothing_to_call():
    """模型幻觉出下单工具时，这里必须没有东西可调。"""
    for fake in ["place_order", "submit_order", "buy", "sell", "execute_trade"]:
        r = dispatch(fake, {"code": "600519", "shares": 100})
        assert r["ok"] is False
        assert r["error_type"] == "tool_not_available"


def test_excluded_tool_explains_why():
    """被禁用的工具要说明理由 —— 模型和人都需要知道为什么。"""
    r = dispatch("journal-add", {"code": "600519"})
    assert r["ok"] is False
    assert "写操作" in r["error"]


def test_dispatch_never_raises(monkeypatch):
    """工具执行失败必须返回结构化错误，抛异常会中断整个对话。"""
    from artemis.copilot import tools as T

    def boom(_a):
        raise RuntimeError("模拟故障")
    monkeypatch.setitem(T.COMMANDS, "health", boom)
    r = dispatch("system_health", {})
    assert r["ok"] is False and r["error_type"] == "RuntimeError"


# ---------------------------------------------------------------- 提示渲染
def test_hermes_system_prompt_contains_tools_tag():
    s = render_hermes_system()
    assert "<tools>" in s and "</tools>" in s
    assert "<tool_call>" in s
    for t in TOOLS:
        assert t.name in s


def test_system_prompt_forbids_trading_advice():
    """不给买卖建议必须写进系统提示，而不只是写在文档里。"""
    s = render_hermes_system()
    assert "不碰交易" in s or "绝不给出买卖建议" in s


def test_openai_tools_are_valid_json_schema():
    for t in render_openai_tools():
        assert t["type"] == "function"
        f = t["function"]
        assert f["parameters"]["type"] == "object"
        json.dumps(t)   # 必须可序列化


# ---------------------------------------------------------------- 工具调用解析
def test_native_tool_calls_parsed():
    msg = {"content": None, "tool_calls": [
        {"id": "c1", "function": {"name": "screen_stocks",
                                  "arguments": '{"codes":["600519"]}'}}]}
    calls = extract_tool_calls(msg)
    assert len(calls) == 1
    assert calls[0]["arguments"] == {"codes": ["600519"]}
    assert calls[0]["source"] == "native"


def test_text_tool_calls_parsed():
    """Ollama / llama.cpp 某些配置下 <tool_call> 会留在正文里。

    只实现 native 路线会在这些栈上拿不到任何调用，
    表现为"模型不会用工具"—— 实际是没接住。
    """
    msg = {"content": '好的。<tool_call>\n{"name":"system_health","arguments":{}}\n</tool_call>'}
    calls = extract_tool_calls(msg)
    assert len(calls) == 1 and calls[0]["source"] == "text"


def test_multiple_text_tool_calls():
    msg = {"content": '<tool_call>{"name":"system_health","arguments":{}}</tool_call>'
                      '<tool_call>{"name":"data_health","arguments":{}}</tool_call>'}
    assert [c["name"] for c in extract_tool_calls(msg)] == ["system_health", "data_health"]


def test_duplicate_across_both_routes_deduped():
    """同一个调用同时出现在 native 和文本里，不能执行两遍。"""
    msg = {"content": '<tool_call>{"name":"system_health","arguments":{}}</tool_call>',
           "tool_calls": [{"id": "c1", "function": {"name": "system_health",
                                                    "arguments": "{}"}}]}
    assert len(extract_tool_calls(msg)) == 1


def test_malformed_tool_call_json_skipped_not_crash():
    msg = {"content": '<tool_call>{"name": 这不是合法JSON</tool_call>'}
    assert extract_tool_calls(msg) == []


def test_malformed_native_arguments_default_to_empty():
    msg = {"content": None, "tool_calls": [
        {"id": "c1", "function": {"name": "system_health", "arguments": "{broken"}}]}
    assert extract_tool_calls(msg)[0]["arguments"] == {}


def test_strip_tool_calls_leaves_human_text():
    c = '我先查一下。<tool_call>{"name":"x","arguments":{}}</tool_call> 稍等。'
    out = strip_tool_calls(c)
    assert "<tool_call>" not in out
    assert "我先查一下" in out and "稍等" in out


# ---------------------------------------------------------------- 连接失败
def test_unreachable_endpoint_gives_actionable_error():
    llm = LocalLLM(base_url="http://127.0.0.1:59998/v1", timeout=2)
    h = llm.health_check()
    assert h["reachable"] is False
    # 报错要带排查线索，不能只说"失败了"
    assert "ARTEMIS_LLM_BASE_URL" in h["error"] or "11434" in h["error"]


# ---------------------------------------------------------------- 简报
def test_brief_works_without_llm():
    """核心架构保证：LLM 挂了简报照样出。"""
    b = build_facts("premarket")
    assert isinstance(b, Brief)
    assert b.facts.get("session") is not None
    assert b.narrative is None
    txt = render_text(b)
    assert "盘前情报" in txt


def test_brief_survives_broken_llm():
    b = build_facts("premarket")
    from artemis.brief import narrate
    b = narrate(b, llm=LocalLLM(base_url="http://127.0.0.1:59997/v1", timeout=2))
    assert b.llm_error is not None
    txt = render_text(b)
    assert "以上事实部分不受影响" in txt


def test_brief_alerts_deduped():
    b = build_facts("premarket")
    assert len(b.alerts) == len(set(b.alerts)), "同一条告警不该重复出现"


def test_brief_disclaims_no_trading_advice():
    txt = render_text(build_facts("premarket"))
    assert "不构成投资建议" in txt


def test_brief_json_is_machine_readable():
    b = build_facts("postmarket")
    parsed = json.loads(b.to_json())
    assert parsed["kind"] == "postmarket"
    assert "facts" in parsed and "alerts" in parsed
