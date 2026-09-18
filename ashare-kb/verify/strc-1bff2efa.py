#!/usr/bin/env python3
"""strc-1bff2efa —— 把一条 Wind 转述自己算一遍。

STATEMENT: 2026年上半年5528只A股中仅1695只上涨，区间涨跌幅中位数为-14.99%
IF_WRONG:  按同口径（剔除区间内新上市、含ST、前复权）自算的结果与此偏离超过1个百分点

这条现在是 L4（Wind 数据转述）。**跑这个脚本之前得先回溯来源**，
否则质量门会拦下它 —— 自己算过了，来源就是你自己的计算，不再是转述：

    ./kb source strc-1bff2efa --tier 2 --src "akshare 自算，见 verify/strc-1bff2efa.py"
    ./kb verify strc-1bff2efa --script verify/strc-1bff2efa.py

区间已封闭，所以缓存一次之后永远是秒级，也不会衰减（--stale-after never）。
"""

import ashare_data as ad
import kbverify as kv

START, END = "20260101", "20260630"

CLAIMED_MEDIAN = -0.1499
CLAIMED_UP = 1695
CLAIMED_TOTAL = 5528
TOLERANCE = 0.01  # if_wrong 说的"1个百分点"


def main() -> None:
    try:
        symbols = ad.universe()
        returns = ad.stock_returns(symbols, START, END, progress=500)
    except Exception as exc:
        kv.inconclusive(f"取数失败: {type(exc).__name__}: {exc}")

    med = ad.median(returns)
    if med is None:
        kv.inconclusive("样本为空")
    up, total = ad.breadth(returns)

    print(f"自算: {total} 只入样，{up} 只上涨，中位数 {med:+.2%}")
    print(f"转述: {CLAIMED_TOTAL} 只，{CLAIMED_UP} 只上涨，中位数 {CLAIMED_MEDIAN:+.2%}")

    # 只数只报不判 —— 当初记下的 if_wrong 只约束了中位数。
    # 想让只数也具有约束力，就去改断言的 if_wrong，别在这里偷偷加判定条件：
    # 脚本比断言严，等于断言的实际内容和库里写的不是同一条。
    if abs(up - CLAIMED_UP) > 50 or abs(total - CLAIMED_TOTAL) > 50:
        print(f"注意: 只数与转述差得不小（上涨 {up - CLAIMED_UP:+d}，"
              f"总数 {total - CLAIMED_TOTAL:+d}），但 if_wrong 只约束中位数。")

    gap = abs(med - CLAIMED_MEDIAN)
    if gap > TOLERANCE:
        kv.falsified(f"中位数自算 {med:+.2%}，转述 {CLAIMED_MEDIAN:+.2%}，"
                     f"相差 {gap:.2%} > {TOLERANCE:.0%}")
    kv.holds(f"中位数自算 {med:+.2%}，与转述 {CLAIMED_MEDIAN:+.2%} 相差 {gap:.2%}，"
             f"在 {TOLERANCE:.0%} 容差内（{total} 只入样，{up} 只上涨）")


if __name__ == "__main__":
    main()
