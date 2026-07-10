"""总控编排 Orchestrator（蓝图 3.0）—— MVP 纯 Python 版，零依赖即可运行。

流程（P1 选品+内容 Copilot 闭环）：
  Hunter 硬门槛 → Scorer 七维评分 → Critic 复核评分 → 人工闸门(终选)
  → Copywriter 生成内容(过合规闸) → Critic 复核内容 → 汇总日报推送

生产环境用 graph.py 里的 LangGraph 有状态图替换本文件（带检查点/回滚/HITL）。
本文件与 graph.py 共用同一批节点函数，保证行为一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Product, ScoreCard, ContentPack, CriticVerdict
from .agents import hunter, scorer, copywriter, critic


@dataclass
class PipelineResult:
    candidates: list[Product] = field(default_factory=list)
    top_cards: list[ScoreCard] = field(default_factory=list)
    score_reviews: dict = field(default_factory=dict)      # spu_id -> CriticVerdict
    contents: dict = field(default_factory=dict)           # spu_id -> ContentPack
    content_reviews: dict = field(default_factory=dict)    # spu_id -> CriticVerdict
    needs_human: list[str] = field(default_factory=list)


def run_pipeline(top_k: int = 5, held_quals: list[str] | None = None) -> PipelineResult:
    res = PipelineResult()

    # ① 爆品发现（硬门槛）
    res.candidates = hunter.run()

    # ② 选品评分（确定性引擎）
    res.top_cards = scorer.run(res.candidates, top_k=top_k)

    # ③ Critic 复核评分（独立反幻觉）
    prod_by_id = {p.spu_id: p for p in res.candidates}
    approved_cards: list[ScoreCard] = []
    for card in res.top_cards:
        v = critic.review_score(prod_by_id[card.spu_id], card)
        res.score_reviews[card.spu_id] = v
        if v.approved:
            approved_cards.append(card)
        else:
            res.needs_human.append(f"{card.spu_id} 评分被 Critic 打回: {v.issues}")

    # ④ 人工闸门：终选（MVP 自动取通过复核的 Top，标记需人工确认）
    #    生产：飞书卡片人点选 3~5 个；此处仅标记，不代替人做发布决策。
    final_pick = approved_cards[:top_k]

    # ⑤ 内容工厂（过合规闸）+ ⑥ Critic 复核内容
    for card in final_pick:
        p = prod_by_id[card.spu_id]
        pack = copywriter.run(p, held_quals=held_quals)
        res.contents[p.spu_id] = pack
        cv = critic.review_content(p, pack)
        res.content_reviews[p.spu_id] = cv
        if not cv.approved:
            res.needs_human.append(f"{p.spu_id} 内容需人工修订: {cv.issues}")

    return res
