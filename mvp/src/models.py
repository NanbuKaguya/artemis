"""数据模型（Pydantic-free 轻量版，零依赖即可运行）。

生产环境建议替换为 Pydantic v2 + SQLModel，这里用 dataclass 保证脚手架
在无第三方依赖时也能直接运行、便于阅读。字段口径与《架构蓝图》第四部分一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class Product:
    """候选商品（SPU 级）。来自爆品发现 Hunter 的原始情报。"""
    spu_id: str
    title: str
    category: str                 # 类目，如 "美妆个护/面部护理"
    sale_price: float             # 抖音在售价（元）
    supply_price: float           # 供货价/到手成本（1688 等）
    # —— 市场情报（来自第三方带货数据/算数）——
    gmv_30d: float                # 近 30 天该品类 GMV 体量（元）
    growth_rate_4w: float         # 近 4 周增速（0.35 = +35%）
    growth_accel: float           # 增速的加速度（>0 表示还在提速）
    talent_count: int             # 带货达人数（铺量密度）
    on_sale_count: int            # 全网在售同款链接数（竞争密度）
    head_concentration: float     # 头部商家集中度 0~1（越高越垄断）
    # —— 供应链 ——
    supplier_rating: float        # 供应商评分 0~1
    ship_hours: float             # 平均发货时效（小时）
    return_rate: float            # 预估退货率 0~1
    # —— 内容/生命周期 ——
    lifecycle_stage: str          # introduction | growth | mature | decline
    pain_points: list[str] = field(default_factory=list)  # 评论洞察出的痛点

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarginCard:
    """利润卡（利润测算 Agent 产出，全部走确定性代码）。"""
    spu_id: str
    gross_margin: float           # 毛利（元/件）
    gross_margin_rate: float      # 毛利率
    breakeven_roi: float          # 盈亏平衡 ROI（售价/单位变动成本）
    affordable_cac: float         # 可承受获客成本（元）
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoreCard:
    """七维评分卡（选品评分 Scorer 产出）。分数均归一到 0~1。"""
    spu_id: str
    dims: dict                     # 七维原始得分
    total: float                   # 加权总分 0~1
    tags: list[str]                # 潜力爆品/蓝海/高利润/上升趋势
    rationale: str = ""            # LLM 生成的可解释理由
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContentPack:
    """内容物料（Copywriter 产出，已过合规闸）。"""
    spu_id: str
    titles: list[str]
    selling_points: list[str]
    detail_copy: str
    video_script: str
    compliance_passed: bool
    compliance_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CriticVerdict:
    """Critic 独立评审结论。"""
    target: str                    # 被审对象类型：score | content
    spu_id: str
    quality: float                 # 0~100
    approved: bool
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def dumps(obj) -> str:
    """统一 JSON 序列化（中文不转义）。"""
    if hasattr(obj, "to_dict"):
        obj = obj.to_dict()
    return json.dumps(obj, ensure_ascii=False, indent=2)
