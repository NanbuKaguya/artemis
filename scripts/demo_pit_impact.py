"""演示：搞错 point-in-time 会凭空造出多少假 alpha。

构造一个财报公告日会产生跳空的市场（这是真实现象：业绩超预期/暴雷
都在公告当天反映到股价上），然后用三种方式对齐同一个**业绩增速因子**：

  A. 正确 PIT      —— 按公告日对齐，公告后才可见
  B. 报告期对齐    —— 最常见的错误：以为报告期一结束就知道数据
  C. 最终版追溯    —— 用数据库里的最终值，忽略当时的原始版本

三者的差距就是"数据处理错误伪装成的 alpha"。

为什么用增速因子而不是 E/P：
PIT 错误的伤害大小取决于因子对**公告事件**的敏感度。E/P 这类水平值因子
在报告期末到公告日之间几乎不变，偷跑的信息量小；而增速/超预期类因子
的全部信息都在公告那一刻产生 —— 提前 30 天知道它，等于提前知道了跳空方向。
真实世界里增长类因子极其常用，这才是 PIT 错误的主战场。

前瞻窗口也必须盖住公告日（报告期末到公告约 30 天），否则跳空落在窗口之外，
你会误以为 PIT 无害。
"""
from __future__ import annotations

import sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from artemis.data.fundamentals import align_to_bars, make_synthetic_pit, validate_pit
from artemis.alpha import factors as F


def build_market_coupled_to_earnings(
    n_stocks: int = 300, start: str = "2017-01-01", end: str = "2021-12-31",
    seed: int = 11, jump_scale: float = 0.05,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成"公告日跳空"的市场：业绩超预期越多，公告当天涨得越多。

    jump_scale 控制跳空幅度。A 股财报公告日的平均绝对波动约 3–5%，
    这里用 5% 作为一倍标准差的尺度，属于保守设定。
    """
    rng = np.random.default_rng(seed)
    codes = [f"{600000 + i * 7:06d}" for i in range(n_stocks)]
    dates = pd.bdate_range(start, end)

    pit = validate_pit(make_synthetic_pit(codes, start, end, seed=seed))

    # 每次净利润公告的"惊喜度"：本次 TTM 相对上次 TTM 的变化，横截面标准化
    npf = pit[pit.field == "net_profit"].sort_values(["code", "ann_date"])
    npf = npf.drop_duplicates(["code", "report_period"], keep="last")
    npf["prev"] = npf.groupby("code")["value"].shift(1)
    npf["surprise"] = (npf["value"] / npf["prev"] - 1).replace([np.inf, -np.inf], np.nan)
    # 按报告期分组标准化，而不是按公告日：公告日高度分散，每组只有几只股票，
    # 按它标准化出来的"惊喜度"基本是噪音，会稀释掉整个演示要展示的效应。
    npf["surprise"] = npf.groupby("report_period")["surprise"].transform(
        lambda x: (x - x.mean()) / (x.std() or 1)).clip(-3, 3)

    # 跳空矩阵：只在公告当天注入
    jump = pd.DataFrame(0.0, index=dates, columns=codes)
    for _, r in npf.dropna(subset=["surprise"]).iterrows():
        d = r["ann_date"]
        if d in jump.index and r["code"] in jump.columns:
            jump.at[d, r["code"]] = float(r["surprise"]) * jump_scale

    mkt = rng.normal(0.0002, 0.011, len(dates))
    idio = rng.normal(0, 0.018, (len(dates), n_stocks))
    beta = rng.normal(1.0, 0.25, n_stocks)
    ret = beta * mkt[:, None] + idio + jump.values
    ret = np.clip(ret, -0.10, 0.10)

    px = 12 * np.cumprod(1 + ret, axis=0)
    shares = rng.lognormal(np.log(5e8), 0.9, n_stocks)

    idx = pd.MultiIndex.from_product([dates, codes], names=["date", "code"])
    bars = pd.DataFrame({
        "open": px.ravel(), "high": (px * 1.01).ravel(), "low": (px * 0.99).ravel(),
        "close": px.ravel(), "volume": 1e7, "amount": (px * 1e7).ravel(),
        "prev_close": np.vstack([px[:1], px[:-1]]).ravel(), "adj_factor": 1.0,
        "is_st": False, "is_suspended": False, "is_tradable": True,
        "days_since_ipo": 999, "total_mv": (px * shares).ravel(),
        "float_mv": (px * shares * 0.7).ravel(), "industry": "测试",
    }, index=idx)
    return bars, pit


def _growth(bars: pd.DataFrame, pit: pd.DataFrame) -> pd.Series:
    """净利润 TTM 同比增速。全部信息都在公告那一刻产生。"""
    ttm = align_to_bars(pit, bars, ["net_profit"])["net_profit"].unstack("code")
    yoy = ttm / ttm.shift(252) - 1
    return yoy.stack(future_stack=True).reindex(bars.index)


def growth_correct_pit(bars, pit) -> pd.Series:
    """A. 正确：按公告日对齐。"""
    return _growth(bars, pit)


def growth_report_period(bars, pit) -> pd.Series:
    """B. 错误：把报告期当成可见日 —— 提前约 30 天知道业绩。"""
    fake = pit.copy()
    fake["ann_date"] = fake["report_period"]
    return _growth(bars, fake)


def growth_final_restated(bars, pit) -> pd.Series:
    """C. 错误：按首次公告日可见，但取的是最终修正值。

    看起来"用了公告日"很规矩，但值是修正后的 —— 等于提前知道了会计差错更正。
    """
    fake = pit.sort_values("ann_date").copy()
    key = ["code", "report_period", "field"]
    fake["ann_date"] = fake.groupby(key)["ann_date"].transform("min")
    fake["value"] = fake.groupby(key)["value"].transform("last")
    fake = fake.drop_duplicates(key, keep="last")
    return _growth(bars, fake)


def evaluate(name: str, fac: pd.Series, bars: pd.DataFrame, horizon: int = 40) -> dict:
    """用 T+1 开盘买入、T+1+h 开盘卖出的口径评估。"""
    op = bars["open"].unstack("code")
    fwd = (op.shift(-1 - horizon) / op.shift(-1) - 1).stack(future_stack=True).reindex(bars.index)
    f = F.prepare(fac, bars, neutral=False)
    df = pd.DataFrame({"f": f, "r": fwd}).dropna()
    if df.empty:
        return {"因子对齐方式": name, "样本": 0}
    ic = df.groupby(level="date").apply(
        lambda g: g["f"].corr(g["r"], method="spearman") if len(g) >= 20 else np.nan).dropna()
    q = df.groupby(level="date", group_keys=False).apply(
        lambda g: g.assign(q=pd.qcut(g["f"].rank(method="first"), 5, labels=False))
        if len(g) >= 20 else g.assign(q=np.nan)).dropna(subset=["q"])
    qr = q.groupby([q.index.get_level_values("date"), "q"])["r"].mean().unstack("q")
    ls = (qr[4.0] - qr[0.0]) if 4.0 in qr and 0.0 in qr else pd.Series(dtype=float)
    ann = float(ls.mean() * 252 / horizon) if len(ls) else np.nan
    return {
        "因子对齐方式": name,
        "IC均值": round(float(ic.mean()), 4),
        "年化ICIR": round(float(ic.mean() / ic.std() * np.sqrt(252 / horizon)), 2),
        "多空年化": f"{ann:.2%}",
        "样本天数": len(ic),
    }


def main():
    print("生成'财报公告引发跳空'的市场（300 只 × 5 年）...")
    bars, pit = build_market_coupled_to_earnings()
    print(f"  行情 {len(bars):,} 行，财务记录 {len(pit):,} 条\n")

    rows = [
        evaluate("A. 正确 PIT（按公告日）", growth_correct_pit(bars, pit), bars),
        evaluate("B. 报告期对齐（常见错误）", growth_report_period(bars, pit), bars),
        evaluate("C. 最终版追溯（隐蔽错误）", growth_final_restated(bars, pit), bars),
    ]
    df = pd.DataFrame(rows)
    print("=" * 78)
    print("同一个业绩增速因子，三种对齐方式（40 日前瞻，窗口覆盖公告日）")
    print("=" * 78)
    print(df.to_string(index=False))
    print("=" * 78)

    a, b, c = rows[0], rows[1], rows[2]
    def pct(s): return float(str(s).rstrip("%")) if isinstance(s, str) else float(s)
    print(f"\n凭空多出的假 alpha：")
    print(f"  报告期对齐   比正确 PIT 多 {pct(b['多空年化']) - pct(a['多空年化']):+.2f} pp/年"
          f"   (ICIR {b['年化ICIR']:.2f} vs {a['年化ICIR']:.2f})")
    print(f"  最终版追溯   比正确 PIT 多 {pct(c['多空年化']) - pct(a['多空年化']):+.2f} pp/年"
          f"   (ICIR {c['年化ICIR']:.2f} vs {a['年化ICIR']:.2f})")
    print("\n最该注意的不是多空收益那几个百分点，而是 ICIR 的符号：")
    print(f"  正确对齐时 ICIR = {a['年化ICIR']:.2f}（这因子实际上是有害的）")
    print(f"  报告期对齐时 ICIR = {b['年化ICIR']:.2f}（看起来可以用了）")
    print("  一个该被淘汰的因子，仅因为对齐方式错误就通过了初筛。")
    print("\n关于 C（最终版追溯）：本演示中的追溯调整是随机的（均值为 1），")
    print("所以提前知道修正值并不系统性有利。真实世界不是这样 —— 会计差错更正")
    print("常常与后续暴雷相关，方向不随机，真实偏差会比这里更大。")
    print("\n这些错误都不会报错、不会崩溃。它们只会让你的回测好看一点，")
    print("好看到足以骗过你的初筛，然后你把钱投进去。")


if __name__ == "__main__":
    main()
