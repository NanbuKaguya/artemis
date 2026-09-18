"""akshare 数据层 —— 结构层断言的取数与算数。

没有 Wind/Choice，用 akshare（背后是东财等公开接口）。
**口径差异会直接变成断言的真假差异**，所以口径写在这里，不写在脚本里。

设计上只有一条规矩：**取数和算数分开。**
算数是纯函数，没有网络也能测；取数失败一律 inconclusive，
绝不降级成"算出来了"。这是 verify/README.md 那条退出码契约的延伸 ——
拿不到数据不是证据，把它当证据，库就开始撒谎。

## 口径（钉死，否则断言不可证伪）

- 价格：前复权（`adjust="qfq"`）
- 区间涨跌幅：以区间开始前最后一个交易日的收盘价为基准
- 样本：区间开始前已有交易数据的全部 A 股（等价于剔除区间内新上市）
- 含 ST；区间内退市的按其最后一个交易日计入（这是诚实的中位数的一部分）
- 指数：中证全指 000985（市值加权，与"个股中位数"可比）

## 成本

全A逐只历史 = 5000+ 次请求，第一次跑要一到两小时。
逐只缓存在 `.cache/hist/` 下，中断可续、可复用，第二次跑是秒级。
"""

from __future__ import annotations

import csv
import datetime as _dt
import os
from pathlib import Path

import kbverify as kv

CACHE_DIRNAME = ".cache"
INDEX_ALL_SHARE = "000985"  # 中证全指
PRE_WINDOW_DAYS = 30        # 多取一段，保证拿得到区间前的基准收盘价


# ---------------------------------------------------------------------------
# 纯函数 —— 没有网络也能测
# ---------------------------------------------------------------------------

def last_complete_quarters(n: int, today: _dt.date) -> list[tuple[str, str, str]]:
    """最近 n 个**已结束**的自然季度，早的在前。

    返回 [(标签, 起始日 YYYYMMDD, 结束日 YYYYMMDD), ...]。
    当前季度不算 —— 半个季度的收益和整个季度的收益不可比。
    """
    q = (today.month - 1) // 3          # 0-3，当前季度
    year, idx = today.year, q - 1       # 上一个已结束的季度
    out = []
    for _ in range(n):
        if idx < 0:
            year, idx = year - 1, 3
        start = _dt.date(year, idx * 3 + 1, 1)
        end = _dt.date(year + (idx == 3), (idx * 3 + 4 - 1) % 12 + 1, 1) - _dt.timedelta(days=1)
        out.append((f"{year}Q{idx + 1}", start.strftime("%Y%m%d"), end.strftime("%Y%m%d")))
        idx -= 1
    return list(reversed(out))


def window_return(rows: list[tuple[str, float]], start: str, end: str) -> float | None:
    """区间涨跌幅，基准是区间开始前最后一个交易日的收盘价。

    rows 是按日期升序的 [(YYYYMMDD, 收盘价), ...]。

    返回 None 表示这只股票不进样本：
      - 区间前没有交易数据 —— 区间内新上市，剔除
      - 区间内没有交易数据 —— 整段停牌或已退市，剔除
    两种情况都必须是 None 而不是 0.0：把它们当成"涨跌幅为零"
    会把中位数往上拉，而这条断言比的正是中位数。
    """
    before = [c for d, c in rows if d < start]
    inside = [c for d, c in rows if start <= d <= end]
    if not before or not inside:
        return None
    base = before[-1]
    if base <= 0:
        return None
    return inside[-1] / base - 1.0


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid, even = len(s) // 2, len(s) % 2 == 0
    return (s[mid - 1] + s[mid]) / 2 if even else s[mid]


def breadth(values: list[float]) -> tuple[int, int]:
    """(上涨只数, 总只数)。严格大于 0 才算上涨 —— 平盘不算。"""
    return sum(1 for v in values if v > 0), len(values)


# ---------------------------------------------------------------------------
# 取数 —— 失败一律 inconclusive
# ---------------------------------------------------------------------------

def require_akshare():
    try:
        import akshare as ak
    except ImportError:
        kv.inconclusive(
            "akshare 未安装。pip install akshare（见 requirements.txt）。"
            "注意 Debian 系统 Python 上 jsonpath 构建会失败，用干净的 venv。")
    return ak


def cache_dir() -> Path:
    d = kv.root() / CACHE_DIRNAME / "hist"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_cache(path: Path) -> list[tuple[str, float]] | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return [(r[0], float(r[1])) for r in csv.reader(fh) if r]
    except (OSError, ValueError, IndexError):
        return None  # 缓存坏了就当没有，重新取


def _write_cache(path: Path, rows: list[tuple[str, float]]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    tmp.replace(path)  # 原子替换：中断不会留下半截缓存


def _extract_closes(df) -> list[tuple[str, float]]:
    """从 akshare 的 DataFrame 里取 (日期, 收盘)。

    列名在 akshare 各版本间变过，所以按名字找而不是按位置取，
    找不到就抛 KeyError 让调用方转成 inconclusive —— 不猜。
    """
    cols = {str(c): c for c in df.columns}
    date_col = next((cols[c] for c in cols if c in ("日期", "date")), None)
    close_col = next((cols[c] for c in cols if c in ("收盘", "close")), None)
    if date_col is None or close_col is None:
        raise KeyError(f"认不出日期/收盘列: {list(df.columns)}")
    out = []
    for d, c in zip(df[date_col], df[close_col]):
        out.append((str(d).replace("-", "")[:8], float(c)))
    out.sort()
    return out


def history(symbol: str, start: str, end: str, *, kind: str = "stock") -> list[tuple[str, float]]:
    """逐只历史收盘价，带本地缓存。返回 [] 表示这只没有数据。"""
    ak = require_akshare()
    path = cache_dir() / f"{kind}-{symbol}-{start}-{end}.csv"
    cached = _read_cache(path)
    if cached is not None:
        return cached

    pre = (_dt.datetime.strptime(start, "%Y%m%d").date()
           - _dt.timedelta(days=PRE_WINDOW_DAYS)).strftime("%Y%m%d")
    fetch = (ak.stock_zh_a_hist if kind == "stock" else ak.index_zh_a_hist)
    kwargs = dict(symbol=symbol, period="daily", start_date=pre, end_date=end)
    if kind == "stock":
        kwargs["adjust"] = "qfq"

    df = fetch(**kwargs)
    rows = [] if df is None or df.empty else _extract_closes(df)
    _write_cache(path, rows)
    return rows


def universe() -> list[str]:
    """全部 A 股代码。上市日期不另外查 —— 区间前无数据的由 window_return 剔除。"""
    ak = require_akshare()
    df = ak.stock_info_a_code_name()
    col = next((c for c in df.columns if str(c) in ("code", "股票代码")), df.columns[0])
    return [str(c).zfill(6) for c in df[col]]


def index_return(symbol: str, start: str, end: str) -> float | None:
    return window_return(history(symbol, start, end, kind="index"), start, end)


def stock_returns(symbols: list[str], start: str, end: str, *, progress=None) -> list[float]:
    """逐只算区间涨跌幅，跳过不进样本的。

    取数报错不吞：让它冒到调用方，由脚本转成 inconclusive。
    吞掉错误会让样本悄悄变小，而中位数对样本缺失是敏感的。
    """
    out = []
    for i, sym in enumerate(symbols, 1):
        r = window_return(history(sym, start, end), start, end)
        if r is not None:
            out.append(r)
        if progress and i % progress == 0:
            print(f"  ... {i}/{len(symbols)} 只，入样 {len(out)}", flush=True)
    return out


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")
