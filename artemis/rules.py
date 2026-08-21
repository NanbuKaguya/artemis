"""A 股市场规则常量与判定函数。

这一层刻意做成纯函数 + 无依赖，因为它是整个系统的"物理定律"：
回测、实盘、风控都必须共用同一套规则，否则回测就是在另一个宇宙里赚钱。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Board(str, Enum):
    """上市板块。涨跌停幅度、最小申报单位都由板块决定。"""

    MAIN = "main"          # 沪深主板 60/000/001/002(中小板已并入)
    STAR = "star"          # 科创板 688
    CHINEXT = "chinext"    # 创业板 300/301
    BSE = "bse"            # 北交所 4xx/8xx/920
    UNKNOWN = "unknown"


def classify_board(code: str) -> Board:
    """按证券代码判定板块。code 为 6 位数字字符串，可带 .SH/.SZ/.BJ 后缀。"""
    c = code.split(".")[0].strip()
    if len(c) != 6 or not c.isdigit():
        return Board.UNKNOWN
    if c.startswith("688") or c.startswith("689"):
        return Board.STAR
    if c.startswith("300") or c.startswith("301") or c.startswith("302"):
        return Board.CHINEXT
    if c.startswith(("4", "8", "920")):
        return Board.BSE
    if c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return Board.MAIN
    return Board.UNKNOWN


def price_limit_pct(code: str, is_st: bool = False, days_since_ipo: int | None = None) -> float:
    """返回当日涨跌停幅度（小数，例如 0.10 表示 ±10%）。

    days_since_ipo 为 None 表示非次新或未知；科创板/创业板新股上市前 5 个交易日
    不设涨跌幅限制，这里用一个很大的值表示"实质无限制"。
    """
    board = classify_board(code)

    # 新股上市初期的特殊处理
    if days_since_ipo is not None and days_since_ipo >= 0:
        if board in (Board.STAR, Board.CHINEXT) and days_since_ipo < 5:
            return 10.0          # 实质无涨跌幅限制
        if board is Board.BSE and days_since_ipo < 1:
            return 10.0          # 北交所上市首日不设限
        if board is Board.MAIN and days_since_ipo < 1:
            return 0.44          # 主板新股首日 +44%

    if is_st:
        # ST/*ST：主板 5%，创业板/科创板仍为 20%，北交所 30%
        if board is Board.MAIN:
            return 0.05
        if board in (Board.STAR, Board.CHINEXT):
            return 0.20
        if board is Board.BSE:
            return 0.30
        return 0.05

    if board in (Board.STAR, Board.CHINEXT):
        return 0.20
    if board is Board.BSE:
        return 0.30
    return 0.10


def round_limit_price(prev_close: float, pct: float, up: bool) -> float:
    """按交易所规则计算涨/跌停价：四舍五入保留两位小数。"""
    raw = prev_close * (1 + pct) if up else prev_close * (1 - pct)
    # 交易所对涨跌停价采用四舍五入到分
    return float(round(raw + 1e-12, 2))


def min_lot(code: str, side: str) -> int:
    """最小交易单位（股）。

    买入：主板/创业板 100 股整数倍；科创板 200 股起、以 1 股为增量。
    卖出：余额不足 100 股（科创板不足 200 股）时必须一次性全部卖出，
          所以卖出方向不强制取整，由撮合层处理。
    """
    if side == "sell":
        return 1
    return 200 if classify_board(code) is Board.STAR else 100


@dataclass(frozen=True)
class CostModel:
    """交易成本模型。默认值取 2026 年 A 股常见散户费率。

    - 印花税：2023-08-28 起 0.05%，卖出单边征收
    - 过户费：2022-04-29 起沪深统一 0.001%，双边
    - 佣金：券商竞争后普遍在万 1.5 ~ 万 3，含规费；多数券商最低 5 元，
      部分券商可"免5"。min_commission 设为 0 表示已谈到免 5。
    """

    stamp_tax: float = 0.0005        # 卖出单边
    transfer_fee: float = 0.00001    # 双边
    commission: float = 0.00025      # 双边，万 2.5
    min_commission: float = 5.0      # 单笔佣金最低收取
    slippage_bps: float = 8.0        # 冲击成本+滑点，单边基点(1bp=0.01%)

    def buy_cost(self, turnover: float) -> float:
        """买入一笔金额为 turnover 的显性成本（不含滑点）。"""
        if turnover <= 0:
            return 0.0
        comm = max(turnover * self.commission, self.min_commission)
        return comm + turnover * self.transfer_fee

    def sell_cost(self, turnover: float) -> float:
        """卖出一笔金额为 turnover 的显性成本（不含滑点）。"""
        if turnover <= 0:
            return 0.0
        comm = max(turnover * self.commission, self.min_commission)
        return comm + turnover * self.transfer_fee + turnover * self.stamp_tax

    def round_trip_bps(self) -> float:
        """一次完整买卖的成本，单位基点。用于估算策略的换手率上限。"""
        explicit = (2 * self.commission + 2 * self.transfer_fee + self.stamp_tax) * 1e4
        return explicit + 2 * self.slippage_bps


# 默认成本模型：不要为了让回测好看而调低它。
DEFAULT_COST = CostModel()
