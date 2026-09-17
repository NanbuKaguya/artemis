#!/usr/bin/env python3
"""strc-6045eb4e —— L2 形态的样板：自己算一遍。

STATEMENT: A股个股涨跌幅中位数长期低于市值加权指数收益
IF_WRONG:  连续4个季度个股涨跌幅中位数 ≥ 同期市值加权指数收益

今天跑它会退 2（不确定），因为行情数据源还没接上。
**不要**为了让它跑通而放宽判定 —— 接不上数据就退 2，这是契约。

接数据时要钉死的口径（口径不定，这条断言不可证伪）：
  - 样本：区间首日已上市且未退市的全部 A 股；剔除区间内新上市
  - 价格：前复权
  - 指数：中证全指（市值加权，与"个股中位数"可比）
  - 窗口：最近 4 个完整自然季度，逐季比较
"""

import kbverify as kv

QUARTERS = 4


def load_quarterly_returns():
    """返回 [(季度标签, 个股涨跌幅中位数, 指数收益), ...]。

    接 Wind/Choice/本地行情库时实现这个函数。
    """
    return None


if __name__ == "__main__":
    data = load_quarterly_returns()
    if not data:
        kv.inconclusive("行情数据源未接入 —— 实现 load_quarterly_returns() 后再验证")
    if len(data) < QUARTERS:
        kv.inconclusive(f"只拿到 {len(data)} 个季度，需要 {QUARTERS} 个")

    breaches = [(q, m, i) for q, m, i in data if m >= i]
    if len(breaches) == QUARTERS:
        kv.falsified(
            f"连续 {QUARTERS} 个季度中位数 ≥ 指数: "
            + "; ".join(f"{q} {m:.2%} vs {i:.2%}" for q, m, i in breaches)
        )
    kv.holds(
        f"{QUARTERS} 个季度中 {QUARTERS - len(breaches)} 个季度中位数 < 指数: "
        + "; ".join(f"{q} {m:.2%} vs {i:.2%}" for q, m, i in data)
    )
