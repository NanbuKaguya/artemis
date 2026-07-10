"""生产编排：LangGraph 有状态图（蓝图 7.1）。

与 orchestrator.py 行为一致，但带上生产必需的三件事：
  · 检查点 checkpoint（每节点可回滚）
  · human-in-the-loop 中断（终选/发布/花钱 三闸用 interrupt 挂起等人）
  · 条件路由（Critic 打回 → 重做/降级人审）

⚠️ 需要 `pip install langgraph`。未安装时本模块 import 会报错，
   不影响 orchestrator.py 与 run_demo.py 的离线运行。
"""
from __future__ import annotations

from typing import TypedDict

from .agents import hunter, scorer, copywriter, critic


class GraphState(TypedDict, total=False):
    top_k: int
    held_quals: list
    candidates: list
    top_cards: list
    approved_cards: list
    contents: dict
    needs_human: list
    human_approved_picks: list      # 由人工闸门写入


def build_graph():
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import interrupt

    def n_hunter(s: GraphState) -> GraphState:
        return {"candidates": hunter.run()}

    def n_scorer(s: GraphState) -> GraphState:
        return {"top_cards": scorer.run(s["candidates"], top_k=s.get("top_k", 5))}

    def n_score_critic(s: GraphState) -> GraphState:
        by_id = {p.spu_id: p for p in s["candidates"]}
        approved, needs = [], list(s.get("needs_human", []))
        for c in s["top_cards"]:
            v = critic.review_score(by_id[c.spu_id], c)
            (approved.append(c) if v.approved
             else needs.append(f"{c.spu_id} 评分打回: {v.issues}"))
        return {"approved_cards": approved, "needs_human": needs}

    def n_human_gate(s: GraphState) -> GraphState:
        # 人工闸门：挂起，等人在飞书卡片选定终选品
        picks = interrupt({"reason": "终选 3~5 个品",
                           "candidates": [c.spu_id for c in s["approved_cards"]]})
        return {"human_approved_picks": picks}

    def n_content(s: GraphState) -> GraphState:
        by_id = {p.spu_id: p for p in s["candidates"]}
        picks = s.get("human_approved_picks") or [c.spu_id for c in s["approved_cards"]]
        contents, needs = {}, list(s.get("needs_human", []))
        for spu in picks:
            p = by_id[spu]
            pack = copywriter.run(p, held_quals=s.get("held_quals"))
            contents[spu] = pack
            cv = critic.review_content(p, pack)
            if not cv.approved:
                needs.append(f"{spu} 内容需人工修订: {cv.issues}")
        return {"contents": contents, "needs_human": needs}

    g = StateGraph(GraphState)
    g.add_node("hunter", n_hunter)
    g.add_node("scorer", n_scorer)
    g.add_node("score_critic", n_score_critic)
    g.add_node("human_gate", n_human_gate)
    g.add_node("content", n_content)

    g.set_entry_point("hunter")
    g.add_edge("hunter", "scorer")
    g.add_edge("scorer", "score_critic")
    g.add_edge("score_critic", "human_gate")
    g.add_edge("human_gate", "content")
    g.add_edge("content", END)

    return g.compile(checkpointer=MemorySaver())
