"""财务数据的 point-in-time 对齐引擎。

这是接真实数据之后**最容易悄悄毁掉整个回测**的地方。合成数据里不存在
这些问题，所以它们要到你接上真实财务数据的那一刻才会出现 —— 而且不会报错，
只会让你的回测凭空多出一大块 alpha。

三个必须处理的坑：

1. **公告日 ≠ 报告期**
   2023 年三季报的报告期是 2023-09-30，但公告日可能是 2023-10-28。
   在 10-28 之前，市场不知道这份报表。用报告期对齐 = 未来函数，
   而且是最肥的那种：你提前一个月知道了业绩。

2. **A 股利润表和现金流量表是累计值（YTD），不是单季值**
   一季报的"净利润"是 Q1 的，中报的是 Q1+Q2 的，三季报是 Q1+Q2+Q3 的。
   直接拿它算 TTM 会得到荒谬的数字。必须先做累计转单季。
   资产负债表是时点值，不需要转换 —— 两类字段要分开处理。

3. **追溯调整（restatement）**
   同一个报告期会被多次公告，后一次修正前一次。PIT 的定义是
   "在 T 时刻你所知道的值"，所以必须取 ann_date <= T 的最新那一版，
   而不是数据库里最终那一版。用最终版做回测 = 你提前知道了会计差错更正。

实现方式：在每个"公告事件"上重算一次 TTM，得到 (ann_date, value) 序列，
再用 merge_asof 贴到日频网格上。复杂度是 O(公告数) 而不是 O(日期数×股票数)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import numpy as np
import pandas as pd

FieldKind = Literal["flow", "stock"]

# 常见字段的类型。flow = 累计值需转单季；stock = 时点值直接用。
FIELD_KIND: dict[str, FieldKind] = {
    # 利润表（累计）
    "revenue": "flow", "net_profit": "flow", "net_profit_deduct": "flow",
    "operating_profit": "flow", "total_profit": "flow", "gross_profit": "flow",
    # 现金流量表（累计）
    "ocf": "flow", "icf": "flow", "fcf": "flow",
    # 资产负债表（时点）
    "total_assets": "stock", "total_equity": "stock", "total_liab": "stock",
    "goodwill": "stock", "monetary_funds": "stock", "inventory": "stock",
    "accounts_receivable": "stock",
}

PIT_COLUMNS = ["code", "report_period", "ann_date", "field", "value"]


class PITError(ValueError):
    pass


def validate_pit(df: pd.DataFrame) -> pd.DataFrame:
    """校验财务长表。缺 ann_date 的数据一律拒收 —— 没有公告日就无法做 PIT。"""
    missing = [c for c in PIT_COLUMNS if c not in df.columns]
    if missing:
        raise PITError(
            f"财务长表缺少必需列 {missing}。特别注意 ann_date：\n"
            f"没有公告日的财务数据无法做 point-in-time 对齐，用它回测等于开了未来函数。\n"
            f"AkShare 的 stock_yjbb_em / stock_lrb_em 带'最新公告日期'；\n"
            f"Tushare 的 income/balancesheet 接口带 ann_date 和 f_ann_date。"
        )
    out = df.copy()
    out["report_period"] = pd.to_datetime(out["report_period"])
    out["ann_date"] = pd.to_datetime(out["ann_date"])
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")

    bad = out["ann_date"] < out["report_period"]
    if bad.any():
        n = int(bad.sum())
        # 公告日早于报告期是数据错误，直接丢弃比"修正"安全
        out = out[~bad]
        print(f"  [PIT] 丢弃 {n} 行公告日早于报告期的记录（数据源错误）")

    return out.sort_values(["code", "field", "ann_date", "report_period"]).reset_index(drop=True)


def _quarter_index(period: pd.Timestamp) -> int:
    """报告期 → 该年的第几季（1-4）。"""
    return (period.month - 1) // 3 + 1


def cumulative_to_single(periods: pd.Series, values: pd.Series) -> pd.Series:
    """累计值 → 单季值。

    A 股一季报/中报/三季报/年报的利润表都是年初至今的累计数：
      Q1单季 = Q1累计
      Q2单季 = H1累计 − Q1累计
      Q3单季 = Q3累计 − H1累计
      Q4单季 = 年报累计 − Q3累计

    缺失中间季度时返回 NaN，而不是猜一个值 —— 猜出来的数字会变成假因子。
    """
    df = pd.DataFrame({"p": pd.to_datetime(periods), "v": values}).sort_values("p")
    df["year"] = df["p"].dt.year
    df["q"] = df["p"].map(_quarter_index)
    out = []
    for _, g in df.groupby("year", sort=True):
        g = g.sort_values("q")
        prev_q, prev_v = 0, 0.0
        for _, r in g.iterrows():
            if r["q"] == 1:
                out.append((r["p"], r["v"]))
                prev_q, prev_v = 1, r["v"]
            elif r["q"] == prev_q + 1:
                out.append((r["p"], r["v"] - prev_v))
                prev_q, prev_v = r["q"], r["v"]
            else:
                # 中间有季度缺失，无法还原单季值
                out.append((r["p"], np.nan))
                prev_q, prev_v = r["q"], r["v"]
    res = pd.Series(dict(out), name="single_q")
    res.index = pd.to_datetime(res.index)
    return res.sort_index()


@dataclass
class _KnownState:
    """某只股票在某个时刻"已知的"财务状态：{报告期: 最新已知值}。"""

    values: dict[pd.Timestamp, float]

    def update(self, period: pd.Timestamp, value: float) -> None:
        # 追溯调整：后来的公告直接覆盖同一报告期的旧值
        self.values[period] = value

    def ttm(self, kind: FieldKind) -> float:
        """按当前已知状态计算 TTM（flow）或取最新时点值（stock）。"""
        if not self.values:
            return np.nan
        periods = sorted(self.values)
        if kind == "stock":
            return self.values[periods[-1]]

        singles = cumulative_to_single(
            pd.Series(periods), pd.Series([self.values[p] for p in periods])
        )
        singles = singles.dropna()
        if len(singles) < 4:
            return np.nan
        return float(singles.iloc[-4:].sum())

    def latest_period(self) -> pd.Timestamp | None:
        return max(self.values) if self.values else None


def build_pit_series(
    pit: pd.DataFrame,
    field: str,
    kind: FieldKind | None = None,
    min_report_lag_days: int = 0,
) -> pd.DataFrame:
    """把某个财务字段折叠成"公告事件 → 当时已知的 TTM/时点值"。

    返回 columns=[code, ann_date, value, report_period]，按 (code, ann_date) 排序。
    这个中间产物才是可以安全 merge_asof 到日频的东西。

    min_report_lag_days: 额外的保守滞后。有些数据源的公告日期本身就不可靠，
    加 1~2 天的缓冲能避免"当天盘中就用上当晚才披露的数据"。
    """
    kind = kind or FIELD_KIND.get(field, "flow")
    # 防御性校验：这是公开入口，不能假设调用方已经跑过 validate_pit。
    # 日期列若还是字符串，后面的时间推进会静默出错。
    if not pd.api.types.is_datetime64_any_dtype(pit.get("ann_date", pd.Series(dtype=object))):
        pit = validate_pit(pit)
    sub = pit[pit["field"] == field]
    if sub.empty:
        return pd.DataFrame(columns=["code", "ann_date", "value", "report_period"])

    rows = []
    for code, g in sub.groupby("code", sort=False):
        state = _KnownState(values={})
        # 按公告日推进 —— 这就是"时间的箭头"
        for ann_date, gg in g.sort_values("ann_date").groupby("ann_date", sort=True):
            for _, r in gg.iterrows():
                state.update(r["report_period"], r["value"])
            eff = ann_date + pd.Timedelta(days=min_report_lag_days)
            rows.append({
                "code": code,
                "ann_date": eff,
                "value": state.ttm(kind),
                "report_period": state.latest_period(),
            })
    out = pd.DataFrame(rows)
    return out.sort_values(["code", "ann_date"]).reset_index(drop=True)


def align_to_bars(
    pit: pd.DataFrame,
    bars: pd.DataFrame,
    fields: Iterable[str],
    min_report_lag_days: int = 0,
) -> pd.DataFrame:
    """把财务字段按 PIT 规则贴到日频行情网格上。

    返回 DataFrame，index 与 bars 一致，每个 field 一列。
    任何 T 日的值都只依赖 ann_date <= T 的公告。
    """
    pit = validate_pit(pit)
    idx = bars.index
    # merge_asof 要求左右两边都按 on 键（date）全局排序，by= 分组不豁免这一点
    grid = idx.to_frame(index=False)[["date", "code"]].sort_values("date", kind="stable")

    out = {}
    for field in fields:
        ser = build_pit_series(pit, field, min_report_lag_days=min_report_lag_days)
        if ser.empty:
            out[field] = pd.Series(np.nan, index=idx)
            continue
        right = (ser[["code", "ann_date", "value"]]
                 .rename(columns={"ann_date": "date"})
                 .sort_values("date", kind="stable"))
        merged = pd.merge_asof(
            grid, right, on="date", by="code",
            direction="backward", allow_exact_matches=True,
        )
        s = merged.set_index(["date", "code"])["value"]
        out[field] = s.reindex(idx)

    return pd.DataFrame(out, index=idx)


def staleness_days(
    pit: pd.DataFrame, bars: pd.DataFrame, field: str
) -> pd.Series:
    """每个 (date, code) 上，所用财务数据距今多少天。

    用途：财报数据在年报季前会变得很陈旧（4 月初用的还是去年三季报，
    已经陈旧 180 天以上）。基于它的因子在这些时段有效性会系统性下降 ——
    监控它能解释一部分"因子为什么在某些月份突然失效"。
    """
    ser = build_pit_series(pit, field)
    if ser.empty:
        return pd.Series(np.nan, index=bars.index, name="staleness_days")

    grid = bars.index.to_frame(index=False)[["date", "code"]].sort_values("date", kind="stable")
    right = (ser[["code", "ann_date"]]
             .assign(last_ann=ser["ann_date"])
             .rename(columns={"ann_date": "date"})
             .sort_values("date", kind="stable"))
    merged = pd.merge_asof(grid, right, on="date", by="code", direction="backward")
    merged["staleness_days"] = (merged["date"] - merged["last_ann"]).dt.days
    return (merged.set_index(["date", "code"])["staleness_days"]
            .reindex(bars.index).rename("staleness_days"))


# --------------------------------------------------------------------------
# 合成财务数据：用于验证 PIT 引擎本身
# --------------------------------------------------------------------------
def make_synthetic_pit(
    codes: Iterable[str],
    start: str = "2016-01-01",
    end: str = "2021-12-31",
    seed: int = 0,
    restatement_prob: float = 0.08,
) -> pd.DataFrame:
    """生成带真实公告节奏和追溯调整的合成财务数据。

    公告节奏参照 A 股实际规定：
      一季报  4/30 前
      中报    8/31 前
      三季报  10/31 前
      年报    次年 4/30 前
    """
    rng = np.random.default_rng(seed)
    codes = list(codes)
    rows = []

    periods = pd.date_range(start, end, freq="QE")
    # 各报告期的法定披露截止日（相对报告期末的天数）
    deadline_days = {1: 30, 2: 61, 3: 31, 4: 120}

    for code in codes:
        base_rev = rng.lognormal(np.log(8e8), 0.9)
        base_margin = rng.uniform(0.03, 0.22)
        growth = rng.normal(0.02, 0.05)

        for p in periods:
            q = _quarter_index(p)
            # 累计值：季数 × 单季基准 × (1+累计增长) × 噪音
            cum_scale = q * (1 + growth) ** ((p.year - periods[0].year) + q / 4)
            rev = base_rev * cum_scale * rng.lognormal(0, 0.08)
            np_ = rev * base_margin * rng.lognormal(0, 0.25)
            assets = base_rev * 2.2 * rng.lognormal(0, 0.1)
            equity = assets * rng.uniform(0.3, 0.7)

            # 公告日：截止日之前的随机某天，越大的公司越早披露
            dl = p + pd.Timedelta(days=deadline_days[q])
            ann = dl - pd.Timedelta(days=int(rng.integers(0, 25)))

            for field, val in [("revenue", rev), ("net_profit", np_),
                               ("total_assets", assets), ("total_equity", equity)]:
                rows.append({"code": code, "report_period": p, "ann_date": ann,
                             "field": field, "value": val})

            # 追溯调整：一段时间后重新公告同一报告期的修正值
            if rng.random() < restatement_prob:
                re_ann = ann + pd.Timedelta(days=int(rng.integers(60, 400)))
                if re_ann <= pd.Timestamp(end):
                    adj = rng.normal(1.0, 0.12)
                    for field, val in [("revenue", rev * adj), ("net_profit", np_ * adj)]:
                        rows.append({"code": code, "report_period": p, "ann_date": re_ann,
                                     "field": field, "value": val})

    return pd.DataFrame(rows)
