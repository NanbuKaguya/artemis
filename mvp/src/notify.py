"""通知 / 人机协同闸门推送 —— 飞书/企微卡片（蓝图 7.3）。

MVP 打印到控制台 + 可选 Webhook。审批闸门通过 IM 卡片的"通过/驳回"回调实现
（此处给出结构，回调服务在生产的 API 层实现）。
"""
from __future__ import annotations

import json
import os
import urllib.request


def _webhook() -> str | None:
    return os.getenv("FEISHU_WEBHOOK") or os.getenv("WECOM_WEBHOOK")


def push_daily_brief(text: str) -> None:
    """推送每日经营简报/选品日报。"""
    print("\n" + "=" * 68)
    print("📮 [飞书/企微 推送] 每日选品日报")
    print("=" * 68)
    print(text)

    url = _webhook()
    if url:
        try:
            payload = {"msg_type": "text", "content": {"text": text}}
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            print("(已发送到 Webhook)")
        except Exception as e:   # noqa: BLE001
            print(f"(Webhook 发送失败，仅本地展示: {e})")


def request_human_gate(kind: str, summary: str) -> None:
    """触发人工闸门（花钱/发布/合规）。生产环境为可交互 IM 卡片。"""
    print("\n" + "🔔" * 34)
    print(f"⚠️  人工闸门 [{kind}] 待决策")
    print(summary)
    print("👉 请在飞书卡片点击 [通过 / 驳回]（MVP 阶段人工在后台确认）")
    print("🔔" * 34)
