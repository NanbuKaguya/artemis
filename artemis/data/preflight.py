"""数据体检：在你花一整夜下载之前，先知道会缺什么。

这个模块存在的理由是一次真实的失败实验：
拿只有 OHLCV 的数据（AkShare 的 stock_zh_a_hist 就只给这些）跑整套系统，
结果是——

  micro_cap 排雷规则   剔除比例 0.0%（应为 ~40%），规则形同虚设
  size / turnover 因子  非空率 0.0%
  行业+市值中性化       与未中性化相关性 1.000，完全没起作用

**全部不报错。** 可交易池从 46% 虚增到 54%，你会以为排雷层在工作。
中性化只吐了几行 LAPACK 警告，而大多数人的脚本里都有 filterwarnings。

静默降级比崩溃危险得多：崩溃你会去修，静默降级你会拿它去做决策。
所以这个模块把每一项能力对数据的依赖显式登记，跑之前先报告哪些是活的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Severity = Literal["critical", "important", "optional"]


@dataclass
class Requirement:
    """一项能力对数据列的依赖。"""

    capability: str
    columns: list[str]
    severity: Severity
    consequence: str        # 缺失时会发生什么（说清楚"静默"这件事）
    remedy: str             # 怎么补


REQUIREMENTS: list[Requirement] = [
    Requirement(
        "回测引擎", ["open", "high", "low", "close", "prev_close", "volume"],
        "critical",
        "无法回测。prev_close 缺失会导致涨跌停判定全错，而且不报错",
        "任何数据源都提供。prev_close 若缺，用前一交易日 close 填补（注意除权日）",
    ),
    Requirement(
        "复权收益计算", ["adj_factor"],
        "critical",
        "用未复权价算收益，除权日会凭空出现 -10% 甚至 -50% 的假跌幅",
        "AkShare: 同时拉 adjust='' 和 adjust='hfq'，两者收盘价相除即为复权因子",
    ),
    Requirement(
        "流动性排雷 + 换手因子", ["amount"],
        "important",
        "illiquid 规则失效；2024年1月微盘股踩踏那类流动性风险完全不设防",
        "AkShare 的日线返回'成交额'列，直接可用",
    ),
    Requirement(
        "市值排雷 + 市值中性化", ["total_mv"],
        "important",
        "micro_cap 规则静默失效（剔除 0%）；市值中性化不起作用，"
        "你以为在做 alpha，实际在赌小盘风格",
        "Tushare daily_basic 直接给历史 total_mv/circ_mv（最干净）；"
        "AkShare 需用 总股本 × 收盘价 自行拼接",
    ),
    Requirement(
        "换手率因子", ["float_mv"],
        "important",
        "turnover_20 因子全空，compute() 会跳过它但不会告诉你少了一个因子",
        "同上，Tushare daily_basic 的 circ_mv",
    ),
    Requirement(
        "行业中性化 + 行业约束", ["industry"],
        "important",
        "行业中性化不起作用；组合可能整体压在一个行业上而分散度指标看起来正常",
        "AkShare stock_board_industry_cons_em（当前快照，回测用会有前视）；"
        "Tushare stock_basic 的 industry 字段",
    ),
    Requirement(
        "ST 排雷", ["is_st"],
        "important",
        "ST 规则失效。这是审计中 edge 最高的一条规则（+2.54，尾部保护 9.2%）",
        "**必须用历史 ST 记录，不能用当前快照** —— 后者是未来函数。"
        "Tushare namechange 接口按日期给出名称变更历史",
    ),
    Requirement(
        "停牌处理", ["is_suspended"],
        "important",
        "停牌股会被当成可交易，回测里买进卖出都成交，实盘买不到",
        "多数数据源直接跳过停牌日；用 volume<=0 兜底判定",
    ),
    Requirement(
        "退市处理", ["is_tradable"],
        "critical",
        "幸存者偏差。退市股从池子里消失而不是被强制清算，回测凭空变好看",
        "必须包含已退市股票的历史数据。Tushare stock_basic(list_status='D') 给退市列表",
    ),
    Requirement(
        "次新股排雷", ["days_since_ipo"],
        "important",
        "new_listing 规则失效（审计 edge +1.67）",
        "Tushare stock_basic 的 list_date，与交易日历相减",
    ),
]


def _survivorship_check(df: pd.DataFrame) -> tuple[str, str]:
    """幸存者偏差检查：面板里有没有"中途消失"的股票。

    正确的历史数据里，退市股的**退市前历史必须保留**，退市后的行才删掉。
    所以判据不是某一列的取值，而是：有多少股票的最后交易日早于面板结束日。

    A 股 2019 年后退市明显加速，一份 5-10 年的全市场数据里，
    提前消失的股票应占 3%~10%。如果是 0%，几乎可以肯定你的股票池
    是用"今天还在交易的股票"倒推出来的 —— 那是最经典的幸存者偏差。
    """
    try:
        d = df.index.get_level_values("date")
        c = df.index.get_level_values("code")
    except (KeyError, AttributeError):
        return "degraded", "无法读取 (date, code) 索引，跳过幸存者偏差检查"

    last_overall = d.max()
    last_by_code = pd.Series(d, index=c).groupby(level=0).max()
    n_total = len(last_by_code)
    # 留一周缓冲，避免把"最近几天没数据"误判成退市
    gone = int((last_by_code < last_overall - pd.Timedelta(days=7)).sum())
    ratio = gone / max(n_total, 1)

    span_years = (last_overall - d.min()).days / 365.25
    if span_years < 1.5:
        return "ok", f"样本仅 {span_years:.1f} 年，退市样本少属正常（{gone}/{n_total} 只提前消失）"
    if gone == 0:
        return "dead", (f"{n_total} 只股票全部存活到面板结束 —— "
                        f"跨越 {span_years:.1f} 年却零退市，几乎必然是幸存者偏差")
    if ratio < 0.01:
        return "degraded", (f"仅 {ratio:.1%} 的股票提前消失（{gone}/{n_total}），"
                            f"{span_years:.1f} 年样本期偏低，可能漏了退市股")
    return "ok", f"{ratio:.1%} 的股票在面板结束前消失（{gone}/{n_total}），符合退市预期"


@dataclass
class CheckResult:
    capability: str
    severity: Severity
    status: Literal["ok", "degraded", "dead"]
    detail: str
    remedy: str


def check(bars: pd.DataFrame, sample_frac: float = 1.0) -> pd.DataFrame:
    """体检行情表，报告每项能力是活的、残的、还是死的。

    判定标准不只看列是否存在，还看**是否有有效值** ——
    一列全是 NaN 和这列不存在，对下游是一样的，但前者更隐蔽。
    """
    df = bars.sample(frac=sample_frac) if 0 < sample_frac < 1 else bars
    rows: list[CheckResult] = []

    for req in REQUIREMENTS:
        missing = [c for c in req.columns if c not in df.columns]
        allnan = [c for c in req.columns
                  if c in df.columns and df[c].isna().all()]
        # 常量列也算死：industry 全是"未知"、is_st 全是 False 都等于没有信息。
        # is_tradable 不在此列 —— 契约要求退市后的行被删掉，所以交付的表里
        # 它本来就该全是 True。幸存者偏差要用"是否有股票提前消失"来查（见下）。
        constant = []
        for c in req.columns:
            if c in df.columns and c not in allnan:
                nun = df[c].nunique(dropna=True)
                if nun <= 1 and c in ("industry", "is_st", "is_suspended"):
                    constant.append(c)

        # 幸存者偏差要看面板结构，不是看某一列的取值
        if req.capability == "退市处理" and not missing and not allnan:
            status, detail = _survivorship_check(df)
            rows.append(CheckResult(req.capability, req.severity, status,
                                    detail, req.remedy))
            continue

        if missing or allnan:
            status = "dead"
            bad = missing + allnan
            detail = (f"缺列 {missing}" if missing else "") + \
                     (f" 全为空 {allnan}" if allnan else "")
        elif constant:
            status = "degraded"
            detail = f"{constant} 是常量，无区分度（等同于没有这项信息）"
        else:
            nan_rate = float(df[req.columns].isna().mean().max())
            if nan_rate > 0.30:
                status = "degraded"
                detail = f"最高缺失率 {nan_rate:.0%}"
            else:
                status = "ok"
                detail = f"最高缺失率 {nan_rate:.1%}"

        rows.append(CheckResult(req.capability, req.severity, status,
                                detail.strip(), req.remedy))

    out = pd.DataFrame([r.__dict__ for r in rows])
    order = {"dead": 0, "degraded": 1, "ok": 2}
    sev = {"critical": 0, "important": 1, "optional": 2}
    return out.sort_values(by=["status", "severity"],
                           key=lambda s: s.map(order if s.name == "status" else sev))


def report(bars: pd.DataFrame) -> str:
    """给人看的体检报告。"""
    df = check(bars)
    icon = {"ok": "✓", "degraded": "▲", "dead": "✗"}
    lines = ["=" * 76, "  数据体检", "=" * 76]

    n_dead = int((df.status == "dead").sum())
    n_deg = int((df.status == "degraded").sum())
    lines.append(f"  {len(df)} 项能力：{len(df)-n_dead-n_deg} 正常  {n_deg} 降级  {n_dead} 失效\n")

    for _, r in df.iterrows():
        lines.append(f"{icon[r.status]} [{r.severity:<9}] {r.capability}")
        lines.append(f"    {r.detail}")
        if r.status != "ok":
            req = next(q for q in REQUIREMENTS if q.capability == r.capability)
            lines.append(f"    后果：{req.consequence}")
            lines.append(f"    补法：{req.remedy}")
        lines.append("")

    if n_dead or n_deg:
        lines.append("-" * 76)
        lines.append("这些失效都是**静默的** —— 系统照样跑完、照样出净值曲线，")
        lines.append("只是其中一部分结论是假的。补齐之前不要拿回测结果做决策。")
    return "\n".join(lines)


def assert_ready(bars: pd.DataFrame, allow_degraded: bool = False) -> None:
    """上线前的硬闸门。critical 项失效直接抛错，不给"先跑跑看"的机会。"""
    df = check(bars)
    fatal = df[(df.status == "dead") & (df.severity == "critical")]
    if len(fatal):
        raise ValueError(
            "数据不满足回测的最低要求：\n" +
            "\n".join(f"  ✗ {r.capability}: {r.detail}\n     补法：{r.remedy}"
                      for _, r in fatal.iterrows())
        )
    if not allow_degraded:
        bad = df[(df.status.isin(["dead", "degraded"])) & (df.severity == "important")]
        if len(bad):
            raise ValueError(
                f"{len(bad)} 项重要能力失效或降级。这些失效是静默的，"
                f"回测会照样出结果但结论不可信：\n" +
                "\n".join(f"  {'✗' if r.status=='dead' else '▲'} {r.capability}: {r.detail}"
                          for _, r in bad.iterrows()) +
                "\n\n确实要在这个状态下跑，传 allow_degraded=True，"
                "并且明确知道哪些结论不能信。"
            )
