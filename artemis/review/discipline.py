"""纪律评分。

一个不受欢迎但正确的观点：对绝大多数散户来说，
执行纪律的边际收益远高于改进策略的边际收益。

你不需要更好的因子。你需要的是：
  - 不在系统没发信号的时候手痒下单
  - 不在止损位到了的时候找理由不止损
  - 不在连亏三天之后加倍下注
  - 不在别人都在赚钱的时候突然改参数

这个模块给这些行为打分。分数低不代表你笨，代表你是人。
但你至少能看见它。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


RULES = {
    "遵守系统信号": "系统外的主观交易占比 <= 10%",
    "止损执行率": "触发止损后按时执行的比例 >= 90%",
    "仓位纪律": "实际仓位与目标仓位偏离 <= 10%",
    "调仓频率": "实际换手不超过计划换手的 1.3 倍",
    "情绪控制": "标记为 fomo/revenge 的交易占比 <= 5%",
    "记录完整性": "有事前承诺记录的交易占比 >= 95%",
}


def score(journal_df: pd.DataFrame, trades: pd.DataFrame,
          daily: pd.DataFrame, planned_turnover: float = 3.0) -> pd.DataFrame:
    """输出各项纪律得分（0~100）与总分。"""
    rows = []

    # 1) 系统外交易占比
    if not journal_df.empty and "source" in journal_df:
        disc = float((journal_df["source"] == "discretionary").mean())
        rows.append(("遵守系统信号", max(0, 100 * (1 - disc / 0.10)) if disc <= 0.10 else max(0, 100 - (disc - 0.10) * 500),
                     f"主观交易占比 {disc:.1%}"))
    else:
        rows.append(("遵守系统信号", np.nan, "无日志记录"))

    # 2) 情绪控制
    if not journal_df.empty and "emotion" in journal_df:
        bad = float(journal_df["emotion"].isin(["fomo", "revenge"]).mean())
        rows.append(("情绪控制", max(0, 100 - bad * 1000), f"冲动交易占比 {bad:.1%}"))
    else:
        rows.append(("情绪控制", np.nan, "无日志记录"))

    # 3) 记录完整性
    n_journal = len(journal_df) if journal_df is not None else 0
    n_buy = int((trades["side"] == "buy").sum()) if trades is not None and not trades.empty else 0
    if n_buy > 0:
        cov = min(1.0, n_journal / n_buy)
        rows.append(("记录完整性", cov * 100, f"{n_journal}/{n_buy} 笔有事前记录"))
    else:
        rows.append(("记录完整性", np.nan, "无交易"))

    # 4) 调仓频率
    if trades is not None and not trades.empty and daily is not None and not daily.empty:
        eq = daily["equity"]
        years = len(eq) / 252
        turn = trades["amount"].sum() / 2 / eq.mean() / max(years, 1e-9)
        ratio = turn / planned_turnover if planned_turnover > 0 else np.nan
        rows.append(("调仓频率", float(np.clip(100 * (1.3 / max(ratio, 1e-9)), 0, 100)) if ratio > 1.3 else 100.0,
                     f"实际年换手 {turn:.1f}x / 计划 {planned_turnover:.1f}x"))

    # 5) 仓位纪律
    if daily is not None and "position_pct" in daily:
        halted = float(daily["halted"].mean()) if "halted" in daily else 0.0
        rows.append(("仓位纪律", 100.0 * (1 - halted),
                     f"熔断状态天数占比 {halted:.1%}"))

    df = pd.DataFrame(rows, columns=["纪律项", "得分", "说明"])
    valid = df["得分"].dropna()
    total = float(valid.mean()) if len(valid) else np.nan
    df.loc[len(df)] = ["—— 总分", total, "低于 80 分说明执行是你的主要漏洞，不是策略"]
    df["得分"] = df["得分"].map(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
    return df


def behavioral_flags(equity: pd.Series, trades: pd.DataFrame) -> list[str]:
    """检测典型的行为陷阱，直接给出警告。"""
    flags = []
    if equity is None or len(equity) < 20:
        return flags
    ret = equity.pct_change().fillna(0)

    # 报复性交易：连续亏损后交易量激增
    if trades is not None and not trades.empty:
        daily_amt = trades.groupby("date")["amount"].sum()
        daily_amt = daily_amt.reindex(equity.index).fillna(0)
        losing_streak = (ret < 0).rolling(3).sum() >= 3
        if losing_streak.any():
            # 必须显式 astype(bool)：shift+fillna 会把 bool 序列变成 object dtype，
            # 此时 ~ 执行的是按位取反（得到 -1/-2）而不是逻辑取反，
            # 结果会被 pandas 当成标签索引，静默索引到错误的行或直接报错。
            prev_streak = losing_streak.shift(1).fillna(False).astype(bool)
            after_loss = daily_amt[prev_streak]
            normal = daily_amt[~prev_streak]
            if len(after_loss) > 5 and normal.mean() > 0 and after_loss.mean() > normal.mean() * 1.5:
                flags.append(
                    f"⚠ 报复性交易：连亏 3 日后的成交额是平时的 {after_loss.mean()/normal.mean():.1f} 倍"
                )

    # 回撤中加仓
    dd = equity / equity.cummax() - 1
    if trades is not None and not trades.empty:
        buys = trades[trades.side == "buy"].groupby("date")["amount"].sum().reindex(equity.index).fillna(0)
        deep = (dd < -0.10).astype(bool)
        if deep.sum() > 10 and deep.sum() < len(deep) and \
                buys[deep].mean() > buys[~deep].mean() * 1.3:
            flags.append("⚠ 深度回撤中仍在加仓 —— 检查是否在'摊平成本'")

    # 换手漂移：后半段换手显著高于前半段
    if trades is not None and not trades.empty:
        mid = equity.index[len(equity) // 2]
        early = trades[trades.date < mid]["amount"].sum()
        late = trades[trades.date >= mid]["amount"].sum()
        if early > 0 and late > early * 1.6:
            flags.append(f"⚠ 换手漂移：后半段交易额是前半段的 {late/early:.1f} 倍，可能在过度干预系统")

    return flags
