#!/usr/bin/env python3
"""inst-625f832d —— 科创板个人投资者交易权限门槛。

STATEMENT: 科创板个人投资者交易权限门槛为申请权限前20个交易日日均资产
           不低于人民币50万元，且参与证券交易满24个月
IF_WRONG:  规则原文显示该门槛已取消、下调，或资产/年限口径与此不符

快照怎么取：
  上交所规则库 →《上海证券交易所科创板股票交易特别规定》
  或《上海证券交易所科创板投资者适当性管理办法》，取含适当性条款那一节的全文，
  存成 sources/sse-kechuangban-shidangxing.txt

  kb source inst-625f832d --src sources/sse-kechuangban-shidangxing.txt
  kb verify inst-625f832d

断言有三个数字成分（20个交易日 / 50万元 / 24个月），三个都必须在原文里找到。
只核对其中两个，脚本就比断言宽松 —— 那时它说 HOLDS，
实际支持的是一条比库里记的更弱的断言。
"""

import kbverify as kv

SNAPSHOT = "sse-kechuangban-shidangxing.txt"

PHRASES = (
    ("20个交易日", "二十个交易日"),
    ("50万元", "五十万元", "500,000元", "500000元"),
    ("24个月", "二十四个月", "2年", "两年"),
)

if __name__ == "__main__":
    kv.require_phrases(SNAPSHOT, *PHRASES)
