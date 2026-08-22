"""执行成本：测量、归因、优化。

对日频调仓的个人投资者，这是 Level-2 数据价值最确定的地方。
按 Artemis 默认成本模型，单次完整买卖 26bp，其中滑点占 16bp（双边各 8bp）。
如果 L2 能把单边滑点从 8bp 压到 4bp，年换手 6 倍就是每年省 0.48% ——
这个收益是确定的、可验证的，不需要你比别人更会选股。

**一个必须建进模型的东西：逆向选择。**
被动挂单看起来能省下半个价差，但你会在价格对你不利时优先成交：
买单挂在 bid1，价格下跌时才轮到你成交；价格上涨时你根本买不到。
所以"省下的价差"里有一部分是幻觉。不把这一项算进去，
会系统性高估被动挂单的收益，然后你在实盘发现省下的钱远没有回测多。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

TICK = 0.01          # A 股最小变动价位（1 元以上股票）


@dataclass
class Fill:
    """一笔成交记录，用于事后成本归因。"""

    code: str
    side: Literal["buy", "sell"]
    arrival_price: float      # 决策时刻的中间价（成本基准）
    fill_price: float         # 实际成交均价
    shares: float
    interval_vwap: float      # 下单到成交期间的市场 VWAP
    close_price: float        # 当日收盘价

    @property
    def signed(self) -> int:
        return 1 if self.side == "buy" else -1

    def decompose(self) -> dict:
        """把滑点拆成三块，因为三块的改善方式完全不同。

        spread_bps  —— 穿越价差的成本。改善方式：被动挂单
        impact_bps  —— 你自己的成交把价格推走的部分。改善方式：拆单、限制参与率
        timing_bps  —— 从决策到成交期间市场自己的漂移。改善方式：缩短决策-执行时滞
        """
        a = self.arrival_price
        if a <= 0:
            return {}
        total = self.signed * (self.fill_price - a) / a * 1e4
        # 相对区间 VWAP 的偏离 = 你的执行相对"市场平均价"的好坏
        impact = self.signed * (self.fill_price - self.interval_vwap) / a * 1e4
        # 区间 VWAP 相对决策价的漂移 = 时机成本（市场自己走的）
        timing = self.signed * (self.interval_vwap - a) / a * 1e4
        return {
            "total_bps": total,
            "impact_bps": impact,
            "timing_bps": timing,
            "notional": self.shares * self.fill_price,
        }


def attribution(fills: list[Fill]) -> pd.DataFrame:
    """一批成交的成本归因汇总。按金额加权，因为大单的成本更重要。"""
    rows = [{"code": f.code, "side": f.side, **f.decompose()} for f in fills]
    df = pd.DataFrame([r for r in rows if r.get("notional")])
    if df.empty:
        return df
    w = df["notional"] / df["notional"].sum()
    summary = pd.DataFrame([{
        "笔数": len(df),
        "总金额": df["notional"].sum(),
        "总滑点(bp)": float((df["total_bps"] * w).sum()),
        "其中冲击(bp)": float((df["impact_bps"] * w).sum()),
        "其中时机(bp)": float((df["timing_bps"] * w).sum()),
        "最差单笔(bp)": float(df["total_bps"].max()),
    }])
    return summary


# --------------------------------------------------------------------------
@dataclass
class BookSnapshot:
    """某一时刻的盘口。只需要前几档就够做挂单决策。"""

    bid_prices: list[float]
    bid_vols: list[float]
    ask_prices: list[float]
    ask_vols: list[float]

    @property
    def mid(self) -> float:
        if not self.bid_prices:
            return self.ask_prices[0] if self.ask_prices else float("nan")
        if not self.ask_prices:
            return self.bid_prices[0]
        return (self.bid_prices[0] + self.ask_prices[0]) / 2

    @property
    def spread(self) -> float:
        if not self.bid_prices or not self.ask_prices:
            return float("nan")
        return self.ask_prices[0] - self.bid_prices[0]

    @property
    def spread_bps(self) -> float:
        return self.spread / self.mid * 1e4 if self.mid > 0 else np.nan

    @property
    def n_levels(self) -> int:
        """实际可用档位数。A 股涨跌停时一侧盘口会完全为空。"""
        return min(len(self.bid_prices), len(self.ask_prices))

    @property
    def one_sided(self) -> str | None:
        """返回枯竭的一侧：'bid' 表示无买盘（跌停），'ask' 表示无卖盘（涨停）。"""
        if not self.bid_prices or self.bid_vols and sum(self.bid_vols) <= 0:
            return "bid"
        if not self.ask_prices or self.ask_vols and sum(self.ask_vols) <= 0:
            return "ask"
        return None

    @property
    def imbalance(self) -> float:
        """盘口失衡 ∈ [-1, 1]。正值 = 买盘厚 = 短期上行压力。"""
        b, a = sum(self.bid_vols), sum(self.ask_vols)
        return (b - a) / (b + a) if (b + a) > 0 else 0.0

    def depth_ahead(self, side: Literal["buy", "sell"], level: int) -> float:
        """挂在第 level 档时，排在你前面的委托量（决定成交概率）。"""
        vols = self.bid_vols if side == "buy" else self.ask_vols
        return float(sum(vols[:level]))


@dataclass
class PlacementPolicy:
    """挂单策略参数。默认值偏保守 —— 宁可多付一点价差，也不要拿不到货。"""

    max_participation: float = 0.05     # 单笔不超过区间成交量的 5%
    urgency: float = 0.5                # 0=纯被动 1=立即成交
    max_wait_seconds: int = 300         # 超时后转市价，防止踏空
    adverse_selection_bps: float = 3.0  # 被动成交的逆向选择成本估计


def choose_placement(
    book: BookSnapshot,
    side: Literal["buy", "sell"],
    policy: PlacementPolicy | None = None,
) -> dict:
    """给定盘口，决定挂单价位。

    返回挂单价、预期成本（含逆向选择）、以及各候选方案的对比。
    这个函数的价值不在于它选了哪个，而在于它把**逆向选择**明码标价了。
    """
    policy = policy or PlacementPolicy()
    mid = book.mid
    if not np.isfinite(mid) or mid <= 0:
        return {}

    # 涨跌停：一侧盘口枯竭。这不是异常情况，是 A 股每天都在发生的事，
    # 而且恰恰是最需要这个函数的时候 —— 必须给出明确结论而不是崩掉。
    starved = book.one_sided
    if starved == "ask" and side == "buy":
        return {"推荐方案": "放弃买入（涨停无卖盘）", "挂单价": float("nan"),
                "期望成本bp": float("nan"), "盘口价差bp": book.spread_bps,
                "盘口失衡": book.imbalance,
                "备注": "一字涨停，挂单排队也大概率买不到。追板不在本系统的策略范围内。",
                "候选对比": pd.DataFrame()}
    if starved == "bid" and side == "sell":
        return {"推荐方案": "无法卖出（跌停无买盘）", "挂单价": float("nan"),
                "期望成本bp": float("nan"), "盘口价差bp": book.spread_bps,
                "盘口失衡": book.imbalance,
                "备注": "一字跌停，今日卖不掉。风控层应据此顺延，不要假装已清仓。",
                "候选对比": pd.DataFrame()}

    candidates = []
    # 方案 0：立即成交（吃对手价）
    opposite = book.ask_prices if side == "buy" else book.bid_prices
    if not opposite:
        return {}
    cross_px = opposite[0]
    candidates.append({
        "方案": "立即成交(吃单)",
        "价格": cross_px,
        "价差成本bp": abs(cross_px - mid) / mid * 1e4,
        "逆向选择bp": 0.0,           # 主动成交不承担逆向选择
        "成交概率": 1.00,
    })

    # 方案 1~N：被动挂在第 1~N 档。N 取盘口实际深度，最多 3 档 ——
    # 流动性差的股票可能只有一两档，硬取第 3 档会 IndexError。
    own_side = book.bid_prices if side == "buy" else book.ask_prices
    for lvl in range(1, min(3, len(own_side)) + 1):
        px = own_side[lvl - 1]
        ahead = book.depth_ahead(side, lvl)
        # 成交概率随排队深度衰减；盘口失衡对你有利时概率提升
        favorable = book.imbalance * (-1 if side == "buy" else 1)
        p_fill = float(np.clip(np.exp(-ahead / 3e5) * (1 + 0.3 * favorable), 0.05, 0.95))
        # 被动挂单省下价差，但承担逆向选择：越被动、逆向选择越重
        adverse = policy.adverse_selection_bps * lvl
        candidates.append({
            "方案": f"被动挂第{lvl}档",
            "价格": px,
            "价差成本bp": -abs(mid - px) / mid * 1e4,     # 负数 = 相对中间价占便宜
            "逆向选择bp": adverse,
            "成交概率": p_fill,
        })

    df = pd.DataFrame(candidates)
    # 期望成本 = 成交时的成本 × 成交概率 + 未成交转市价的成本 × (1-成交概率)
    fallback_cost = abs(cross_px - mid) / mid * 1e4 + 2.0    # 超时转市价还要付追价成本
    df["期望成本bp"] = (
        (df["价差成本bp"] + df["逆向选择bp"]) * df["成交概率"]
        + fallback_cost * (1 - df["成交概率"])
    )
    # 紧急度加权：urgency 高时惩罚低成交概率
    df["调整后bp"] = df["期望成本bp"] + policy.urgency * 20 * (1 - df["成交概率"])

    best = df.loc[df["调整后bp"].idxmin()]
    return {
        "推荐方案": best["方案"],
        "挂单价": float(best["价格"]),
        "期望成本bp": float(best["期望成本bp"]),
        "盘口价差bp": book.spread_bps,
        "盘口失衡": book.imbalance,
        "候选对比": df.round(2),
    }


def savings_estimate(
    baseline_slippage_bps: float,
    optimized_slippage_bps: float,
    annual_turnover: float,
) -> dict:
    """把滑点改善换算成年化收益。

    这是唯一该用来判断"L2 权限值不值那笔钱"的算式。
    """
    saved_per_side = baseline_slippage_bps - optimized_slippage_bps
    # 年换手 N 倍 = 一年买卖各 N 次
    annual_saving = saved_per_side * 2 * annual_turnover / 1e4
    return {
        "单边滑点改善bp": saved_per_side,
        "年化节省": annual_saving,
        "年换手": annual_turnover,
        "说明": f"年换手 {annual_turnover:.1f}x 下，单边省 {saved_per_side:.1f}bp "
                f"折合年化 {annual_saving:.2%}",
    }
