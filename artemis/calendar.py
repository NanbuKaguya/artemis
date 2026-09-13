"""A 股交易日历。

为什么这是部署的第一块：无人值守运行时最容易犯的两个错都在这里——
1. 在非交易日跑，产出一份基于昨天数据的"今日清单"
2. 用过期数据当新鲜数据，而且不报错

日历本身要联网取，但取到之后必须能离线用：agent 半夜跑的时候
不该因为一个日历请求失败就整个停摆。所以设计成"缓存优先 + 明确降级"。

刻意不硬编码节假日：中国节假日每年由国务院办公厅通知确定，
含调休，我记错一天就会让你在休市日下单或在开市日踏空。
宁可明确告诉你"日历过期了，我只能按工作日判断"。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CN_TZ = ZoneInfo("Asia/Shanghai")
def _default_cache() -> Path:
    """和 lite.py / service.py 共用 ARTEMIS_DATA_DIR。

    写死相对路径在 launchd 下会解析到 /，日历缓存于是永远读不回来，
    每次都退化成"按工作日判断"—— 而这个降级只在 stderr 说一句。
    """
    return Path(os.environ.get("ARTEMIS_DATA_DIR", "./data_cache")) / "trade_calendar.json"


# 兼容旧引用；真正取路径请用 _default_cache()
DEFAULT_CACHE = _default_cache()

# A 股交易时段（北京时间）
OPEN_AM, CLOSE_AM = "09:30", "11:30"
OPEN_PM, CLOSE_PM = "13:00", "15:00"


@dataclass
class CalendarStatus:
    ok: bool
    source: str            # 'cache' | 'fetched' | 'weekday_fallback'
    covered_to: date | None
    stale_days: int | None
    warning: str | None


class TradingCalendar:
    def __init__(self, cache_path: str | Path | None = None):
        # 默认值在调用时解析，不在 import 时。模块级常量会把
        # ARTEMIS_DATA_DIR 冻在第一次 import 的取值上。
        self.cache_path = Path(cache_path) if cache_path is not None else _default_cache()
        self._days: set[date] = set()
        self._status = CalendarStatus(False, "none", None, None, "尚未加载")
        self._load_cache()

    # ---------------------------------------------------------------- 加载
    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._days = {date.fromisoformat(d) for d in raw["days"]}
            covered = max(self._days) if self._days else None
            stale = (self.today() - covered).days if covered else None
            self._status = CalendarStatus(
                ok=True, source="cache", covered_to=covered, stale_days=stale,
                warning=(f"日历只覆盖到 {covered}，已过期 {stale} 天，请跑 refresh()"
                         if stale is not None and stale > 0 else None),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._status = CalendarStatus(False, "none", None, None,
                                          f"日历缓存损坏：{e}")

    def refresh(self, start: str = "2015-01-01", end: str | None = None) -> CalendarStatus:
        """从数据源拉取交易日历并落地。建议每月跑一次，或在年初节假日安排公布后跑。"""
        try:
            import akshare as ak
        except ImportError:
            self._status = CalendarStatus(
                bool(self._days), self._status.source, self._status.covered_to,
                self._status.stale_days, "未装 akshare，无法刷新日历")
            return self._status

        end = end or (self.today() + pd.Timedelta(days=400)).isoformat()
        try:
            df = ak.tool_trade_date_hist_sina()
            col = df.columns[0]
            d = pd.to_datetime(df[col])
            d = d[(d >= start) & (d <= end)]
            self._days = {x.date() for x in d}
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "fetched_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                "days": sorted(x.isoformat() for x in self._days),
            }, ensure_ascii=False), encoding="utf-8")
            covered = max(self._days)
            self._status = CalendarStatus(True, "fetched", covered,
                                          (self.today() - covered).days, None)
        except Exception as e:  # noqa: BLE001 - 上游异常类型不稳定
            self._status = CalendarStatus(
                bool(self._days), self._status.source, self._status.covered_to,
                self._status.stale_days, f"刷新失败：{str(e)[:80]}")
        return self._status

    # ---------------------------------------------------------------- 查询
    @staticmethod
    def today() -> date:
        return datetime.now(CN_TZ).date()

    @staticmethod
    def now() -> datetime:
        return datetime.now(CN_TZ)

    def is_trading_day(self, d: date | None = None) -> tuple[bool, str]:
        """返回 (是否交易日, 依据)。依据字段是为了让调用方知道结论有多可信。"""
        d = d or self.today()
        if self._days:
            covered = max(self._days)
            if d <= covered:
                return d in self._days, "calendar"
            # 超出日历覆盖范围：明确降级，不假装知道
            return d.weekday() < 5, f"weekday_fallback(日历只到 {covered})"
        return d.weekday() < 5, "weekday_fallback(无日历缓存，节假日无法识别)"

    def prev_trading_day(self, d: date | None = None) -> date | None:
        d = d or self.today()
        past = sorted(x for x in self._days if x < d)
        return past[-1] if past else None

    def session(self, ts: datetime | None = None) -> str:
        """当前处于哪个时段。agent 用它决定"现在该做盘前还是盘后"。"""
        ts = ts or self.now()
        ok, _ = self.is_trading_day(ts.date())
        if not ok:
            return "closed_holiday"
        hm = ts.strftime("%H:%M")
        if hm < "09:15":
            return "premarket"
        if hm < OPEN_AM:
            return "call_auction"
        if hm <= CLOSE_AM:
            return "trading_am"
        if hm < OPEN_PM:
            return "lunch_break"
        if hm <= CLOSE_PM:
            return "trading_pm"
        return "postmarket"

    @property
    def status(self) -> CalendarStatus:
        return self._status

    def to_dict(self) -> dict:
        s = self._status
        ok, basis = self.is_trading_day()
        return {
            "today": self.today().isoformat(),
            "now_cn": self.now().isoformat(timespec="seconds"),
            "is_trading_day": ok,
            "basis": basis,
            "session": self.session(),
            "calendar_source": s.source,
            "covered_to": s.covered_to.isoformat() if s.covered_to else None,
            "stale_days": s.stale_days,
            "warning": s.warning,
        }
