"""交易日志与事前承诺。

这个模块处理的不是市场，是你自己。

行为金融学里最稳的发现之一：人会在事后重构自己的决策理由
（"我早就知道会跌"）。这让复盘变成自我安慰，而不是纠错。
唯一的解药是"事前承诺"——在下单之前，先写下：
  1. 我为什么买（可证伪的理由，不是"感觉会涨"）
  2. 什么情况证明我错了（预先定义的失效条件）
  3. 我打算持有多久
  4. 这笔交易是不是系统信号（还是我手痒）

然后复盘时，拿实际结果对照当初写下的东西。
系统外交易的表现会告诉你，你的"盘感"到底值多少钱 —— 通常是负的。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd


@dataclass
class TradeIntent:
    """下单前必须填写的事前承诺。字段少但每个都必填。"""

    date: str
    code: str
    side: str                     # buy / sell
    size_pct: float               # 占总资产比例
    source: str                   # system | discretionary  —— 这个字段最值钱
    thesis: str                   # 为什么买/卖，必须可证伪
    invalidation: str             # 什么情况说明我错了
    expected_holding_days: int
    conviction: int = 3           # 1-5
    emotion: str = "calm"         # calm | fomo | fear | revenge | bored
    notes: str = ""

    def validate(self) -> list[str]:
        errs = []
        if self.source not in ("system", "discretionary"):
            errs.append("source 必须是 system 或 discretionary")
        if len(self.thesis.strip()) < 10:
            errs.append("thesis 太短 —— 说不清理由的交易不该做")
        if len(self.invalidation.strip()) < 5:
            errs.append("必须写明失效条件：什么情况证明你错了")
        if not 0 < self.size_pct <= 1:
            errs.append("size_pct 应在 (0, 1]")
        if self.emotion in ("fomo", "revenge"):
            errs.append(f"情绪状态为 {self.emotion} —— 建议 24 小时后再决定")
        return errs


class Journal:
    """交易日志。落地为 JSONL，方便追加和事后分析。"""

    def __init__(self, path: str | Path = "./journal.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, intent: TradeIntent, strict: bool = True) -> list[str]:
        errs = intent.validate()
        if errs and strict:
            return errs
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**asdict(intent), "logged_at": datetime.now().isoformat()},
                               ensure_ascii=False) + "\n")
        return errs

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()
        rows = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def outcome_analysis(self, trades: pd.DataFrame, bars: pd.DataFrame,
                         horizon: int = 20) -> pd.DataFrame:
        """把事前承诺和实际结果对上账。

        最重要的一行输出：system vs discretionary 的收益对比。
        绝大多数人会发现自己的临时起意在系统性地亏钱 ——
        看到数字比听到道理有用得多。
        """
        j = self.load()
        if j.empty:
            return pd.DataFrame()
        px = bars["close"].unstack("code")
        fwd = (px.shift(-horizon) / px - 1)

        rows = []
        for _, r in j.iterrows():
            try:
                ret = float(fwd.loc[r["date"], r["code"]])
            except (KeyError, ValueError):
                continue
            if pd.isna(ret):
                continue
            rows.append({**r.to_dict(), f"fwd_{horizon}d": ret})
        out = pd.DataFrame(rows)
        return out


def summarize_by_source(outcomes: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """按来源（系统信号 vs 主观决策）和情绪状态汇总表现。"""
    if outcomes.empty:
        return pd.DataFrame()
    col = f"fwd_{horizon}d"
    g = outcomes.groupby("source")[col]
    by_source = pd.DataFrame({
        "笔数": g.size(), "平均收益": g.mean(), "胜率": g.apply(lambda x: (x > 0).mean()),
        "最差": g.min(),
    })
    return by_source.round(4)
