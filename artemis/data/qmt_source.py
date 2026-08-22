"""QMT / xtquant 数据适配器（在你本机运行）。

⚠️ 本文件无法在开发容器内实测 —— 容器里没有 QMT 客户端、没有券商柜台连接。
   所有与 xtquant 交互的部分都按官方接口写，但**必须在你本地跑一次 probe()
   验证**。标了 [需本地验证] 的地方是字段名/返回结构可能随 QMT 版本变化的位置。

为什么走 QMT 而不是别的：
- 它是券商官方通道，合规、稳定，且和实盘下单是同一条链路
- Level-2 权限由券商开通，数据直接落到本地，不存在爬虫限频问题
- 与同花顺超级Level-2 的区别：后者是**看板产品**，只能看不能取；
  QMT 的 L2 是**数据接口**，为程序化访问而设计

分级降级：没有 L2 权限时自动退回 Level-1 tick，先把链路跑通。
L1 tick 也能算出一部分微观结构特征（虽然精度差很多），
足够验证整条流水线，等 L2 权限开通后只改一个参数。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np
import pandas as pd

# xtquant 的周期名。L2 全部需要券商开通 Level-2 权限。
PERIODS = {
    "tick": {"level": 1, "desc": "Level-1 逐笔快照（3 秒一笔）"},
    "l2quote": {"level": 2, "desc": "Level-2 十档快照"},
    "l2quoteaux": {"level": 2, "desc": "Level-2 快照补充"},
    "l2order": {"level": 2, "desc": "Level-2 逐笔委托"},
    "l2transaction": {"level": 2, "desc": "Level-2 逐笔成交"},
    "l2orderqueue": {"level": 2, "desc": "Level-2 委买委卖队列"},
    "l2transactioncount": {"level": 2, "desc": "Level-2 大单统计"},
}


class QmtError(RuntimeError):
    pass


def _xtdata():
    try:
        from xtquant import xtdata
    except ImportError as e:  # pragma: no cover - 环境相关
        raise QmtError(
            "未安装 xtquant。它随 QMT 客户端一起分发，不在 PyPI 上：\n"
            "  1. 安装券商的 QMT 客户端并登录\n"
            "  2. xtquant 位于 QMT 安装目录下的 bin.x64/Lib/site-packages/xtquant\n"
            "  3. 把该路径加入 PYTHONPATH，或直接用 QMT 自带的 python 解释器"
        ) from e
    return xtdata


def to_xt_code(code: str) -> str:
    """6 位代码 → xtquant 格式（600000 → 600000.SH）。"""
    c = code.split(".")[0].strip().zfill(6)
    if c.startswith(("6", "9")):
        return f"{c}.SH"
    if c.startswith(("4", "8")) or c.startswith("920"):
        return f"{c}.BJ"
    return f"{c}.SZ"


def from_xt_code(xt: str) -> str:
    return xt.split(".")[0]


# --------------------------------------------------------------------------
def probe(sample_code: str = "600000", verbose: bool = True) -> pd.DataFrame:
    """能力体检：报告你的账户实际拥有哪些数据权限。

    **接 QMT 后第一件该跑的事。** 它回答两个问题：
      1. xtquant 能不能连上（QMT 客户端是否在运行、是否已登录）
      2. 哪些周期真的能取到数据（L2 权限是否已开通）

    不要相信券商销售的口头承诺，以这个函数的输出为准。
    """
    xtdata = _xtdata()
    xt_code = to_xt_code(sample_code)
    rows = []

    for period, meta in PERIODS.items():
        ok, detail, n = False, "", 0
        try:
            # 先尝试补一天历史，再读本地
            xtdata.download_history_data(xt_code, period, "", "")
            data = xtdata.get_local_data(
                field_list=[], stock_list=[xt_code], period=period, count=10
            )
            obj = data.get(xt_code) if isinstance(data, dict) else data
            if obj is None:
                detail = "返回空"
            elif isinstance(obj, pd.DataFrame):
                n, ok = len(obj), len(obj) > 0
                detail = f"{list(obj.columns)[:6]}" if ok else "0 行"
            else:
                n = len(obj) if hasattr(obj, "__len__") else 0
                ok = n > 0
                detail = f"{type(obj).__name__}"
        except Exception as e:  # noqa: BLE001 - xtquant 异常类型不稳定
            detail = str(e)[:90]

        rows.append({
            "period": period, "级别": f"L{meta['level']}", "说明": meta["desc"],
            "可用": ok, "样本行数": n, "详情": detail,
        })

    df = pd.DataFrame(rows)
    if verbose:
        l2_ok = df[(df["级别"] == "L2") & df["可用"]]
        print(df[["period", "级别", "说明", "可用", "样本行数"]].to_string(index=False))
        if len(l2_ok) == 0:
            print("\n→ 未检测到任何 Level-2 权限。可以先用 period='tick' 跑通链路。")
            print("  开通 L2 需联系券商，费用约 2000-3000 元/年（部分券商月费 <200 元）。")
        else:
            print(f"\n→ 检测到 {len(l2_ok)} 项 L2 权限可用。")
    return df


# --------------------------------------------------------------------------
@dataclass
class QmtSource:
    """QMT 数据源。

    level: 'auto' 时自动探测，有 L2 用 L2，没有退回 L1 tick。
    """

    level: Literal["auto", "l1", "l2"] = "auto"
    _resolved: str = field(default="", init=False)

    def __post_init__(self):
        if self.level != "auto":
            self._resolved = self.level

    def resolve_level(self, sample_code: str = "600000") -> str:
        """确定实际可用的数据级别。结果会被缓存。"""
        if self._resolved:
            return self._resolved
        try:
            df = probe(sample_code, verbose=False)
            has_l2 = bool(df[(df["级别"] == "L2") & df["可用"]].shape[0])
            self._resolved = "l2" if has_l2 else "l1"
        except QmtError:
            self._resolved = "l1"
        return self._resolved

    # ---------------------------------------------------------------- 股票池
    def stock_list(self, sector: str = "沪深A股") -> list[str]:
        xtdata = _xtdata()
        codes = xtdata.get_stock_list_in_sector(sector)
        return sorted(from_xt_code(c) for c in codes)

    # ---------------------------------------------------------------- 日线
    def daily_bars_one(self, code: str, start: str, end: str) -> pd.DataFrame:
        """日线，产出 schema 契约格式。与 AkshareSource 同签名，可直接换用。"""
        xtdata = _xtdata()
        xt = to_xt_code(code)
        s, e = start.replace("-", ""), end.replace("-", "")
        xtdata.download_history_data(xt, "1d", s, e)

        raw = xtdata.get_local_data(field_list=[], stock_list=[xt], period="1d",
                                    start_time=s, end_time=e, dividend_type="none")
        hfq = xtdata.get_local_data(field_list=[], stock_list=[xt], period="1d",
                                    start_time=s, end_time=e, dividend_type="back")
        df = raw.get(xt) if isinstance(raw, dict) else raw
        dfh = hfq.get(xt) if isinstance(hfq, dict) else hfq
        if df is None or len(df) == 0:
            return pd.DataFrame()

        out = _normalize_bars(df)
        if dfh is not None and len(dfh):
            h = _normalize_bars(dfh)
            out["adj_factor"] = (h["close"] / out["close"]).reindex(out.index).ffill().fillna(1.0)
        else:
            out["adj_factor"] = 1.0

        out["code"] = from_xt_code(xt)
        out["prev_close"] = out.get("preClose", out["close"].shift(1)).fillna(out["open"])
        for col, default in [("is_st", False), ("is_suspended", False), ("is_tradable", True),
                             ("days_since_ipo", 9999), ("total_mv", np.nan),
                             ("float_mv", np.nan), ("industry", "未知")]:
            if col not in out.columns:
                out[col] = default
        out["is_suspended"] = out["is_suspended"] | (out["volume"].fillna(0) <= 0)
        keep = ["open", "high", "low", "close", "volume", "amount", "prev_close", "adj_factor",
                "is_st", "is_suspended", "is_tradable", "days_since_ipo",
                "total_mv", "float_mv", "industry", "code"]
        return out[[c for c in keep if c in out.columns]].reset_index().set_index(["date", "code"])

    # ---------------------------------------------------------------- 逐笔
    def fetch_ticks(
        self, code: str, date: str, period: str | None = None
    ) -> pd.DataFrame:
        """取某只股票某天的逐笔数据。

        period 为 None 时按 resolve_level() 自动选：
          有 L2 → 'l2transaction'（真逐笔成交）
          无 L2 → 'tick'（Level-1 快照，3 秒一笔，精度差很多但能跑通链路）

        [需本地验证] 返回字段名随 QMT 版本可能不同，用 probe() 的输出核对。
        """
        xtdata = _xtdata()
        period = period or ("l2transaction" if self.resolve_level(code) == "l2" else "tick")
        xt = to_xt_code(code)
        d = date.replace("-", "")
        xtdata.download_history_data(xt, period, d, d)
        data = xtdata.get_local_data(field_list=[], stock_list=[xt], period=period,
                                     start_time=d, end_time=d)
        df = data.get(xt) if isinstance(data, dict) else data
        if df is None or len(df) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(df).copy()
        df["code"] = from_xt_code(xt)
        return df

    def to_level2_contract(
        self, raw: pd.DataFrame, period: str
    ) -> pd.DataFrame:
        """把 xtquant 的原始返回转成 level2.py 的契约格式。

        [需本地验证] 这是整个适配器最需要你本地核对的一步 ——
        xtquant 的字段名在不同 QMT 版本间会变。跑一次 probe() 看真实列名，
        对不上就在 _FIELD_MAP 里补一行，不要改下游代码。
        """
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(columns=_FIELD_MAP.get(period, {})).copy()

        if "time" in df.columns:
            # xtquant 的 time 通常是毫秒时间戳
            if pd.api.types.is_numeric_dtype(df["time"]):
                df["time"] = pd.to_datetime(df["time"], unit="ms")
            else:
                df["time"] = pd.to_datetime(df["time"])

        if period == "l2transaction":
            if "trade_type" not in df.columns:
                # 深市逐笔成交无撤单记录；沪市用 tradeType/'C' 标记撤单
                df["trade_type"] = "T"
            df["trade_type"] = df["trade_type"].astype(str).str.upper().str[0].replace(
                {"0": "T", "1": "C", "F": "T"})
        elif period == "l2order":
            if "order_type" in df.columns:
                df["order_type"] = df["order_type"].map(_ORDER_TYPE_MAP).fillna("LIMIT")
            if "side" in df.columns:
                df["side"] = df["side"].map(_SIDE_MAP).fillna(df["side"])
        return df


_FIELD_MAP = {
    "l2transaction": {
        "tradeTime": "time", "tradePrice": "price", "tradeVolume": "volume",
        "askOrder": "ask_order_no", "bidOrder": "bid_order_no", "tradeType": "trade_type",
        "price": "price", "volume": "volume",
    },
    "l2order": {
        "orderTime": "time", "orderPrice": "price", "orderVolume": "volume",
        "orderType": "order_type", "orderSide": "side", "orderIndex": "order_no",
        "price": "price", "volume": "volume",
    },
    "l2quote": {"askPrice": "ask_p", "bidPrice": "bid_p",
                "askVol": "ask_v", "bidVol": "bid_v", "lastPrice": "last"},
}
_ORDER_TYPE_MAP = {0: "LIMIT", 1: "MARKET", 2: "BEST", 10: "CANCEL",
                   "0": "LIMIT", "1": "MARKET", "2": "BEST", "10": "CANCEL"}
_SIDE_MAP = {1: "B", 2: "S", "1": "B", "2": "S", "B": "B", "S": "S"}


def _normalize_bars(df) -> pd.DataFrame:
    d = pd.DataFrame(df).copy()
    if "time" in d.columns:
        d["date"] = pd.to_datetime(d["time"], unit="ms").dt.normalize()
    elif not isinstance(d.index, pd.DatetimeIndex):
        d["date"] = pd.to_datetime(d.index)
    else:
        d["date"] = d.index.normalize()
    d = d.rename(columns={"volume": "volume", "amount": "amount"})
    if "volume" in d.columns:
        d["volume"] = d["volume"].astype(float) * 100    # QMT 日线成交量单位是手
    return d.set_index("date").sort_index()
