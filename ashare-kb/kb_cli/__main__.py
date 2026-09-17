"""kb —— A股知识库的命令行。三条核心命令：lead / verify / stale。"""

from __future__ import annotations

import argparse
import sys

from . import commands as c
from .db import KBError

EPILOG = """核心循环:
  kb lead "<断言>" --layer institutional --tier 4 --src <来源> --if-wrong "<什么观测推翻它>"
  kb source <id> --tier 1 --src sources/xxx.pdf      # 回溯：L4/L5 -> L1-L3
  kb verify <id> --script verify/<id>.py            # 只有脚本能把它变成 verified
  kb stale                                          # 淘汰：过期的 verified 降级
  kb digest                                         # 生成 digest/latest.md
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kb", description="ashare-kb：存断言，不存理解。",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", help="库根目录（默认 ashare-kb/ 或 $ASHARE_KB_ROOT）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="建库/建目录；库为空时自动重放账本")
    s.set_defaults(func=c.cmd_init)

    s = sub.add_parser("lead", help="记一条线索（status 恒为 lead）")
    s.add_argument("statement", help="一句话，必须可证伪")
    s.add_argument("--layer", required=True, choices=["institutional", "structural"],
                   help="没有 state 层 —— 当下状态不进库")
    s.add_argument("--tier", required=True, type=int, choices=[1, 2, 3, 4, 5])
    s.add_argument("--src", required=True, help="URL 或 sources/ 下的文件")
    s.add_argument("--if-wrong", required=True, dest="if_wrong",
                   help="什么观测推翻它。写不出来就说明这不是断言")
    s.add_argument("--stale-after", dest="stale_after",
                   help="衰减天数，或 never。默认 structural=90 / institutional=never")
    s.add_argument("--verify-script", dest="verify_script", help="verify/ 下的脚本（可后补）")
    s.add_argument("--note")
    s.set_defaults(func=c.cmd_lead)

    s = sub.add_parser("source", help="回溯来源（L4/L5 -> L1-L3）。整套系统最重要的动作")
    s.add_argument("claim_id")
    s.add_argument("--tier", type=int, choices=[1, 2, 3, 4, 5])
    s.add_argument("--src")
    s.add_argument("--note")
    s.set_defaults(func=c.cmd_source)

    s = sub.add_parser("verify", help="跑验证脚本，按退出码改状态")
    s.add_argument("claim_id")
    s.add_argument("--script", help="verify/ 下的脚本；给了就绑定到这条断言")
    s.add_argument("--note", help="若脚本判定 falsified，作为打脸理由记入墓碑")
    s.set_defaults(func=c.cmd_verify)

    s = sub.add_parser("falsify", help="手动打脸（制度变了、发现自相矛盾）")
    s.add_argument("claim_id")
    s.add_argument("--why", required=True, help="为什么错了")
    s.add_argument("--evidence")
    s.set_defaults(func=c.cmd_falsify)

    s = sub.add_parser("stale", help="过期的 verified 降级为 stale")
    s.add_argument("--dry-run", action="store_true", help="只列出，不写库")
    s.set_defaults(func=c.cmd_stale)

    s = sub.add_parser("digest", help="生成 digest/latest.md")
    s.set_defaults(func=c.cmd_digest)

    s = sub.add_parser("list", help="列出断言")
    s.add_argument("--status", choices=["lead", "verified", "falsified", "stale"])
    s.add_argument("--layer", choices=["institutional", "structural"])
    s.add_argument("--tier", type=int, choices=[1, 2, 3, 4, 5])
    s.set_defaults(func=c.cmd_list)

    s = sub.add_parser("show", help="看一条断言 + 它的账本历史")
    s.add_argument("claim_id")
    s.set_defaults(func=c.cmd_show)

    s = sub.add_parser("rebuild", help="从 ledger/events.jsonl 重建 kb.sqlite")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=c.cmd_rebuild)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KBError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
