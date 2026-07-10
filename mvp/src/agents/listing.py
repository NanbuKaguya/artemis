"""④ 上架组装 Listing（蓝图 3.9 / 第五部分）。

流程：内容物料 → 合规复检 → 组装草稿 payload → 落盘 data/drafts/
     → (凭证可用时) 抖店 API 写草稿态 → 触发人工发布闸门。

已实现：dry-run 全流程（无凭证时草稿落盘，人可直接拿去后台粘贴）。
TODO(Codex-9)：凭证可用时打通 client.call 真实写草稿（依赖 Codex-6~8）。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Product, ContentPack
from .. import compliance, notify
from ..doudian.client import DoudianClient, build_draft_payload

_DRAFT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "drafts"


def run(p: Product, pack: ContentPack, *, category_leaf_id: int = 0,
        held_quals: list[str] | None = None) -> dict:
    """返回 {"ok": bool, "draft_path"|"error": ..., "via": "api"|"dryrun"}。"""
    # 1) 合规复检（上架前最后一道硬闸，不信任上游状态）
    texts = pack.titles + pack.selling_points + [pack.detail_copy]
    ok, problems = compliance.gate(texts, p.category, held_quals)
    if not ok:
        return {"ok": False, "error": f"合规复检未过: {problems}", "via": "gate"}

    # 2) 组装草稿（确定性，缺参即拒）
    payload = build_draft_payload(
        category_leaf_id=category_leaf_id,
        product_title=pack.titles[0],
        selling_points=pack.selling_points,
        detail_html=pack.detail_copy.replace("\n", "<br/>"),
        pic_urls=["<待上传主图>"],          # TODO(Codex-9): upload_image 后替换
        sku_list=[{"spec": "默认", "price_yuan": p.sale_price,
                   "stock": 0, "supply_price_yuan": p.supply_price}],
    )

    # 3) 写草稿：优先官方 API，无凭证则落盘 dry-run
    client = DoudianClient()
    if client.available:
        # TODO(Codex-9): resp = client.create_product_draft(payload)
        #                失败读 sub_msg 自动修正一次后重试，仍失败进人工队列
        via = "api"
        draft_path = None
        raise NotImplementedError("真实 API 写草稿依赖 Codex-6~8 完成")
    else:
        _DRAFT_DIR.mkdir(parents=True, exist_ok=True)
        draft_path = _DRAFT_DIR / f"{p.spu_id}.json"
        draft_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        via = "dryrun"

    # 4) 发布永远走人工闸门（红线）
    notify.request_human_gate(
        "发布",
        f"商品草稿已就绪: {pack.titles[0]}\n"
        f"售价 ¥{p.sale_price} / 供货 ¥{p.supply_price}\n"
        f"草稿: {draft_path or '抖店后台草稿箱'}\n"
        f"请人工核对 价格/资质/主图 后在后台点击上架",
    )
    return {"ok": True, "draft_path": str(draft_path), "via": via}
