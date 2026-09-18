#!/usr/bin/env python3
"""inst-69d8655b —— L1 形态的样板：核对原文快照。

STATEMENT: 新“国九条”于2024年4月12日由国务院印发，并以此为纲形成“1+N”政策体系
IF_WRONG:  找不到国务院原文，或原文的印发日期、文号、“1+N”表述与此不符

今天跑它会退 2（不确定），因为 sources/ 下还没有原文快照。
这是正确行为，不是 bug：**这条断言目前不该是 verified。**

要让它变成 verified：
  1. 从 www.gov.cn 取《关于加强监管防范风险推动资本市场高质量发展的若干意见》
     全文，存成 sources/gov-2024-04-12-guojiutiao.txt
  2. kb source inst-69d8655b --src sources/gov-2024-04-12-guojiutiao.txt
  3. kb verify inst-69d8655b --script verify/inst-69d8655b.py
"""

import kbverify as kv

SNAPSHOT = "gov-2024-04-12-guojiutiao.txt"

# 这几条短语同时出现，才算原文支持了这条断言的每一个成分。
# 少写一条，验证就比断言宽松，库就开始撒谎。
PHRASES = (
    "关于加强监管防范风险推动资本市场高质量发展的若干意见",
    "2024年4月12日",
)

if __name__ == "__main__":
    kv.require_phrases(SNAPSHOT, *PHRASES)
