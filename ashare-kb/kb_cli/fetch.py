"""kb fetch —— 把原文取回来变成快照，并留下可复核的来源记录。

## 为什么来源信息不写进快照正文

快照是 `require_phrases` 搜索的对象。把 URL 和抓取时间写进文件开头，
搜索就会把它们一起搜进去 —— 而 URL 里很可能就带着日期
（`.../2024-04-12/...`），那正是 `date_variants()` 的候选之一。
于是快照给自己作了证。

所以来源另存 `<快照名>.meta.json`：URL、抓取时间、原始字节的 sha256。
sha256 的用处是下次重抓能看出页面变没变 —— 法规被悄悄修订时，
字节会变，而你不会收到任何通知。

## 为什么默认不覆盖

`sources/README.md` 里写着：原文变了要存新快照，不要原地覆盖。
覆盖掉的话，依赖旧快照的那条断言就失去了它当初的依据，
墓碑上的教训也没法复核了。所以覆盖要显式 --force。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .db import KBError

TIMEOUT = 60
UA = "ashare-kb/1.0 (snapshot archiver)"

# 需要哪些快照、给哪条断言、去哪里找。
# **刻意不写死 URL** —— 我不确定这四份文件的确切地址，写一个会 404 的
# 链接比不写更糟：它看起来像是验证过的。找到链接后用 --url 传进来。
WANTED = {
    "gov-2024-04-12-guojiutiao.txt": (
        "inst-69d8655b",
        "国务院《关于加强监管防范风险推动资本市场高质量发展的若干意见》",
        "www.gov.cn 政策文件库",
    ),
    "sse-kechuangban-shidangxing.txt": (
        "inst-625f832d",
        "上交所 科创板股票交易特别规定 / 投资者适当性管理办法（含适当性条款那节）",
        "上交所规则库",
    ),
    "sse-jiaoyi-guize.txt": (
        "inst-623b43f8",
        "上交所《交易规则》含回转交易那一节",
        "上交所规则库",
    ),
    "sse-rongzirongquan-xize.txt": (
        "inst-623b43f8",
        "上交所《融资融券交易实施细则》",
        "上交所规则库",
    ),
}


# ---------------------------------------------------------------------------
# 解码与抽取 —— 纯函数，没有网络也能测
# ---------------------------------------------------------------------------

_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I)


def detect_charset(raw: bytes, content_type: str = "") -> str:
    """先看响应头，再看 meta 标签，最后猜。

    编码猜错会把整份快照变成乱码，而 require_phrases 只会说"找不到短语" ——
    看起来像断言的问题，其实是解码的问题。所以宁可多试几种。
    """
    m = re.search(r"charset\s*=\s*([\w\-]+)", content_type, re.I)
    if m:
        return m.group(1).lower()
    m = _META_CHARSET.search(raw[:4096])
    if m:
        return m.group(1).decode("ascii", "ignore").lower()
    return ""


def decode(raw: bytes, content_type: str = "") -> str:
    charset = detect_charset(raw, content_type)
    # gb2312/gbk 声明的中文页面实际常含 GB18030 才有的字符，一律按 gb18030 解
    candidates = [c for c in (charset, "utf-8", "gb18030") if c]
    if charset in ("gb2312", "gbk"):
        candidates = ["gb18030", "utf-8"]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "head", "svg", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "section", "article",
             "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip() + "\n"


def pdf_to_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise KBError(
            "这是 PDF，需要 pypdf 才能抽文本：pip install pypdf\n"
            "  或者自己另存为纯文本，再用 kb fetch <名字> --from-file <文件> --url <原址>"
        ) from None
    import io
    pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages]
    text = "\n\n".join(pages).strip() + "\n"
    if len(text.strip()) < 50:
        raise KBError(
            "PDF 里抽不出文字 —— 多半是扫描件。先做 OCR，或找同一文件的网页版。\n"
            "  扫描版存下来也没用：require_phrases 在图片里找不到字。")
    return text


def extract(raw: bytes, content_type: str, name_hint: str) -> tuple[str, str]:
    """返回 (纯文本, 用了哪个抽取器)。"""
    lowered = (content_type or "").lower()
    if "pdf" in lowered or name_hint.lower().endswith(".pdf"):
        return pdf_to_text(raw), "pdf"
    text = decode(raw, content_type)
    if "html" in lowered or name_hint.lower().endswith((".html", ".htm")) \
            or "<html" in text[:2048].lower():
        return html_to_text(text), "html"
    return text if text.endswith("\n") else text + "\n", "text"


# ---------------------------------------------------------------------------
# 取
# ---------------------------------------------------------------------------

def http_get(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise KBError(f"HTTP {exc.code} —— {url}") from None
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "403" in reason or "407" in reason or "CONNECT" in reason.upper():
            raise KBError(
                f"代理拒绝了这个域名（{url}）。\n"
                "  远程沙箱的 egress 策略屏蔽了全部中文数据源和监管源 ——\n"
                "  这一步只能在你自己的机器上跑，或者手工下载后用 --from-file。"
            ) from None
        raise KBError(f"取不到 {url}: {reason}") from None


META_SUFFIX = ".meta.json"


def meta_path(snapshot: Path) -> Path:
    return snapshot.with_name(snapshot.name + META_SUFFIX)


def check_name(name: str) -> str:
    """快照名必须是 sources/ 下的一个纯文件名。

    不校验的话 `kb fetch ../../x.txt` 会把文件写到库外面去 ——
    verify 脚本的路径早就有这道检查，快照这边漏了，不一致本身就是味道。
    """
    clean = name.strip()
    if not clean or clean in (".", "..") or Path(clean).name != clean:
        raise KBError(
            f"快照名只能是 sources/ 下的一个文件名，不能带路径: {name!r}\n"
            "  看 kb fetch --list 里的名字。")
    if clean.endswith(META_SUFFIX):
        # .meta.json 是来源记录的命名空间。让快照占用它的话，
        # 另一份快照的来源记录会把这份快照的正文悄悄盖掉 ——
        # 而 sources/ 存在的唯一理由就是不让证据消失。
        raise KBError(f"{META_SUFFIX} 是来源记录专用后缀，快照不能叫这个名字: {name!r}")
    return clean


def write_snapshot(root: Path, name: str, raw: bytes, content_type: str,
                   url: str, source_note: str, force: bool) -> tuple[Path, dict]:
    name = check_name(name)
    path = root / "sources" / name
    # 两条路径都要查：正文和来源记录。只守正文的话，
    # 一份来源记录可以把另一份快照的正文悄悄盖掉。
    for target in (path, meta_path(path)):
        if target.exists() and not force:
            raise KBError(
                f"{target.relative_to(root)} 已存在。\n"
                "  原文修订了就存一份新快照（换个文件名），不要原地覆盖 ——\n"
                "  覆盖掉的话，依赖旧快照的断言就失去了当初的依据。\n"
                "  确实要覆盖就加 --force。")

    text, extractor = extract(raw, content_type, url or name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    meta = {
        "snapshot": name,
        "url": url or None,
        "source": source_note or None,
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "content_type": content_type or None,
        "extractor": extractor,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "text_chars": len(text),
    }
    meta_path(path).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, meta
