"""风控规则（实盘可用）。

为什么单独一个模块：回测引擎内部有一套风控逻辑，但实盘走的是
premarket 脚本这条路。如果两边的止损规则不是同一份代码，
它们迟早会漂移 —— 然后你的实盘会以你没预期的方式亏钱。

这个模块把风控抽成纯函数，回测和实盘共用同一份判定。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..config import RiskConfig


@dataclass
class Position:
    """一笔实盘持仓。价格一律用后复权口径，否则除权日会误触发止损。"""

    code: str
    shares: float
    cost_basis: float          # 加权平均成本（后复权）
    peak_price: float          # 持仓期最高价（后复权）
    entry_date: date
    current_price: float       # 最新价（后复权）

    @property
    def pnl_pct(self) -> float:
        return self.current_price / self.cost_basis - 1 if self.cost_basis > 0 else 0.0

    @property
    def drawdown_from_peak(self) -> float:
        return self.current_price / self.peak_price - 1 if self.peak_price > 0 else 0.0

    def holding_days(self, today: date) -> int:
        return (today - self.entry_date).days


def check_position(pos: Position, today: date, cfg: RiskConfig | None = None) -> dict:
    """单票风控检查。返回是否需要卖出及原因。"""
    cfg = cfg or RiskConfig()
    reasons = []
    if pos.pnl_pct <= -cfg.stop_loss_pct:
        reasons.append(f"止损：自成本价 {pos.pnl_pct:.1%}，已穿透 {-cfg.stop_loss_pct:.0%}")
    if pos.drawdown_from_peak <= -cfg.trailing_stop_pct:
        reasons.append(f"移动止盈：自最高价回撤 {pos.drawdown_from_peak:.1%}")
    if pos.holding_days(today) > cfg.max_holding_days:
        reasons.append(f"超期：已持有 {pos.holding_days(today)} 天，上限 {cfg.max_holding_days}")
    return {"code": pos.code, "should_exit": bool(reasons), "reasons": reasons,
            "pnl_pct": pos.pnl_pct, "drawdown_from_peak": pos.drawdown_from_peak}


def check_portfolio(equity_curve: pd.Series, cfg: RiskConfig | None = None) -> dict:
    """组合层风控：回撤分档处理。

    三档而非一刀切，因为一刀切的熔断会在阈值附近反复触发，
    反而制造额外的换手成本。
    """
    cfg = cfg or RiskConfig()
    eq = equity_curve.dropna()
    if len(eq) < 2:
        return {"level": "normal", "position_multiplier": 1.0, "drawdown": 0.0, "action": "正常"}

    dd = float(eq.iloc[-1] / eq.cummax().iloc[-1] - 1)
    if dd <= -cfg.portfolio_dd_halt:
        return {"level": "halt", "position_multiplier": 0.0, "drawdown": dd,
                "action": f"熔断：清仓并停止开新仓 {cfg.halt_cooldown_days} 个交易日"}
    if dd <= -cfg.portfolio_dd_derisk:
        return {"level": "derisk", "position_multiplier": 0.5, "drawdown": dd,
                "action": "降仓：目标仓位减半"}
    if dd <= -cfg.portfolio_dd_warn:
        return {"level": "warn", "position_multiplier": 0.75, "drawdown": dd,
                "action": "预警：目标仓位降至 75%"}
    return {"level": "normal", "position_multiplier": 1.0, "drawdown": dd, "action": "正常"}


def check_crowding(factor_crowding_z: float, cfg: RiskConfig | None = None) -> dict:
    """因子拥挤度检查。

    拥挤度不预测收益，它预测"崩起来有多快"。2024 年 1 月微盘股踩踏前，
    微盘因子的拥挤度就在历史极值 —— 当所有人的持仓高度重合，
    任何一个人的止损都会变成所有人的止损。
    """
    cfg = cfg or RiskConfig()
    if not np.isfinite(factor_crowding_z):
        return {"crowded": False, "action": "数据不足"}
    if factor_crowding_z >= cfg.crowding_zscore_halt:
        return {"crowded": True, "z": factor_crowding_z,
                "action": f"拥挤度 z={factor_crowding_z:.2f} 超过 {cfg.crowding_zscore_halt}，"
                          f"建议停用该因子或减半权重"}
    if factor_crowding_z >= cfg.crowding_zscore_halt * 0.7:
        return {"crowded": False, "z": factor_crowding_z,
                "action": f"拥挤度 z={factor_crowding_z:.2f} 偏高，密切关注"}
    return {"crowded": False, "z": factor_crowding_z, "action": "正常"}


def daily_risk_report(positions: list[Position], equity_curve: pd.Series,
                      today: date, cfg: RiskConfig | None = None) -> dict:
    """盘前风控总检。这是 premarket 清单之外必须跑的一步。"""
    cfg = cfg or RiskConfig()
    pos_checks = [check_position(p, today, cfg) for p in positions]
    exits = [c for c in pos_checks if c["should_exit"]]
    port = check_portfolio(equity_curve, cfg)
    return {
        "portfolio": port,
        "forced_exits": exits,
        "n_positions": len(positions),
        "worst_position": min(pos_checks, key=lambda c: c["pnl_pct"]) if pos_checks else None,
    }


def render_risk_report(rep: dict) -> str:
    lines = ["【风控检查】"]
    p = rep["portfolio"]
    lines.append(f"  组合回撤 {p['drawdown']:.2%} → {p['action']}")
    if p["position_multiplier"] < 1.0:
        lines.append(f"  今日目标仓位需乘以 {p['position_multiplier']:.0%}")
    if rep["forced_exits"]:
        lines.append(f"  强制卖出 {len(rep['forced_exits'])} 只（优先于任何调仓信号）：")
        for e in rep["forced_exits"]:
            lines.append(f"    {e['code']}  " + "；".join(e["reasons"]))
    else:
        lines.append("  无触发止损的持仓")
    return "\n".join(lines)
