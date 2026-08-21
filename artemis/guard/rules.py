"""排雷层：在选股之前先把地雷剔掉。

核心信念：对散户来说，避开 -50% 的票，比找到 +50% 的票更值钱，
而且更容易做到。找 alpha 是跟全市场最聪明的人竞争；避雷主要是
跟自己的贪婪竞争，胜率高得多。

每条规则都返回 (mask, reason)，并且整层是可度量的：
audit() 会告诉你每条规则剔掉的股票后续表现如何 —— 如果一条规则
剔掉的股票后来涨得更好，那它就是在帮倒忙，应该删掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..config import GuardConfig

# 规则签名：(bars, cfg) -> Series[bool]，True 表示"排除"
RuleFn = Callable[[pd.DataFrame, GuardConfig], pd.Series]

_REGISTRY: dict[str, RuleFn] = {}


def rule(name: str):
    def deco(fn: RuleFn) -> RuleFn:
        _REGISTRY[name] = fn
        fn.rule_name = name  # type: ignore[attr-defined]
        return fn
    return deco


# --------------------------------------------------------------------------
# 规则定义
# --------------------------------------------------------------------------

@rule("st")
def _st(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """ST/*ST：涨跌停只有 5%，流动性差，退市概率高，且是财务造假重灾区。"""
    if not cfg.exclude_st:
        return pd.Series(False, index=bars.index)
    return bars["is_st"].astype(bool)


@rule("suspended")
def _suspended(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """停牌：买不进也卖不出。停牌股在回测里是最常见的未来函数来源。"""
    if not cfg.exclude_suspended:
        return pd.Series(False, index=bars.index)
    return bars["is_suspended"].astype(bool)


@rule("new_listing")
def _new_listing(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """次新股：没有历史数据可算因子，且上市初期波动极大、估值虚高。"""
    return bars["days_since_ipo"] < cfg.min_days_since_ipo


@rule("illiquid")
def _illiquid(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """流动性不足：2024 年 1 月微盘股踩踏的核心教训。

    流动性不是"平时够用就行"—— 它在你最需要卖出的那天会消失。
    用 20 日均额而非当日额，避免被单日异动骗过去。
    """
    adv20 = (
        bars["amount"].groupby(level="code", group_keys=False)
        .rolling(20, min_periods=10).mean().droplevel(0)
    )
    adv20 = adv20.reindex(bars.index)
    return adv20 < cfg.min_adv20


@rule("micro_cap")
def _micro_cap(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """市值过小：2024 年退市新规把市值退市红线抬到 3 亿（主板 5 亿）。

    小市值曾是 A 股最强的因子之一，但它的超额收益里有很大一块是
    "壳价值"和"流动性溢价"，注册制+严退市之后这块正在系统性消失。
    """
    return bars["total_mv"] < cfg.min_market_cap


@rule("limit_up_chase")
def _limit_up_chase(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """当日涨停：买不进（一字板），或买进就是接盘。禁止追板。"""
    ret = bars["close"] / bars["prev_close"] - 1
    # 用一个略宽松的阈值统一覆盖 5%/10%/20%/30% 各板块
    codes = bars.index.get_level_values("code")
    from ..rules import price_limit_pct
    lim = pd.Series(
        [price_limit_pct(c, bool(st)) for c, st in zip(codes, bars["is_st"].values)],
        index=bars.index,
    )
    return ret >= lim - 0.005


@rule("price_floor")
def _price_floor(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """低价股：面值退市（连续 20 日收盘 < 1 元）的候选，且波动被最小变动
    单位放大（1 分钱在 2 元股上是 0.5%）。"""
    return bars["close"] < 2.0


@rule("extreme_run_up")
def _extreme_run_up(bars: pd.DataFrame, cfg: GuardConfig) -> pd.Series:
    """短期暴涨：20 日涨幅 > 60% 的票，均值回复的风险远大于动量延续。"""
    px = bars["close"].unstack("code")
    runup = (px / px.shift(20) - 1).stack(future_stack=True)
    return runup.reindex(bars.index).fillna(0) > 0.60


def available_rules() -> list[str]:
    return list(_REGISTRY)


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------

@dataclass
class GuardResult:
    mask: pd.Series                 # True = 可交易（已通过全部排雷）
    detail: pd.DataFrame            # 每条规则的排除标记
    summary: pd.DataFrame           # 每条规则的剔除比例

    @property
    def tradable_ratio(self) -> float:
        return float(self.mask.mean())


class Guard:
    """排雷引擎。"""

    def __init__(self, cfg: GuardConfig | None = None, rules: list[str] | None = None):
        self.cfg = cfg or GuardConfig()
        self.rules = rules or available_rules()

    def apply(self, bars: pd.DataFrame) -> GuardResult:
        detail = {}
        for name in self.rules:
            fn = _REGISTRY[name]
            m = fn(bars, self.cfg)
            detail[name] = m.reindex(bars.index).fillna(True).astype(bool)
        detail_df = pd.DataFrame(detail, index=bars.index)
        excluded = detail_df.any(axis=1)

        summary = pd.DataFrame({
            "excluded_pct": detail_df.mean().mul(100).round(2),
            "unique_excluded_pct": pd.Series({
                n: float((detail_df[n] & ~detail_df.drop(columns=[n]).any(axis=1)).mean() * 100)
                for n in detail_df.columns
            }).round(2),
        }).sort_values("excluded_pct", ascending=False)

        return GuardResult(mask=~excluded, detail=detail_df, summary=summary)

    # ----------------------------------------------------------------------
    def audit(self, bars: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
        """度量每条规则的价值：被剔除的股票，后续 horizon 日表现如何？

        解读方式：
          excl_fwd_ret  被剔除样本的未来收益均值
          kept_fwd_ret  保留样本的未来收益均值
          edge          kept - excl，正数越大说明这条规则越有价值
          tail_saved    被剔除样本里未来跌超 20% 的比例 —— 这是"避雷"的直接证据

        如果某条规则 edge 显著为负，说明它在帮倒闲，应当删除而不是保留。
        规则的价值主要体现在 tail_saved 上，而不是均值上。
        """
        res = self.apply(bars)
        px = bars["close"].unstack("code")
        fwd = (px.shift(-horizon) / px - 1).stack(future_stack=True).reindex(bars.index)

        rows = []
        for name in res.detail.columns:
            m = res.detail[name]
            excl, kept = fwd[m].dropna(), fwd[~m].dropna()
            if len(excl) == 0:
                continue
            rows.append({
                "rule": name,
                "n_excluded": int(m.sum()),
                "excl_pct": round(float(m.mean()) * 100, 2),
                "excl_fwd_ret": round(float(excl.mean()) * 100, 2),
                "kept_fwd_ret": round(float(kept.mean()) * 100, 2),
                "edge": round(float(kept.mean() - excl.mean()) * 100, 2),
                "tail_saved": round(float((excl < -0.20).mean()) * 100, 2),
                "tail_base": round(float((kept < -0.20).mean()) * 100, 2),
            })
        out = pd.DataFrame(rows).sort_values("edge", ascending=False)
        out.attrs["horizon"] = horizon
        return out
