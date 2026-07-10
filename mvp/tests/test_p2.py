"""P2 基础设施测试 —— 限频/缓存/趋势/抖店签名/草稿组装/熔断/VoC 兜底。

运行：python3 tests/test_p2.py（零依赖）或 pytest。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.datasources.base import RateLimiter, TTLCache
from src.datasources.trend import growth_metrics, lifecycle_stage
from src.doudian.client import sign, canonical_param_json, build_draft_payload
from src.agents.monitor import evaluate
from src.agents.voc import extract_pain_points
from src.agents import listing
from src.models import Product, ContentPack


def test_rate_limiter_spacing():
    t = {"now": 0.0}
    waited = []
    rl = RateLimiter(rate_per_min=60,  # 间隔 1s
                     _clock=lambda: t["now"], _sleep=lambda s: waited.append(s))
    assert rl.acquire() == 0.0          # 第一次不等待
    assert rl.acquire() == 1.0          # 立刻再取 → 等满 1s
    t["now"] = 10.0
    assert rl.acquire() == 0.0          # 已过窗口 → 不等待


def test_ttl_cache_expiry():
    t = {"now": 1000.0}
    with tempfile.TemporaryDirectory() as d:
        c = TTLCache(Path(d), ttl_seconds=60, _clock=lambda: t["now"])
        assert c.get("k") is None
        c.set("k", {"a": 1})
        assert c.get("k") == {"a": 1}
        t["now"] += 61                   # 过期
        assert c.get("k") is None


def test_growth_metrics():
    g, a = growth_metrics([100, 120, 150, 200])
    assert g == 1.0                      # (200-100)/100
    assert a > 0                         # 环比在加速


def test_lifecycle_decline():
    assert lifecycle_stage([100, 200, 300, 150]) == "decline"   # 末周<峰值70%
    assert lifecycle_stage([100, 130, 170, 230]) == "growth"


def test_doudian_sign_deterministic():
    pj = canonical_param_json({"b": 1, "a": "中文"})
    assert pj == '{"a":"中文","b":1}'    # key 升序、无空格、保留中文
    s1 = sign("key1", "secret1", "product.addV2", pj, "2026-07-10 12:00:00")
    s2 = sign("key1", "secret1", "product.addV2", pj, "2026-07-10 12:00:00")
    assert s1 == s2 and len(s1) == 64    # HMAC-SHA256 hex


def test_draft_payload_is_draft_only():
    payload = build_draft_payload(
        category_leaf_id=123, product_title="测试品",
        selling_points=["a"], detail_html="<p>x</p>",
        pic_urls=["http://img"], sku_list=[{"spec": "默认", "price_yuan": 59.9,
                                            "stock": 10, "supply_price_yuan": 22.0}])
    assert payload["status"] == 1        # ★ 红线：只能草稿态
    assert payload["spec_prices"][0]["price"] == 5990   # 元→分集中换算


def test_draft_payload_rejects_bad_price():
    try:
        build_draft_payload(category_leaf_id=1, product_title="t",
                            selling_points=[], detail_html="d", pic_urls=["u"],
                            sku_list=[{"spec": "默认", "price_yuan": 10,
                                       "stock": 1, "supply_price_yuan": 20}])
        assert False, "售价<供货价应被拒绝"
    except ValueError:
        pass


def test_monitor_circuit_breaker():
    alerts = evaluate({"refund_rate": 0.20, "roi": 0.8,
                       "conversion": 0.01, "conversion_prev": 0.03})
    levels = {a.metric: a.level for a in alerts}
    assert levels["refund_rate"] == "pause"
    assert levels["roi"] == "pause"      # 只暂停，无任何"加投"动作
    assert levels["conversion"] == "warn"
    assert evaluate({"refund_rate": 0.02, "roi": 3.0}) == []


def test_voc_offline_extraction():
    pains = extract_pain_points(["用两天就坏了", "开裂了", "发货慢死", "挺好的"])
    assert pains[0] == "痛点:质量差"
    assert "痛点:物流慢" in pains


def test_listing_dryrun_creates_draft():
    p = Product(spu_id="TL", title="测试品", category="家居日用/厨房工具",
                sale_price=45.0, supply_price=14.0, gmv_30d=1e6,
                growth_rate_4w=0.3, growth_accel=0.05, talent_count=10,
                on_sale_count=50, head_concentration=0.2, supplier_rating=0.8,
                ship_hours=40, return_rate=0.05, lifecycle_stage="growth")
    pack = ContentPack(spu_id="TL", titles=["测试品 好用款"],
                       selling_points=["耐高温", "好收纳", "易清洗"],
                       detail_copy="日常好物", video_script="s", compliance_passed=True)
    res = listing.run(p, pack)
    assert res["ok"] and res["via"] == "dryrun"
    assert Path(res["draft_path"]).exists()
    Path(res["draft_path"]).unlink()     # 清理


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✅ {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} 测试通过")


if __name__ == "__main__":
    _run_all()
