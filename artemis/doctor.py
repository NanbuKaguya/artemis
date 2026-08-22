"""安装体检：告诉你现在卡在哪，以及下一条该敲什么命令。

为什么需要它：这套系统有七份文档、三条部署路径、十几个可选依赖。
读文档找答案比跑一条命令慢得多，而且容易读串。

设计原则：**按依赖顺序检查，停在第一个阻塞项**。
一次报十个问题只会让人不知道先修哪个 —— 而且后九个往往是第一个的连锁反应。
"""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

STATUS_OK = "ok"
STATUS_WARN = "warn"       # 能跑，但功能残缺
STATUS_BLOCK = "block"     # 跑不了，必须先修


@dataclass
class Step:
    name: str
    status: str
    detail: str
    fix: str | None = None
    why: str | None = None


def _try_import(mod: str) -> str | None:
    try:
        m = importlib.import_module(mod)
        return getattr(m, "__version__", "installed")
    except ImportError:
        return None


def _python_exe() -> str:
    """给出的修复命令要能直接复制粘贴，所以用真实解释器路径。"""
    return sys.executable


def check_all(watchlist: str = "watchlist.txt") -> list[Step]:
    steps: list[Step] = []
    py = _python_exe()

    # ---------- 1. Python 版本 ----------
    v = sys.version_info
    steps.append(Step(
        "Python 版本",
        STATUS_OK if v >= (3, 11) else STATUS_BLOCK,
        f"{v.major}.{v.minor}.{v.micro}",
        fix=None if v >= (3, 11) else "需要 Python 3.11+，请升级后重建虚拟环境",
        why="代码用了 zoneinfo 和 3.11 的类型语法",
    ))

    # ---------- 2. 核心依赖 ----------
    missing = [m for m in ("pandas", "numpy", "pyarrow", "scipy") if not _try_import(m)]
    steps.append(Step(
        "核心依赖",
        STATUS_OK if not missing else STATUS_BLOCK,
        "齐全" if not missing else f"缺 {missing}",
        fix=None if not missing else f"{py} -m pip install -e .",
        why="没有它们什么都跑不了",
    ))

    # ---------- 3. 数据源 ----------
    ak = _try_import("akshare")
    steps.append(Step(
        "AkShare（数据源）",
        STATUS_OK if ak else STATUS_BLOCK,
        f"v{ak}" if ak else "未安装",
        fix=None if ak else f"{py} -m pip install -e '.[data]'",
        why="排雷检查要靠它取全市场快照。没有它 Lite 的核心功能用不了",
    ))

    # ---------- 4. 网络（只在 akshare 装好后才有意义）----------
    if ak:
        ok, detail = _probe_quote_api()
        steps.append(Step(
            "行情源连通性",
            STATUS_OK if ok else STATUS_BLOCK,
            detail,
            fix=None if ok else ("检查网络/代理。境外服务器和部分公司网络连不上国内行情源；"
                                 "若走代理，确认 HTTPS_PROXY 允许 CONNECT 到东财"),
            why="AkShare 底层是爬虫，直连东财/新浪",
        ))

    # ---------- 5. 交易日历 ----------
    from .calendar import TradingCalendar

    cal = TradingCalendar()
    st = cal.status
    has_cal = st.source in ("cache", "fetched")
    stale = (st.stale_days or 0) > 0
    steps.append(Step(
        "交易日历",
        STATUS_OK if (has_cal and not stale) else STATUS_WARN,
        (f"覆盖到 {st.covered_to}" if has_cal else "无缓存") +
        (f"（已过期 {st.stale_days} 天）" if stale else ""),
        fix=None if (has_cal and not stale) else f"{py} -m artemis.service calendar-refresh",
        why="没有它，节假日会被当成交易日。系统会在 basis 字段标明降级，但你得先看到",
    ))

    # ---------- 6. 自选股 ----------
    wp = Path(watchlist)
    codes: list[str] = []
    if wp.exists():
        codes = [l.strip() for l in wp.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    steps.append(Step(
        "自选股清单",
        STATUS_OK if codes else STATUS_WARN,
        f"{len(codes)} 只" if codes else f"{wp} 不存在或为空",
        fix=None if codes else f"{py} -m artemis.lite watch   # 会自动创建模板，填好后再跑一次",
        why="排雷检查的输入。空的话每天的简报没内容",
    ))

    # ---------- 7. 本地 LLM（可选）----------
    base = os.environ.get("ARTEMIS_LLM_BASE_URL", "")
    if base:
        u = urlparse(base)
        alive = _probe(u.hostname or "localhost", u.port or 80)
        steps.append(Step(
            "本地 Hermes",
            STATUS_OK if alive else STATUS_WARN,
            f"{base} {'可达' if alive else '连不上'}",
            fix=None if alive else "启动推理服务（如 OLLAMA_CONTEXT_LENGTH=16384 ollama serve）",
            why="可选。简报不依赖它，挂了只是少一段叙述",
        ))
    else:
        steps.append(Step(
            "本地 Hermes", STATUS_WARN, "未配置 ARTEMIS_LLM_BASE_URL",
            fix="export ARTEMIS_LLM_BASE_URL=http://localhost:11434/v1",
            why="可选。不配就是纯事实简报，功能不受影响",
        ))

    return steps


def _probe(host: str, port: int, timeout: float = 4.0) -> bool:
    """裸 TCP 探测。只用于本地服务（如 Ollama）—— 本地端口通了基本就是能用。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_quote_api(timeout: float = 8.0) -> tuple[bool, str]:
    """真实请求行情接口，而不是裸 TCP 连通性探测。

    为什么不能用 TCP 探测：在代理后面，TCP 层能连上（连的是代理），
    但代理可能拒绝 CONNECT 到目标域名 —— 实测中这会给出假阳性，
    体检说"网络 OK"，然后 AkShare 神秘失败，用户完全无从下手。

    所以必须发一个真请求并检查响应内容。
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           "?secid=1.000001&fields1=f1&fields2=f51&klt=101&fqt=1"
           "&beg=20240101&end=20240110")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(2048).decode("utf-8", "replace")
        if '"data"' in body or '"rc"' in body:
            return True, "东财行情接口可用"
        return False, f"东财返回了非预期内容（前 60 字：{body[:60]!r}）"
    except urllib.error.HTTPError as e:
        return False, f"东财返回 HTTP {e.code}（多半是代理或风控拦截）"
    except urllib.error.URLError as e:
        return False, f"无法请求东财：{str(e.reason)[:70]}"
    except OSError as e:
        return False, f"网络错误：{str(e)[:70]}"


def render(steps: list[Step]) -> str:
    icon = {STATUS_OK: "✓", STATUS_WARN: "▲", STATUS_BLOCK: "✗"}
    L = ["=" * 66, "  Artemis 安装体检", "=" * 66, ""]

    for s in steps:
        L.append(f"{icon[s.status]} {s.name:<16} {s.detail}")

    blockers = [s for s in steps if s.status == STATUS_BLOCK]
    warns = [s for s in steps if s.status == STATUS_WARN]

    L.append("")
    if blockers:
        first = blockers[0]
        L += ["-" * 66,
              f"下一步：修 {first.name}",
              "", f"  原因：{first.why}", ""]
        if first.fix:
            L += ["  执行：", f"    {first.fix}", ""]
        if len(blockers) > 1:
            L.append(f"  （还有 {len(blockers)-1} 个阻塞项，修完这个再跑一次体检。"
                     f"后面的问题常常是这个的连锁反应）")
    elif warns:
        first = warns[0]
        L += ["-" * 66,
              "没有阻塞项，可以开始用了。以下是功能残缺的地方：", ""]
        for w in warns:
            L.append(f"  ▲ {w.name}：{w.why}")
            if w.fix:
                L.append(f"     {w.fix}")
        L += ["", f"  最该先补的是「{first.name}」"]
    else:
        L += ["-" * 66, "全部就绪。开始用：", "",
              "    python -m artemis.lite watch      # 每天开盘前",
              "    python -m artemis.lite log        # 每次下单前",
              "    python -m artemis.lite review     # 每周"]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    steps = check_all()
    print(render(steps))
    if any(s.status == STATUS_BLOCK for s in steps):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
