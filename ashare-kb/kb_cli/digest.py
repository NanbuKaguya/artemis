"""生成 digest/latest.md —— 下一次会话读的东西。

这是整个库唯一会被 Claude 读到的文件。它不是索引，是契约 + 证据。
顺序刻意如此：契约在最前面，因为如果 Claude 只读了前二十行，
它至少知道"以库为准，我是错的那个"。
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path

CONTRACT = """## 操作契约 —— 读到这里的 Claude 请照做

1. **这个库是 adversary，不是备忘录。** 你的输出与某条 verified 断言冲突时，
   以库为准，你是错的那个。不要替库找补，指出冲突。
2. **库里没有状态层**，也不要从库里推断当下状态。成交额、两融余额、估值分位、
   当前风格 —— 这些一律不在库中，问就是不知道，去查实时数据。
3. **你在对话里给出的任何判断都不是知识**，直到它被 `kb lead` 记下、
   被回溯到 L1-L3、被一个脚本验证通过。判断请随口说，但要说清它是几级来源。
4. **L4/L5（财经媒体、自媒体、转述）永远不能支撑 verified。** 数据库的触发器
   会挡住，你也别绕。
5. 看到 falsified 那一节就想清楚：那些都是上一个我信誓旦旦给出的东西。
"""


def inline(text: object) -> str:
    """把断言文本压成单行，再放进 Markdown。

    **这是这个文件里最重要的一个函数。**

    digest 是整个系统唯一真正起作用的产物 —— 下一个会话的 Claude 只读它，
    而且契约第一条告诉它"以库为准，你是错的那个"。断言文本的来源是
    财经媒体和自媒体转述，也就是我从别处粘进来的东西。

    不压成单行的话，一条 L5 线索只要在正文里带上换行和 `## verified 断言`，
    digest 里就会出现一整节伪造的已验证断言，带伪造的 id、伪造的来源等级、
    伪造的验证日期。下一个 Claude 会照单全收 —— 它没有别的依据。

    所有的质量门守的都是数据库。digest 是从库里的文本拼出来的，
    渲染这一步不设防，前面那些门就全部绕过去了：
    gates guard the namespace, writes bypass via bytes。

    压成单行就够了：Markdown 的结构（标题、列表、代码围栏）都必须从行首开始，
    没有换行就造不出行首。而且断言本来就该是"一句话"。
    """
    return " ".join(str("" if text is None else text).split())


def _fmt_claim(r: sqlite3.Row) -> str:
    out = [f"- **{inline(r['id'])}** — {inline(r['statement'])}"]
    out.append(f"  - 推翻条件：{inline(r['if_wrong'])}")
    src = f"L{int(r['source_tier'])} · {inline(r['source_ref'])}"
    if r["last_verified"]:
        src += f" · 最后验证 {inline(r['last_verified'])}"
    out.append(f"  - 来源：{src}")
    return "\n".join(out)


def _section(conn, title, sql, params=(), empty=None) -> str:
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return f"## {title}\n\n{empty or '（无）'}\n" if empty is not None else ""
    body = [f"## {title}（{len(rows)} 条）\n"]
    layer_seen = None
    for r in rows:
        if "layer" in r.keys() and r["layer"] != layer_seen:
            layer_seen = r["layer"]
            body.append(f"\n### {inline(layer_seen)}\n")
        body.append(_fmt_claim(r))
    return "\n".join(body) + "\n"


def render(conn: sqlite3.Connection) -> str:
    counts = dict(conn.execute(
        "SELECT status, count(*) FROM claim GROUP BY status").fetchall())
    n = {s: counts.get(s, 0) for s in ("verified", "lead", "stale", "falsified")}

    parts = [
        f"# ashare-kb digest — {_dt.date.today().isoformat()}",
        "",
        f"verified **{n['verified']}** · lead {n['lead']} · stale {n['stale']} · falsified {n['falsified']}",
        "",
        "> verified 少不是失败。关于 A 股，能被硬证据支撑的东西本来就不多，",
        "> 库在诚实地告诉你这件事。用总条目数度量这个库等于度量它有没有在跑，",
        "> 而不是它有没有产出有效输出。",
        "",
        CONTRACT,
    ]

    parts.append(_section(
        conn, "verified 断言",
        "SELECT * FROM claim WHERE status='verified' ORDER BY layer, source_tier, id",
        empty="**一条都没有。** 这个库还没有挣到任何东西 —— 下面的 lead 全部未经验证，"
              "在这次会话里不要把它们当作事实使用。",
    ))
    parts.append(_section(
        conn, "最近 falsified —— 教训",
        "SELECT * FROM claim WHERE status='falsified' ORDER BY id",
        empty="（还没有断言被打脸。如果半年后这一节仍然是空的，"
              "要怀疑的不是命中率，是 if_wrong 写得太软。）",
    ))
    parts.append(_section(
        conn, "stale —— 过期待重算",
        "SELECT * FROM claim WHERE status='stale' ORDER BY layer, id",
        empty="（无）",
    ))
    parts.append(_section(
        conn, "lead —— 待回溯 / 待验证",
        "SELECT * FROM claim WHERE status='lead' ORDER BY source_tier, layer, id",
        empty="（无）",
    ))

    parts.append(
        "---\n\n"
        "本文件由 `kb digest` 生成，不要手改 —— 任何改变库状态的命令都会重写它。\n"
        "会话末尾请跑 `kb stale`。\n\n"
        "下一步做什么写在 `ROADMAP.md` 里；这个库的操作契约和它最可能的死法\n"
        "写在仓库根目录的 `CLAUDE.md` 里。\n"
    )
    return "\n".join(p for p in parts if p is not None)


def write(conn_root: Path, conn: sqlite3.Connection) -> list[Path]:
    text = render(conn)
    out = []
    for name in ("latest.md", f"{_dt.date.today().isoformat()}.md"):
        p = conn_root / "digest" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        out.append(p)
    return out
