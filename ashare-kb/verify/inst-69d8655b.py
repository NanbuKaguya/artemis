#!/usr/bin/env python3
"""inst-69d8655b —— L1 形态的样板：核对原文快照。

STATEMENT: 新“国九条”于2024年4月12日由国务院印发，并以此为纲形成“1+N”政策体系
IF_WRONG:  找不到国务院原文，或原文的印发日期、文号、“1+N”表述与此不符

没有快照时退 2（不确定），因为这条断言目前**不该**是 verified。

要让它变成 verified：
  1. 从 www.gov.cn 取《关于加强监管防范风险推动资本市场高质量发展的若干意见》
     全文，存成 sources/gov-2024-04-12-guojiutiao.txt（存全文，不存摘要）
  2. kb source inst-69d8655b --src sources/gov-2024-04-12-guojiutiao.txt
  3. kb verify inst-69d8655b
"""

import kbverify as kv

SNAPSHOT = "gov-2024-04-12-guojiutiao.txt"

# 这几组短语同时命中，才算原文支持了这条断言的每一个成分。
# 少写一组，验证就比断言宽松，库就开始撒谎。
#
# tuple = 候选组，任一命中即可 —— 同一个事实的不同写法不该算验证失败。
# 日期尤其如此：正文用阿拉伯数字，落款常用中文数字，PDF 和网页版还不一致。
PHRASES = (
    "关于加强监管防范风险推动资本市场高质量发展的若干意见",
    kv.date_variants(2024, 4, 12),
    ("1+N", "1＋N", "“1+N”"),
)

if __name__ == "__main__":
    kv.require_phrases(SNAPSHOT, *PHRASES)
