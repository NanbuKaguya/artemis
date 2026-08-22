"""Level-2 数据契约、合成生成器与日频特征聚合。

关于 L2 数据的三个必须先想清楚的事：

1. **数据量**。全市场逐笔委托+逐笔成交，单个交易日原始数据 30~80 GB。
   你不可能像日线那样"全都存下来慢慢研究"。必须在落地时就做聚合，
   只保留你真正要用的日频特征 —— 原始 tick 留最近 N 天用于调试即可。

2. **沪深不对称**。这是最容易踩的坑：
   深交所逐笔委托里，撤单是一条独立的委托记录（type='撤单'）；
   上交所把撤单编码在逐笔成交里（成交类型标记为 'C'）。
   直接用同一套代码算撤单率，会得到"深市有值、沪市恒为 0"的结果，
   而且不报错。本模块的 cancel_rate 分交易所处理这件事。

3. **L2 对日频策略的边际价值被高估**。L2 的核心优势是毫秒级和逐笔明细，
   而日频调仓系统一天只用一次信号。对个人投资者，L2 最确定的价值在
   **执行侧**（用委托队列优化挂单位置），而不是选股侧。
   选股因子那部分必须走完整的挖掘+FDR 流程才能确认，不要默认它有用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

import numpy as np
import pandas as pd


class Exchange(str, Enum):
    SH = "SH"
    SZ = "SZ"
    BJ = "BJ"


def exchange_of(code: str) -> Exchange:
    c = code.split(".")[0]
    if c.startswith(("6", "9")):
        return Exchange.SH
    if c.startswith(("4", "8", "920")):
        return Exchange.BJ
    return Exchange.SZ


# ---------------------------------------------------------------- 数据契约
# 逐笔委托 (l2order)
ORDER_COLUMNS = {
    "time": "datetime64[ns]",
    "code": "object",
    "price": "float64",
    "volume": "float64",        # 股
    "side": "object",           # 'B' 买 / 'S' 卖
    "order_type": "object",     # 'LIMIT' 限价 / 'MARKET' 市价 / 'BEST' 本方最优 / 'CANCEL' 撤单(深市)
    "order_no": "int64",        # 委托编号，用于关联成交
}

# 逐笔成交 (l2transaction)
TRADE_COLUMNS = {
    "time": "datetime64[ns]",
    "code": "object",
    "price": "float64",
    "volume": "float64",
    "bid_order_no": "int64",    # 买方委托编号
    "ask_order_no": "int64",    # 卖方委托编号
    "trade_type": "object",     # 'T' 成交 / 'C' 撤单(沪市在此编码撤单)
}

# 十档快照 (l2quote)
SNAP_COLUMNS = ["time", "code", "last", "total_bid_vol", "total_ask_vol"] + \
    [f"bid_p{i}" for i in range(1, 11)] + [f"bid_v{i}" for i in range(1, 11)] + \
    [f"ask_p{i}" for i in range(1, 11)] + [f"ask_v{i}" for i in range(1, 11)]


class Level2Error(ValueError):
    pass


def validate_orders(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in ORDER_COLUMNS if c not in df.columns]
    if missing:
        raise Level2Error(f"逐笔委托表缺列 {missing}")
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"])
    return out.sort_values(["code", "time"]).reset_index(drop=True)


def validate_trades(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in TRADE_COLUMNS if c not in df.columns]
    if missing:
        raise Level2Error(f"逐笔成交表缺列 {missing}")
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"])
    return out.sort_values(["code", "time"]).reset_index(drop=True)


# ---------------------------------------------------------------- 日频特征聚合
def daily_features(
    orders: pd.DataFrame | None,
    trades: pd.DataFrame,
    snaps: pd.DataFrame | None = None,
    large_order_threshold: float = 500_000.0,
) -> pd.DataFrame:
    """把一天的逐笔数据聚合成日频特征，index=(date, code)。

    这是 L2 进入日频策略的唯一正确姿势：落地时就聚合。
    原始逐笔一天几十 GB，攒不下来也没必要攒。
    """
    tr = validate_trades(trades)
    tr = tr[tr["trade_type"] == "T"].copy()          # 只算真实成交
    if tr.empty:
        return pd.DataFrame()

    tr["date"] = tr["time"].dt.normalize()
    tr["amount"] = tr["price"] * tr["volume"]

    # 主动买卖方向：委托编号大的一方是后到的，即主动方
    tr["aggressor"] = np.where(tr["bid_order_no"] > tr["ask_order_no"], "B", "S")
    tr["signed_amt"] = np.where(tr["aggressor"] == "B", tr["amount"], -tr["amount"])
    tr["is_large"] = tr["amount"] >= large_order_threshold

    g = tr.groupby(["date", "code"])
    feat = pd.DataFrame({
        "n_trades": g.size(),
        "amount": g["amount"].sum(),
        "vwap": g.apply(lambda x: float((x["price"] * x["volume"]).sum() / x["volume"].sum()),
                        include_groups=False),
        # 订单流失衡：主动买入金额占比偏离 0.5 的程度。文献里最稳健的微观结构因子
        "ofi": g["signed_amt"].sum() / g["amount"].sum(),
        # 大单净流入占比
        "large_net_ratio": (g.apply(lambda x: float(x.loc[x["is_large"], "signed_amt"].sum()),
                                    include_groups=False) / g["amount"].sum()),
        "large_amt_ratio": (g.apply(lambda x: float(x.loc[x["is_large"], "amount"].sum()),
                                    include_groups=False) / g["amount"].sum()),
        "avg_trade_size": g["amount"].mean(),
        # 成交金额的时段分布：尾盘占比高常与被动配置盘/指数调仓相关
        "close_amt_ratio": g.apply(
            lambda x: float(x.loc[x["time"].dt.time >= pd.Timestamp("14:30").time(),
                                  "amount"].sum() / max(x["amount"].sum(), 1e-9)),
            include_groups=False),
    })

    if orders is not None and not orders.empty:
        feat = feat.join(_order_features(orders, trades), how="left")
    if snaps is not None and not snaps.empty:
        feat = feat.join(_book_features(snaps), how="left")

    feat.index.names = ["date", "code"]
    return feat


def _order_features(orders: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """委托侧特征。撤单率必须分交易所处理 —— 沪深的编码方式不同。"""
    od = validate_orders(orders)
    od["date"] = od["time"].dt.normalize()
    od["amount"] = od["price"] * od["volume"]
    od["exch"] = od["code"].map(lambda c: exchange_of(c).value)

    tr = validate_trades(trades)
    tr["date"] = tr["time"].dt.normalize()

    rows = {}
    for (d, c), g in od.groupby(["date", "code"]):
        exch = g["exch"].iloc[0]
        total_amt = float(g.loc[g["order_type"] != "CANCEL", "amount"].sum())

        if exch == "SZ":
            # 深市：撤单是独立的委托记录
            cancel_amt = float(g.loc[g["order_type"] == "CANCEL", "amount"].sum())
        else:
            # 沪市：撤单编码在逐笔成交里，trade_type == 'C'
            t = tr[(tr["date"] == d) & (tr["code"] == c)]
            cancel_amt = float((t.loc[t["trade_type"] == "C", "price"]
                                * t.loc[t["trade_type"] == "C", "volume"]).sum())

        placed = g[g["order_type"] != "CANCEL"]
        rows[(d, c)] = {
            "n_orders": int(len(placed)),
            "order_amt": total_amt,
            "cancel_ratio": cancel_amt / max(total_amt, 1e-9),
            "avg_order_size": float(placed["amount"].mean()) if len(placed) else np.nan,
            # 委托失衡：挂单端的买卖力量对比，与成交端的 ofi 互补
            "order_imbalance": float(
                (placed.loc[placed.side == "B", "amount"].sum()
                 - placed.loc[placed.side == "S", "amount"].sum())
                / max(total_amt, 1e-9)),
            "exchange": exch,
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index = pd.MultiIndex.from_tuples(out.index, names=["date", "code"])
    return out


def _book_features(snaps: pd.DataFrame) -> pd.DataFrame:
    """盘口形态特征。日内多次快照取均值，反映全天的盘口结构。"""
    s = snaps.copy()
    s["time"] = pd.to_datetime(s["time"])
    s["date"] = s["time"].dt.normalize()

    bid_v = s[[f"bid_v{i}" for i in range(1, 11)]].sum(axis=1)
    ask_v = s[[f"ask_v{i}" for i in range(1, 11)]].sum(axis=1)
    s["book_imbalance"] = (bid_v - ask_v) / (bid_v + ask_v).replace(0, np.nan)
    s["spread_bps"] = (s["ask_p1"] - s["bid_p1"]) / s["last"].replace(0, np.nan) * 1e4
    # 盘口厚度：一档量占十档总量的比例。越低说明真实可成交深度越靠后
    s["depth_top1_ratio"] = (s["bid_v1"] + s["ask_v1"]) / (bid_v + ask_v).replace(0, np.nan)

    g = s.groupby(["date", "code"])
    return pd.DataFrame({
        "book_imbalance": g["book_imbalance"].mean(),
        "spread_bps": g["spread_bps"].mean(),
        "depth_top1_ratio": g["depth_top1_ratio"].mean(),
    })


# ---------------------------------------------------------------- 合成 L2
def make_synthetic_l2(
    codes: list[str],
    date: str = "2026-08-21",
    seed: int = 0,
    n_trades_per_stock: int = 3000,
    informed_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """生成一天的合成逐笔数据，用于验证聚合与因子逻辑。

    刻意做出沪深差异：沪市股票的撤单编码在成交表里，深市在委托表里。
    这样聚合代码的分交易所处理才有东西可测。

    informed_ratio: 知情交易者占比。他们的订单流方向与当日收益相关，
    这让 OFI 因子在合成数据上有真实信号可检出。
    """
    rng = np.random.default_rng(seed)
    day = pd.Timestamp(date)
    orders, trades, snaps = [], [], []

    for code in codes:
        exch = exchange_of(code)
        base = float(rng.uniform(8, 60))
        # 当日"真实"方向，知情订单流会与之相关
        drift = float(rng.normal(0, 0.015))

        n = n_trades_per_stock
        # 交易时间：9:30-11:30, 13:00-15:00，U 型分布
        u = rng.beta(0.6, 0.6, n)
        minutes = np.where(u < 0.5, u * 2 * 120, 120 + (u - 0.5) * 2 * 120)
        times = [day + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=float(m))
                 if m < 120 else
                 day + pd.Timedelta(hours=13) + pd.Timedelta(minutes=float(m - 120))
                 for m in np.sort(minutes)]

        px = base * np.cumprod(1 + rng.normal(drift / n, 0.0006, n))
        vol = rng.lognormal(np.log(800), 1.1, n).round(-2).clip(100, 2_000_000)

        informed = rng.random(n) < informed_ratio
        # 知情订单流方向与当日 drift 同向；噪音交易者随机
        p_buy = np.where(informed, 0.5 + np.sign(drift) * 0.30, 0.5)
        is_buy = rng.random(n) < p_buy

        bid_no = np.arange(1, n + 1) * 2
        ask_no = np.arange(1, n + 1) * 2 + 1
        # 主动方委托编号更大
        bid_final = np.where(is_buy, ask_no + 1, bid_no)
        ask_final = np.where(is_buy, ask_no, bid_no + 1)

        trades.append(pd.DataFrame({
            "time": times, "code": code, "price": px, "volume": vol,
            "bid_order_no": bid_final, "ask_order_no": ask_final, "trade_type": "T",
        }))

        # 委托：成交量的 ~2.5 倍（大部分委托不成交）
        m = int(n * 2.5)
        o_times = [times[min(int(i / m * n), n - 1)] for i in range(m)]
        o_px = px[np.minimum((np.arange(m) / m * n).astype(int), n - 1)] * \
            (1 + rng.normal(0, 0.002, m))
        o_vol = rng.lognormal(np.log(700), 1.1, m).round(-2).clip(100, 2_000_000)
        o_side = np.where(rng.random(m) < 0.5, "B", "S")
        o_type = np.full(m, "LIMIT", dtype=object)

        n_cancel = int(m * rng.uniform(0.15, 0.45))
        cancel_idx = rng.choice(m, n_cancel, replace=False)

        if exch is Exchange.SZ:
            # 深市：撤单作为独立委托记录
            o_type[cancel_idx] = "CANCEL"
        else:
            # 沪市：撤单编码在成交表里
            trades.append(pd.DataFrame({
                "time": [o_times[i] for i in cancel_idx], "code": code,
                "price": o_px[cancel_idx], "volume": o_vol[cancel_idx],
                "bid_order_no": 0, "ask_order_no": 0, "trade_type": "C",
            }))

        orders.append(pd.DataFrame({
            "time": o_times, "code": code, "price": o_px, "volume": o_vol,
            "side": o_side, "order_type": o_type, "order_no": np.arange(1, m + 1),
        }))

        # 十档快照：每分钟一次
        n_snap = 240
        snap_t = [day + pd.Timedelta(hours=9, minutes=30 + i) for i in range(n_snap)]
        last = px[np.minimum((np.arange(n_snap) / n_snap * n).astype(int), n - 1)]
        tick = 0.01
        d = {"time": snap_t, "code": code, "last": last}
        # 盘口失衡与 drift 同向 —— 让 book_imbalance 也带上真实信号
        imb = np.tanh(drift * 25) * 0.4
        for i in range(1, 11):
            d[f"bid_p{i}"] = last - tick * i
            d[f"ask_p{i}"] = last + tick * i
            base_v = rng.lognormal(np.log(20000 / i), 0.6, n_snap)
            d[f"bid_v{i}"] = base_v * (1 + imb)
            d[f"ask_v{i}"] = base_v * (1 - imb)
        d["total_bid_vol"] = sum(d[f"bid_v{i}"] for i in range(1, 11))
        d["total_ask_vol"] = sum(d[f"ask_v{i}"] for i in range(1, 11))
        snaps.append(pd.DataFrame(d))

    return (pd.concat(orders, ignore_index=True),
            pd.concat(trades, ignore_index=True),
            pd.concat(snaps, ignore_index=True))
