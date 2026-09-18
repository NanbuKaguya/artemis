"""falsified 断言的墓碑文件。

被打脸的断言不删除 —— 它是教训，教训比断言值钱。
数据库里保留 status='falsified' 的行（这样 digest 能查到），
同时在 ledger/falsified/ 下留一份人读的记录。
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from .digest import inline

TEMPLATE = """# FALSIFIED: {id}

    {statement}

| 字段 | 值 |
|---|---|
| 层 | {layer} |
| 来源分级 | L{source_tier} |
| 来源 | {source_ref} |
| 推翻条件（当初写下的） | {if_wrong} |
| 建立于 | {created_at} |
| 最后一次 verified | {last_verified} |
| 验证脚本 | {verify_script} |
| 打脸于 | {falsified_at} |

## 为什么错了

{why}

## 证据

```
{evidence}
```

## 教训

<!-- 手写。这一节是这个文件存在的唯一理由。
     "断言错了"不是教训，"我当初凭什么相信它"才是。 -->
"""


def _cell(value: object) -> str:
    """墓碑的表格单元格。

    先压成单行（换行会把表格拆散），再转义竖线 —— 正文里的 `|`
    会把内容挤到别的列去，来源等级看起来就成了另一个字段的值，
    而这份文件存在的意义正是让人事后复核"我当初凭什么相信它"。
    """
    return inline(value).replace("|", "\\|")


def write(root: Path, row: dict, why: str, evidence: str = "") -> Path:
    path = root / "ledger" / "falsified" / f"{row['id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = TEMPLATE.format(
        falsified_at=_dt.date.today().isoformat(),
        why=why.strip() or "(未填写)",
        evidence=(evidence.strip() or "(无)"),
        **{k: ("—" if row.get(k) in (None, "") else _cell(row.get(k))) for k in
           ("id", "statement", "layer", "source_tier", "source_ref",
            "if_wrong", "created_at", "last_verified", "verify_script")},
    )
    path.write_text(body, encoding="utf-8")
    return path
