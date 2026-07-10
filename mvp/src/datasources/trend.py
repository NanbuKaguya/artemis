"""趋势计算工具 —— 从时间序列算 增速/加速度/生命周期（确定性，已实现+测试）。

所有数据源的 sales_trend[] 都用这里换算，保证口径统一（蓝图 4.2）。
"""
from __future__ import annotations


def growth_metrics(series: list[float]) -> tuple[float, float]:
    """输入按周的销量/GMV 序列（旧→新，至少 4 点），返回 (4周增速, 加速度)。

    增速   = (末周 − 首周) / 首周
    加速度 = 后半段平均环比 − 前半段平均环比
    """
    if len(series) < 4 or series[0] <= 0:
        return 0.0, 0.0
    s = series[-4:]
    growth = (s[-1] - s[0]) / s[0]

    def avg_ratio(seg: list[float]) -> float:
        ratios = [(b - a) / a for a, b in zip(seg, seg[1:]) if a > 0]
        return sum(ratios) / len(ratios) if ratios else 0.0

    mid = len(s) // 2
    accel = avg_ratio(s[mid - 1:]) - avg_ratio(s[: mid + 1])
    return round(growth, 4), round(accel, 4)


def lifecycle_stage(series: list[float]) -> str:
    """由曲线形态判定生命周期（口径见 scoring._LIFECYCLE_SCORE）。

    规则（简化但确定）:
      · 基数小且在涨            → introduction
      · 增速>15% 且加速度≥0     → growth
      · 末周 < 峰值 70%         → decline
      · 其余                    → mature
    """
    if len(series) < 4:
        return "introduction"
    growth, accel = growth_metrics(series)
    peak = max(series)
    if peak > 0 and series[-1] < 0.7 * peak:
        return "decline"
    if growth > 0.15 and accel >= 0:
        return "growth" if series[0] > 0.2 * peak else "introduction"
    if growth > 0:
        return "introduction" if series[-1] < 0.3 * peak else "mature"
    return "mature"
