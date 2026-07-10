"""LLM 客户端封装 —— 多模型路由 + 离线回退。

对应蓝图 7.1。生产环境用 Claude Agent SDK / 国产模型路由；
本脚手架在无 API Key 时自动回退到"确定性模板"，保证 demo 端到端可跑通、
且 CI 可离线验证。**注意：金额/评分等数值从不经过 LLM（见 margin.py / scoring.py）。**
"""
from __future__ import annotations

import os


def _has_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))


def complete(system: str, user: str, *, task: str = "general", temperature: float = 0.7) -> str:
    """统一补全入口。

    task 用于模型路由：'reasoning' -> 强模型；'bulk' -> 性价比模型。
    离线模式下由各调用方提供的 offline_fallback 兜底（此处返回哨兵）。
    """
    if not _has_key():
        return "[[OFFLINE]]"

    # —— 生产实现示例（按需启用其一）——
    # from anthropic import Anthropic
    # client = Anthropic()
    # model = "claude-opus-4-8" if task == "reasoning" else "claude-haiku-4-5-20251001"
    # msg = client.messages.create(
    #     model=model, max_tokens=1500, temperature=temperature,
    #     system=system, messages=[{"role": "user", "content": user}],
    # )
    # return msg.content[0].text
    raise RuntimeError("检测到 API Key，但生产 LLM 调用未启用：请取消 llm.complete 中的注释并安装 SDK。")


def is_offline(text: str) -> bool:
    return text == "[[OFFLINE]]"
