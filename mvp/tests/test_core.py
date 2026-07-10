"""核心引擎测试 —— 确定性部分必须 100% 可靠（防幻觉红线）。

可用 pytest 运行，也可直接 `python3 tests/test_core.py`（零依赖）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Product
from src.margin import compute_margin
from src.scoring import score_product, DEFAULT_WEIGHTS
from src import compliance


def _product(**over):
    base = dict(
        spu_id="T", title="测试品", category="家居日用/厨房工具",
        sale_price=100.0, supply_price=30.0, gmv_30d=3_000_000,
        growth_rate_4w=0.4, growth_accel=0.05, talent_count=80,
        on_sale_count=150, head_concentration=0.3, supplier_rating=0.85,
        ship_hours=40, return_rate=0.08, lifecycle_stage="growth", pain_points=["a", "b"],
    )
    base.update(over)
    return Product(**base)


def test_margin_positive():
    m = compute_margin(_product())
    assert m.gross_margin > 0
    assert 0 < m.gross_margin_rate < 1


def test_margin_negative_when_supply_high():
    m = compute_margin(_product(sale_price=20, supply_price=19))
    assert m.gross_margin <= 0
    assert any("负" in n for n in m.notes)


def test_score_in_range():
    p = _product()
    card = score_product(p, compute_margin(p))
    assert 0 <= card.total <= 1
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-6


def test_decline_penalized():
    p_growth = _product(lifecycle_stage="growth")
    p_decline = _product(lifecycle_stage="decline")
    s1 = score_product(p_growth, compute_margin(p_growth)).total
    s2 = score_product(p_decline, compute_margin(p_decline)).total
    assert s1 > s2


def test_high_return_flagged_as_risk():
    p = _product(return_rate=0.30)
    card = score_product(p, compute_margin(p))
    assert any("退货" in r for r in card.risks)


def test_compliance_blocks_absolute_terms():
    ok, problems = compliance.gate(["全网最强第一名"], "家居日用/厨房工具")
    assert not ok
    assert any("最" in x or "第一" in x for x in problems)


def test_compliance_blocks_missing_qualification():
    ok, problems = compliance.gate(["普通标题"], "食品饮料/咖啡")
    assert not ok
    assert any("资质" in x for x in problems)


def test_compliance_passes_clean():
    ok, problems = compliance.gate(["温和洁面 日常使用"], "美妆个护/面部护理",
                                   held_quals=["化妆品生产/经营备案"])
    assert ok and problems == []


def test_scrub_removes_terms():
    scrubbed = compliance.scrub("最强第一")
    assert "最" not in scrubbed and "第一" not in scrubbed


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ✅ {fn.__name__}")
    print(f"\n{passed}/{len(fns)} 测试通过")


if __name__ == "__main__":
    _run_all()
