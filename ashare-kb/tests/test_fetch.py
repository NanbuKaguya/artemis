"""kb fetch 的测试。

联网那一段在这个沙箱里测不了（四个监管域名全被 egress 策略 403）。
所以这里测的是**拿到字节之后的一切**：解码、抽文、来源记录、覆盖保护。
--from-file 那条路完全不碰网络，所以是完整覆盖的 —— 而它也是更现实的
一条路，交易所规则多半是 PDF 或藏在门户后面。
"""

from __future__ import annotations

import json

import pytest

from kb_cli import fetch
from kb_cli.db import KBError

from conftest import ROOT

GB_HTML = """<html><head>
<meta http-equiv="Content-Type" content="text/html; charset=gb2312">
<title>某某意见</title>
<script>var x = "2024-04-12";</script><style>.a{color:red}</style>
</head><body>
<div class="nav">首页 &gt; 政策</div>
<h1>关于加强监管防范风险推动资本市场高质量发展的若干意见</h1>
<p>本意见与后续配套制度规则共同形成“1+N”政策体系。</p>
<p class="date">国务院<br/>二〇二四年四月十二日</p>
</body></html>"""


# ---------------------------------------------------------------------------
# 解码 —— 猜错编码会把整份快照变成乱码，而脚本只会说"找不到短语"
# ---------------------------------------------------------------------------

def test_charset_from_header_wins():
    assert fetch.detect_charset(b"<html>", "text/html; charset=UTF-8") == "utf-8"


def test_charset_falls_back_to_meta_tag():
    assert fetch.detect_charset(GB_HTML.encode("gb18030")) == "gb2312"


def test_charset_absent_is_empty():
    assert fetch.detect_charset(b"plain bytes") == ""


def test_gb2312_is_decoded_as_gb18030():
    """声明 gb2312 的中文页面实际常含只有 GB18030 有的字符。"""
    raw = "二〇二四年　全角空格".encode("gb18030")
    assert "二〇二四年" in fetch.decode(raw, "text/html; charset=gb2312")


def test_utf8_round_trip():
    assert fetch.decode("融券卖出".encode("utf-8"), "charset=utf-8") == "融券卖出"


def test_undecodable_bytes_do_not_crash():
    assert isinstance(fetch.decode(b"\xff\xfe\x00bad"), str)


# ---------------------------------------------------------------------------
# HTML -> 文本
# ---------------------------------------------------------------------------

def test_script_and_style_are_dropped():
    text = fetch.html_to_text(GB_HTML)
    assert "var x" not in text and "color:red" not in text
    assert "2024-04-12" not in text        # 埋点里的日期不该进正文


def test_body_text_survives():
    text = fetch.html_to_text(GB_HTML)
    assert "关于加强监管防范风险推动资本市场高质量发展的若干意见" in text
    assert "“1+N”政策体系" in text
    assert "二〇二四年四月十二日" in text


def test_br_becomes_a_line_break():
    """<br/> 不断行的话，"国务院二〇二四年四月十二日" 会连成一串。"""
    text = fetch.html_to_text("<p>国务院<br/>二〇二四年四月十二日</p>")
    assert "国务院二〇二四年" not in text        # 没连在一起
    assert "国务院" in text and "二〇二四年四月十二日" in text


def test_blank_lines_are_collapsed():
    assert "\n\n\n" not in fetch.html_to_text("<div></div>" * 20 + "<p>甲</p>")


# ---------------------------------------------------------------------------
# 抽取器分派
# ---------------------------------------------------------------------------

def test_extract_detects_html_without_content_type():
    _, kind = fetch.extract(GB_HTML.encode("gb18030"), "", "guize")
    assert kind == "html"


def test_extract_passes_plain_text_through():
    text, kind = fetch.extract("融券卖出\n".encode("utf-8"), "text/plain", "a.txt")
    assert (text, kind) == ("融券卖出\n", "text")


def test_plain_text_gets_a_trailing_newline():
    text, _ = fetch.extract(b"no newline", "text/plain", "a.txt")
    assert text.endswith("\n")


def test_pdf_without_pypdf_says_what_to_do():
    """没装 pypdf 时要给出可执行的下一步，而不是 ImportError 栈。"""
    try:
        import pypdf  # noqa: F401
    except ImportError:
        with pytest.raises(KBError, match="pypdf"):
            fetch.pdf_to_text(b"%PDF-1.4 fake")
    else:
        pytest.skip("装了 pypdf，这条路走不到")


# ---------------------------------------------------------------------------
# 快照与来源记录
# ---------------------------------------------------------------------------

URL = "https://www.gov.cn/zhengce/content/2024-04/12/content_6945548.htm"


def write(kb, *, force=False, url=URL, raw=None):
    return fetch.write_snapshot(
        kb, "gov-2024-04-12-guojiutiao.txt",
        raw if raw is not None else GB_HTML.encode("gb18030"),
        "text/html", url, "国务院若干意见", force)


def test_snapshot_and_sidecar_are_written(kb):
    path, meta = write(kb)
    assert path.exists()
    side = json.loads(fetch.meta_path(path).read_text("utf-8"))
    assert side["url"] == URL
    assert side["extractor"] == "html"
    assert len(side["raw_sha256"]) == 64
    assert side["raw_bytes"] == len(GB_HTML.encode("gb18030"))
    assert meta == side


def test_the_url_never_lands_in_the_snapshot_body(kb):
    """URL 里的 2024-04-12 正好是 date_variants 的候选之一。

    写进正文，快照就给自己作了证 —— 脚本会在"来源标注"里找到日期，
    然后声称原文支持这条断言。
    """
    path, _ = write(kb)
    body = path.read_text("utf-8")
    assert URL not in body
    assert "2024-04-12" not in body
    assert "content_6945548" not in body


def test_overwrite_is_refused_by_default(kb):
    write(kb)
    with pytest.raises(KBError, match="已存在"):
        write(kb)


def test_force_overwrites(kb):
    write(kb)
    path, meta = write(kb, raw="<p>换了内容</p>".encode("utf-8"), force=True)
    assert "换了内容" in path.read_text("utf-8")
    assert meta["raw_bytes"] == len("<p>换了内容</p>".encode("utf-8"))


def test_sha256_changes_when_the_page_changes(kb):
    _, first = write(kb)
    _, second = write(kb, raw=(GB_HTML + "<p>新增一款</p>").encode("gb18030"),
                      force=True)
    assert first["raw_sha256"] != second["raw_sha256"]


def test_every_wanted_snapshot_names_a_claim_that_exists():
    """WANTED 里的 claim id 必须真的存在。

    对着仓库committed 的账本核，不对着测试用的空库核 —— 断言被改名或删掉时
    这条会失败，否则 kb fetch 会一直提示一个指向不存在断言的下一步。
    """
    from kb_cli import ledger
    known = {e["claim_id"] for e in ledger.read_all(ROOT)}
    assert known, "仓库的 ledger/events.jsonl 是空的？"
    for name, (cid, doc, where) in fetch.WANTED.items():
        assert name.endswith(".txt"), name
        assert doc and where, name
        assert cid in known, f"{name} 指向不存在的断言 {cid}"


def test_every_wanted_claim_has_a_verify_script():
    """光有快照没有脚本，取回来也验不了。"""
    for name, (cid, _, _) in fetch.WANTED.items():
        assert (ROOT / "verify" / f"{cid}.py").exists(), f"{cid} 没有验证脚本"


# ---------------------------------------------------------------------------
# 快照名：verify 脚本的路径早就有这道检查，快照这边漏了
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "../../escaped.txt", "../x.txt", "a/b.txt", "/abs.txt",
    "..", ".", "", "   ",
])
def test_snapshot_names_cannot_escape_sources(kb, name):
    """不校验的话 kb fetch ../../x 会把文件写到库外面去。"""
    with pytest.raises(KBError, match="不能带路径"):
        fetch.write_snapshot(kb, name, b"x" * 600, "text/plain", "", "", False)


def test_a_plain_name_is_accepted(kb):
    path, _ = fetch.write_snapshot(
        kb, "gov-2024.txt", b"x" * 600, "text/plain", "", "", False)
    assert path.parent == kb / "sources"


def test_surrounding_whitespace_is_trimmed(kb):
    path, meta = fetch.write_snapshot(
        kb, "  gov-2024.txt  ", b"x" * 600, "text/plain", "", "", False)
    assert path.name == "gov-2024.txt"
    assert meta["snapshot"] == "gov-2024.txt"


def test_the_meta_suffix_is_reserved(kb):
    """.meta.json 是来源记录的命名空间。

    让快照占用它的话，另一份快照的来源记录会把这份快照的正文悄悄盖掉 ——
    而 sources/ 存在的唯一理由就是不让证据消失。
    """
    with pytest.raises(KBError, match="专用后缀"):
        fetch.write_snapshot(kb, "a.txt.meta.json", b"x" * 600,
                             "text/plain", "", "", False)


def test_a_sidecar_never_clobbers_an_existing_file(kb):
    """覆盖检查要同时守正文和来源记录两条路径。"""
    (kb / "sources").mkdir(parents=True, exist_ok=True)
    (kb / "sources" / "a.txt.meta.json").write_text("别人的东西", encoding="utf-8")
    with pytest.raises(KBError, match="已存在"):
        fetch.write_snapshot(kb, "a.txt", b"x" * 600, "text/plain", "", "", False)
    assert (kb / "sources" / "a.txt.meta.json").read_text("utf-8") == "别人的东西"
