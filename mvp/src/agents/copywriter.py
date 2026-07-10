"""③ 内容文案 Copywriter（蓝图 3.8）。

职责：为选中品生成标题/卖点/详情/短视频脚本，**必过合规硬闸**。
离线模式用模板生成；有 Key 时走 LLM。所有产出经 compliance.gate 过滤后才返回。
"""
from __future__ import annotations

from ..models import Product, ContentPack
from .. import compliance, llm


def _offline_pack(p: Product) -> ContentPack:
    pains = p.pain_points or ["体验一般", "效果不明显"]
    benefits = [f"针对「{pt}」优化" for pt in pains][:3]
    while len(benefits) < 5:
        benefits.append(f"{p.category.split('/')[-1]}优选 · 高性价比")
    titles = [
        f"{p.title}｜{benefits[0]}",
        f"{benefits[1]} {p.title} 回购款",
        f"{p.title} 新升级 · {benefits[2]}",
    ]
    detail = (f"【产品】{p.title}\n【为什么选它】" + "；".join(benefits[:3]) +
              f"\n【适用】日常使用\n【售后】7天无理由，发货时效约{int(p.ship_hours)}小时\n"
              f"【说明】效果因人而异，请理性参考")
    script = (f"[3秒钩子] 还在为“{pains[0]}”烦恼？\n"
              f"[痛点] 大部分同类产品{pains[0]}\n"
              f"[卖点] 这款{benefits[0]}，{benefits[1]}\n"
              f"[信任] 已有大量用户回购\n"
              f"[行动] 点击下方小黄车，先到先得")
    return ContentPack(spu_id=p.spu_id, titles=titles, selling_points=benefits[:5],
                       detail_copy=detail, video_script=script, compliance_passed=False)


def _llm_pack(p: Product) -> ContentPack:
    system = ("你是抖音电商爆款文案。生成标题(3条)、卖点(5条)、详情文案、短视频口播脚本。"
              "严禁使用广告法极限词（最/第一/顶级/100%/根治等）和医疗功效暗示。"
              "输出用清晰分段。")
    user = f"商品:{p.title}\n类目:{p.category}\n痛点:{p.pain_points}\n售价:{p.sale_price}"
    out = llm.complete(system, user, task="bulk", temperature=0.8)
    if llm.is_offline(out):
        return _offline_pack(p)
    # 简化解析：生产用结构化输出/函数调用。此处 demo 直接放入 detail。
    pack = _offline_pack(p)
    pack.detail_copy = out
    return pack


def run(p: Product, held_quals: list[str] | None = None) -> ContentPack:
    pack = _llm_pack(p)
    texts = pack.titles + pack.selling_points + [pack.detail_copy, pack.video_script]
    passed, problems = compliance.gate(texts, p.category, held_quals)
    pack.compliance_passed = passed
    pack.compliance_hits = problems

    if not passed:
        # 命中合规问题：自动脱敏重写标题与卖点（仅供人工参考，不自动放行发布）
        pack.titles = [compliance.scrub(t) for t in pack.titles]
        pack.selling_points = [compliance.scrub(s) for s in pack.selling_points]
        pack.detail_copy = compliance.scrub(pack.detail_copy)
        pack.video_script = compliance.scrub(pack.video_script)
        # 重新过闸
        texts2 = pack.titles + pack.selling_points + [pack.detail_copy, pack.video_script]
        pack.compliance_passed, pack.compliance_hits = compliance.gate(texts2, p.category, held_quals)
    return pack
