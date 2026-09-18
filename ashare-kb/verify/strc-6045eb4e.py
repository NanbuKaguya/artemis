#!/usr/bin/env python3
"""strc-6045eb4e —— L2 形态：自己算一遍。

STATEMENT: A股个股涨跌幅中位数长期低于市值加权指数收益
IF_WRONG:  连续4个季度个股涨跌幅中位数 ≥ 同期市值加权指数收益

数据源是 akshare（没有 Wind）。口径钉在 verify/ashare_data.py 的模块文档里，
改口径就是改断言，两边必须一起改。

第一次跑要一到两小时（全A逐只历史 5000+ 次请求），之后走 .cache/ 是秒级。
"""

import datetime as _dt

import ashare_data as ad
import kbverify as kv

QUARTERS = 4


def main() -> None:
    quarters = ad.last_complete_quarters(QUARTERS, _dt.date.today())
    print(f"比较区间: {', '.join(q[0] for q in quarters)}")

    try:
        symbols = ad.universe()
    except Exception as exc:  # 取数失败不是证据
        kv.inconclusive(f"拉取全A代码表失败: {type(exc).__name__}: {exc}")
    print(f"全A {len(symbols)} 只")

    rows = []
    for label, start, end in quarters:
        try:
            returns = ad.stock_returns(symbols, start, end, progress=500)
            idx = ad.index_return(ad.INDEX_ALL_SHARE, start, end)
        except Exception as exc:
            kv.inconclusive(f"{label} 取数失败: {type(exc).__name__}: {exc}")
        med = ad.median(returns)
        if med is None or idx is None:
            kv.inconclusive(f"{label} 样本为空（入样 {len(returns)} 只，指数 {idx}）")
        rows.append((label, med, idx))
        print(f"  {label}: 中位数 {med:+.2%} vs 中证全指 {idx:+.2%}  （入样 {len(returns)} 只）")

    detail = "; ".join(f"{q} {m:+.2%} vs {i:+.2%}" for q, m, i in rows)
    breaches = [r for r in rows if r[1] >= r[2]]

    # if_wrong 要的是"连续4个季度"，不是"某个季度"。
    # 单季反例不足以推翻一条"长期"断言 —— 那正是当初写下这个 if_wrong 的原因。
    if len(breaches) == QUARTERS:
        kv.falsified(f"连续 {QUARTERS} 个季度中位数 ≥ 指数: {detail}")
    kv.holds(f"{QUARTERS} 个季度中 {QUARTERS - len(breaches)} 个季度中位数 < 指数: {detail}")


if __name__ == "__main__":
    main()
