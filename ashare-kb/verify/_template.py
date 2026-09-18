#!/usr/bin/env python3
"""验证脚本模板 —— 复制成 verify/<claim_id>.py 再改。

一条断言一个脚本。脚本的职责是回答一个问题：
「今天，用可复核的证据，这条断言还成立吗？」
"""

import kbverify as kv

# 1) 把断言原样抄在这里，改断言时脚本必须跟着改。
STATEMENT = "……"

# 2) 把 if_wrong 也抄在这里。脚本要检验的正是这一条。
IF_WRONG = "……"


def main() -> None:
    # 结论必须由 kv.holds() / kv.falsified() / kv.inconclusive() 显式声明 ——
    # 光 sys.exit(0) 不会让断言变成 verified（见 verify/README.md 的退出码契约）。
    # L1/L3 形态：核对 sources/ 下的原文快照
    #   kv.require_phrases("cnsc-2024-guojiutiao.txt", "1+N", "2024年4月12日")

    # L2 形态：自己算一遍
    #   median, index_ret = compute(...)
    #   if median >= index_ret:
    #       kv.falsified(f"中位数 {median:.2%} >= 指数 {index_ret:.2%}")
    #   kv.holds(f"中位数 {median:.2%} < 指数 {index_ret:.2%}")

    kv.inconclusive("模板未实现")


if __name__ == "__main__":
    main()
