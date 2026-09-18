#!/usr/bin/env python3
"""种子断言 —— 从设计这个库的那轮对话里提取。

**全部以 lead 入库，一条 verified 都没有。**

设计稿里把三条制度层断言标成了 "institutional / verified（L1可查原文）"。
这里没有照办，理由是：那三条在本次会话里没有被任何东西验证过 ——
没有人把法规原文存进 sources/，没有脚本跑过。把它们直接写成 verified，
等于在第一天就造出这个库专门要防的东西：一条谁也说不清凭什么为真的记录。

这个种子集本身就是一堂课：它标出了那轮对话给出的东西里
哪些是硬的、哪些是软的，以及"硬"到今天为止仍然只是**声称**硬。

跑法：
    ./kb init && python3 seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kb_cli.__main__ import main  # noqa: E402

SEEDS = [
    # ---- 制度层 / 声称 L1，待存档原文后验证 ----------------------------------
    dict(
        statement="T+1 限制个人投资者当日卖出当日买入的股票，"
                  "但机构可通过底仓+融券实现变相日内回转",
        layer="institutional", tier=1,
        src="待存档：上交所/深交所《交易规则》日内回转与融券相关条款 → sources/",
        if_wrong="交易所规则原文显示融券门槛与散户对等，"
                 "或显示机构无法通过底仓+融券实现日内回转",
    ),
    dict(
        statement="科创板个人投资者交易权限门槛为申请权限前20个交易日"
                  "日均资产不低于人民币50万元，且参与证券交易满24个月",
        layer="institutional", tier=1,
        src="待存档：上交所《科创板股票交易特别规定》/投资者适当性管理办法 → sources/",
        if_wrong="规则原文显示该门槛已取消、下调，或资产/年限口径与此不符",
    ),
    dict(
        statement="新“国九条”于2024年4月12日由国务院印发，"
                  "并以此为纲形成“1+N”政策体系",
        layer="institutional", tier=1,
        src="待存档：国务院《关于加强监管防范风险推动资本市场高质量发展的若干意见》→ sources/",
        if_wrong="找不到国务院原文，或原文的印发日期、文号、"
                 "“1+N”表述与此不符",
    ),

    # ---- 制度层 / L4，必须回溯 ----------------------------------------------
    dict(
        statement="新“国九条”实施两年间A股分红与回购合计超过5万亿元，"
                  "同期IPO融资约两千亿元",
        layer="institutional", tier=4,
        src="新华网报道（L4）—— 需回溯证监会公告或Wind原始统计",
        if_wrong="证监会/交易所/Wind 的原始统计在同一口径下与此量级不符",
    ),
    dict(
        statement="截至2025年末，中长期资金持有A股流通市值约23万亿元",
        layer="institutional", tier=4,
        src="转述证监会数据（L4）—— 需找到证监会原文及其口径",
        if_wrong="证监会原文披露的口径或数值与此不符，"
                 "或“中长期资金”的统计范围与转述不同",
    ),

    # ---- 结构层 / 可自验 ----------------------------------------------------
    dict(
        statement="A股个股涨跌幅中位数长期低于市值加权指数收益",
        layer="structural", tier=2,
        src="自算（Wind/Choice 全A日行情 + 沪深300/中证全指收益）",
        if_wrong="连续4个季度个股涨跌幅中位数 ≥ 同期市值加权指数收益",
        # 这是一条"长期"结论，必须定期重算 —— 走默认 90 天衰减
    ),
    dict(
        statement="2026年上半年5528只A股中仅1695只上涨，区间涨跌幅中位数为-14.99%",
        layer="structural", tier=4,
        src="Wind 数据转述（L4）—— 自己拉一遍全A行情即可升到 L2",
        if_wrong="按同口径（剔除区间内新上市、含ST、前复权）自算的结果"
                 "与此偏离超过1个百分点",
        stale_after="never",  # 已封闭的历史区间测算，不会腐烂
    ),

    # ---- 结构层 / L5，大概率永远无法 verified --------------------------------
    dict(
        statement="2026年上半年A股散户亏损账户占比79%-82%，人均浮亏约2.1万元",
        layer="structural", tier=5,
        src="自媒体转述（L5）—— 找不到中证协原始报告",
        if_wrong="中证协或交易所原始统计给出的区间与此不符。"
                 "注：同一批转述内部就自相矛盾 —— 百万元以上账户"
                 "一说亏损85-90%、一说盈利超90%，两者不可能同时为真",
        stale_after="never",
    ),
    dict(
        statement="2026年1月1日至5月27日期间，A股普跌天数28天，同期美股4天",
        layer="structural", tier=5,
        src="自媒体研报（L5）—— 口径不明",
        if_wrong="按明确定义的口径（“普跌”的判定阈值、指数与样本范围、"
                 "交易日对齐方式）重算的结果与此不符",
        stale_after="never",
    ),
    dict(
        statement="个人投资者贡献A股60%-70%的成交量",
        layer="structural", tier=5,
        src="转述（L5）—— 需上交所统计年鉴/交易所原始统计",
        if_wrong="交易所年鉴的原始口径数值落在该区间外，"
                 "或该口径统计的是账户数、持股市值而非成交量",
    ),
]


def build_argv(seed: dict) -> list[str]:
    argv = [
        "lead", seed["statement"],
        "--layer", seed["layer"],
        "--tier", str(seed["tier"]),
        "--src", seed["src"],
        "--if-wrong", seed["if_wrong"],
    ]
    if "stale_after" in seed:
        argv += ["--stale-after", str(seed["stale_after"])]
    return argv


def run() -> int:
    failed = 0
    for seed in SEEDS:
        rc = main(build_argv(seed))
        print()
        failed += rc != 0
    print(f"种子集：{len(SEEDS)} 条，失败 {failed} 条。verified 0 条 —— 这是对的。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
