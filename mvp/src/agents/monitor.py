"""⑤ 数据监控 Monitor（蓝图 3.10）。

已实现：evaluate() 熔断判定（确定性规则，有测试）——只"暂停/预警"，
        **绝不自动加投**（资金红线）。
TODO 桩：真实指标拉取（抖店罗盘/千川 API）。
"""
from __future__ import annotations

from dataclasses import dataclass

# 熔断阈值（按店铺实际情况调，进 .env 亦可）
THRESHOLDS = {
    "refund_rate_max": 0.15,       # 退款率
    "roi_min": 1.2,                # 千川 ROI 低于此值 → 建议暂停计划
    "bad_review_rate_max": 0.08,   # 差评率
    "conversion_drop_pct": 0.5,    # 转化率环比跌幅超 50% → 预警
}


@dataclass
class Alert:
    level: str        # "pause"(建议暂停,进人工闸) | "warn"(仅预警)
    metric: str
    message: str


def evaluate(metrics: dict) -> list[Alert]:
    """输入当期指标 dict，输出告警列表。确定性纯函数。

    metrics 口径: {"refund_rate":0.06, "roi":2.1, "bad_review_rate":0.02,
                   "conversion":0.031, "conversion_prev":0.030}
    """
    alerts: list[Alert] = []
    t = THRESHOLDS

    if metrics.get("refund_rate", 0) > t["refund_rate_max"]:
        alerts.append(Alert("pause", "refund_rate",
                            f"退款率 {metrics['refund_rate']:.0%} 超阈值，建议暂停投放并排查履约"))
    if 0 < metrics.get("roi", 99) < t["roi_min"]:
        alerts.append(Alert("pause", "roi",
                            f"千川 ROI {metrics['roi']:.2f} 低于盈亏线，建议暂停计划（人工确认，绝不自动加投）"))
    if metrics.get("bad_review_rate", 0) > t["bad_review_rate_max"]:
        alerts.append(Alert("warn", "bad_review_rate", "差评率异常，触发评论洞察复查"))
    prev = metrics.get("conversion_prev", 0)
    if prev > 0:
        drop = (prev - metrics.get("conversion", prev)) / prev
        if drop > t["conversion_drop_pct"]:
            alerts.append(Alert("warn", "conversion", f"转化率环比暴跌 {drop:.0%}，触发归因诊断"))
    return alerts


# ---- TODO(Codex) ----

def fetch_shop_metrics() -> dict:
    """TODO(Codex-10): 抖店开放平台 订单/售后 接口聚合出 refund_rate 等；
    千川 API 拉计划级 ROI。走 doudian.client + RateLimiter。"""
    raise NotImplementedError


def tick() -> None:
    """TODO(Codex-11): 定时任务入口(每小时)：fetch → evaluate →
    pause 级 alert 调 notify.request_human_gate("花钱"), warn 级 push_daily_brief。"""
    raise NotImplementedError
