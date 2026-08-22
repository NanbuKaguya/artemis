"""盘前工作流：09:00 跑一次，产出今日交易清单。

设计原则：盘前的产出必须是一份**可以直接执行的清单**，而不是一堆图表。
如果盘前工作的结论需要你临场再判断一次，那纪律就已经破了。
"""
from __future__ import annotations

import sys, warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from artemis.config import ArtemisConfig
from artemis.guard.rules import Guard
from artemis.alpha import factors as F
from artemis.portfolio.construct import build_weights, combine_factors
from artemis.regime.market_state import RegimeModel
from artemis.rules import price_limit_pct, round_limit_price
from artemis.risk.controls import Position, daily_risk_report, render_risk_report
from artemis.data.preflight import check as preflight_check

FACTORS = ["momentum_120_20", "low_vol_60", "turnover_20", "vol_price_corr"]


def premarket_plan(bars: pd.DataFrame, current_holdings: dict[str, float] | None = None,
                   cfg: ArtemisConfig | None = None,
                   positions: list[Position] | None = None,
                   equity_curve: pd.Series | None = None) -> dict:
    """产出今日执行清单。

    bars 必须只包含截至**昨日收盘**的数据 —— 今天的数据你还不知道。
    这个约束由调用方保证；引擎会再校验一次日期上界。
    """
    cfg = cfg or ArtemisConfig()
    current_holdings = current_holdings or {}
    last_date = bars.index.get_level_values("date").max()

    # 0) 数据体检。放在最前面，因为数据缺口造成的失效是静默的 ——
    #    排雷规则会照样返回"剔除 0%"，中性化会照样返回一条正常序列。
    pf = preflight_check(bars)
    data_issues = pf[pf.status != "ok"][["capability", "status", "detail"]].to_dict("records")

    # 1) 排雷
    guard = Guard(cfg.guard)
    gres = guard.apply(bars)
    mask = gres.mask

    # 2) 风控总检 —— 必须在择时之前，因为它可以直接把仓位打到 0
    risk_rep = None
    risk_mult = 1.0
    forced_exit_codes: set[str] = set()
    if positions is not None and equity_curve is not None:
        risk_rep = daily_risk_report(positions, equity_curve, last_date.date(), cfg.risk)
        risk_mult = risk_rep["portfolio"]["position_multiplier"]
        forced_exit_codes = {e["code"] for e in risk_rep["forced_exits"]}

    # 3) 择时 -> 今日目标总仓位
    regime = RegimeModel(cfg.regime).fit_transform(bars)
    target_pos = float(regime.target_position.loc[last_date]) * risk_mult
    state = str(regime.state.loc[last_date])

    # 4) 选股
    raw = F.compute(bars, FACTORS)
    prep = pd.DataFrame({c: F.prepare(raw[c], bars) for c in raw.columns}, index=bars.index)
    score = combine_factors(prep)
    weights = build_weights(score, bars, mask=mask, cfg=cfg.portfolio)
    target_w = weights.loc[last_date]
    target_w = target_w[target_w > 0] * target_pos
    # 强制止损的票，无论信号如何一律清零 —— 风控优先于 alpha
    if forced_exit_codes:
        target_w = target_w.drop(index=[c for c in forced_exit_codes if c in target_w.index])

    # 5) 生成买卖清单
    today_bars = bars.loc[last_date]
    orders = []
    all_codes = set(target_w.index) | set(current_holdings)
    for code in sorted(all_codes):
        tgt = float(target_w.get(code, 0.0))
        cur = float(current_holdings.get(code, 0.0))
        diff = tgt - cur
        if abs(diff) < 0.005:
            continue
        row = today_bars.loc[code] if code in today_bars.index else None
        prev_close = float(row["close"]) if row is not None else np.nan
        is_st = bool(row["is_st"]) if row is not None else False
        lim = price_limit_pct(code, is_st)
        orders.append({
            "code": code,
            "action": "买入" if diff > 0 else "卖出",
            "target_pct": round(tgt * 100, 2),
            "current_pct": round(cur * 100, 2),
            "delta_pct": round(diff * 100, 2),
            "prev_close": round(prev_close, 2) if prev_close == prev_close else None,
            "limit_up": round_limit_price(prev_close, lim, True) if prev_close == prev_close else None,
            "limit_down": round_limit_price(prev_close, lim, False) if prev_close == prev_close else None,
            "note": "涨停则放弃买入" if diff > 0 else "跌停则次日再卖",
        })

    return {
        "date": str(last_date.date()),
        "market_state": state,
        "regime_score": round(float(regime.score.loc[last_date]), 3),
        "target_position": target_pos,
        "universe_size": int(mask.loc[last_date].sum()) if last_date in mask.index.get_level_values("date") else 0,
        "orders": orders,
        "guard_summary": gres.summary.to_dict("index"),
        "risk": risk_rep,
        "data_issues": data_issues,
    }


def render(plan: dict) -> str:
    lines = [
        "=" * 64,
        f"  盘前清单  {plan['date']}",
        "=" * 64,
        f"市场状态   : {plan['market_state']}  (健康分 {plan['regime_score']})",
        f"目标总仓位 : {plan['target_position']:.0%}",
        f"可交易股票 : {plan['universe_size']} 只（已排雷）",
        "",
    ]
    if plan.get("data_issues"):
        lines.append("【数据体检】以下能力已失效或降级，相关结论不可信：")
        for d in plan["data_issues"]:
            mark = "✗" if d["status"] == "dead" else "▲"
            lines.append(f"  {mark} {d['capability']}: {d['detail']}")
        lines.append("")
    if plan.get("risk"):
        lines.append(render_risk_report(plan["risk"]))
        lines.append("")
    if not plan["orders"]:
        lines.append("今日无需调仓。什么都不做也是一种执行。")
    else:
        lines.append(f"{'代码':<10}{'动作':<6}{'目标%':>7}{'当前%':>7}{'变动%':>7}"
                     f"{'昨收':>8}{'涨停':>8}{'跌停':>8}  备注")
        lines.append("-" * 90)
        for o in plan["orders"]:
            lines.append(
                f"{o['code']:<10}{o['action']:<6}{o['target_pct']:>7.2f}{o['current_pct']:>7.2f}"
                f"{o['delta_pct']:>7.2f}{o['prev_close'] or 0:>8.2f}"
                f"{o['limit_up'] or 0:>8.2f}{o['limit_down'] or 0:>8.2f}  {o['note']}"
            )
    lines += ["", "纪律提醒：", "  1. 清单之外的票一律不碰",
              "  2. 涨停买不进就放弃，不要追高", "  3. 下单前先在 journal 里写清买入理由和失效条件"]
    return "\n".join(lines)


if __name__ == "__main__":
    from artemis.data.synthetic import make_market
    bars, _ = make_market(n_stocks=200, n_days=700, seed=5)
    holdings = {}
    print(render(premarket_plan(bars, holdings)))
