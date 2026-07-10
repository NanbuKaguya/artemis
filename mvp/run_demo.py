#!/usr/bin/env python3
"""端到端 Demo —— 抖音电商选品+内容 Copilot（P1 MVP）。

无需任何 API Key 即可运行（LLM 离线回退为模板）。
运行：  python3 run_demo.py
"""
from __future__ import annotations

from src.orchestrator import run_pipeline
from src import notify


def _fmt_dims(dims: dict) -> str:
    cn = {"demand": "需求", "growth": "增长", "competition": "竞争宽松",
          "margin": "毛利", "content": "传播", "supply": "供应", "lifecycle": "周期"}
    return " ".join(f"{cn[k]}{v:.2f}" for k, v in dims.items())


def main() -> None:
    print("🚀 启动抖音电商 Agent 系统（P1: 选品 + 内容 Copilot）\n")
    res = run_pipeline(top_k=5)

    print(f"① 爆品发现 Hunter：{len(res.candidates)} 个候选通过硬门槛")
    print(f"② 选品评分 Scorer：产出 Top {len(res.top_cards)} 榜\n")

    lines = ["【今日选品 Top 榜】(评分引擎确定性打分 · Critic 已复核)\n"]
    for rank, card in enumerate(res.top_cards, 1):
        review = res.score_reviews.get(card.spu_id)
        prod = next(p for p in res.candidates if p.spu_id == card.spu_id)
        flag = "✅通过" if (review and review.approved) else "⚠️需人工"
        lines.append(f"{rank}. [{card.total:.2f}] {prod.title}  {flag}")
        lines.append(f"   标签: {('、'.join(card.tags)) or '常规候选'}")
        lines.append(f"   维度: {_fmt_dims(card.dims)}")
        lines.append(f"   理由: {card.rationale}")
        if card.risks:
            lines.append(f"   ⚠️ 风险: {'；'.join(card.risks)}")
        if review and not review.approved:
            lines.append(f"   🔴 Critic: {'；'.join(review.issues)}")
        # 内容物料
        pack = res.contents.get(card.spu_id)
        if pack:
            cstat = "✅合规通过" if pack.compliance_passed else f"❌合规拦截:{pack.compliance_hits}"
            lines.append(f"   📝 标题: {pack.titles[0]}")
            lines.append(f"   📝 卖点: {' / '.join(pack.selling_points[:3])}")
            lines.append(f"   📝 合规: {cstat}")
        lines.append("")

    notify.push_daily_brief("\n".join(lines))

    # 人机协同闸门
    if res.needs_human:
        notify.request_human_gate(
            "选品终选 / 内容修订",
            "以下项需人工确认：\n  - " + "\n  - ".join(res.needs_human) +
            "\n\n（发布=对外承诺，价格/资质/合规由人拍板后一键发布，"
            "Agent 只到草稿态为止）",
        )

    print("\n✅ 流水线完成。全自动生成情报+物料，花钱/发布/合规节点保留人工闸门。")


if __name__ == "__main__":
    main()
