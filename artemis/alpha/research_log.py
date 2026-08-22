"""因子研究日志。

为什么这个模块必须存在：

反过拟合的核心变量是"你到底试过多少次"。收缩夏普 (DSR)、FDR 校正、
Harvey-Liu-Zhu 的 t 值门槛 —— 全都需要这个数字。而人是记不住的，
更关键的是人**不愿意**记住：调参调了三天，最后只记得成功那一次。

所以它必须自动记录。每评估一个因子就写一行，不管结果好坏，
不管你是不是打算用它。研究日志是唯一能让"我试了多少次"变成
可审计事实的东西。

日志落地为 JSONL，方便追加、方便 diff、方便你三个月后回头看
自己当初为什么放弃了某个因子。
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Trial:
    """一次因子评估的完整记录。"""

    factor_name: str
    hypothesis: str                  # 经济逻辑，必填
    formula: str                     # 计算方式的文字描述
    universe: str                    # 股票池定义
    period: str                      # 评估区间
    horizon: int

    ic_mean: float
    icir: float
    t_stat: float
    monotonicity: float
    ls_ann: float
    autocorr: float
    n_days: int

    # 增量价值：对已有因子库正交化后剩下多少
    resid_icir: float | None = None
    retention: float | None = None      # resid_icir / raw_icir，判定冗余的核心字段
    max_corr_existing: float | None = None
    corr_with: str | None = None

    source: str = "manual"           # manual | llm | grid
    parent: str | None = None        # 派生自哪个因子（用于识别"同一想法的第 N 个变体"）
    decision: str = "pending"        # pending | rejected | shortlist | deployed
    reject_reason: str | None = None
    tags: list[str] = field(default_factory=list)
    logged_at: str = ""

    def fingerprint(self) -> str:
        """指纹：用于识别"换个名字重测同一个因子"。"""
        raw = f"{self.formula}|{self.universe}|{self.horizon}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


class ResearchLog:
    def __init__(self, path: str | Path = "./research_log.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, trial: Trial) -> str:
        trial.logged_at = datetime.now().isoformat(timespec="seconds")
        fp = trial.fingerprint()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**asdict(trial), "fingerprint": fp}, ensure_ascii=False) + "\n")
        return fp

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()
        rows = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return pd.DataFrame(rows)

    # ----------------------------------------------------------------
    def trial_count(self, effective: bool = True) -> int:
        """试验次数。

        effective=True 时按指纹去重 —— 同一个因子重测多次只算一次，
        因为多重检验的惩罚针对的是"你搜索了多大的空间"，
        不是"你按了多少次运行"。
        """
        df = self.load()
        if df.empty:
            return 0
        return int(df["fingerprint"].nunique()) if effective else len(df)

    def sharpe_like_stats(self) -> np.ndarray:
        """取出所有试验的 ICIR，供 DSR 估计 sigma_SR 用。"""
        df = self.load()
        if df.empty or "icir" not in df:
            return np.array([])
        return df.drop_duplicates("fingerprint")["icir"].dropna().values

    def summary(self) -> pd.DataFrame:
        df = self.load()
        if df.empty:
            return pd.DataFrame()
        d = df.drop_duplicates("fingerprint", keep="last")
        return pd.DataFrame([{
            "总试验数(去重)": len(d),
            "总记录数": len(df),
            "已否决": int((d.decision == "rejected").sum()),
            "候选": int((d.decision == "shortlist").sum()),
            "已上线": int((d.decision == "deployed").sum()),
            "ICIR中位数": round(float(d.icir.median()), 3),
            "ICIR标准差": round(float(d.icir.std()), 3),
            "最高ICIR": round(float(d.icir.max()), 3),
        }])

    def by_source(self) -> pd.DataFrame:
        """按来源统计。用来回答"LLM 提的假设命中率到底比我自己拍脑袋高吗"。"""
        df = self.load()
        if df.empty:
            return pd.DataFrame()
        d = df.drop_duplicates("fingerprint", keep="last")
        g = d.groupby("source")
        return pd.DataFrame({
            "试验数": g.size(),
            "ICIR均值": g["icir"].mean().round(3),
            "|ICIR|>1 占比": g["icir"].apply(lambda x: (x.abs() > 1).mean()).round(3),
            "进入候选": g["decision"].apply(lambda x: (x == "shortlist").sum()),
        })

    def duplicates(self) -> pd.DataFrame:
        """找出被重复测试的因子 —— 这通常意味着你在原地打转。"""
        df = self.load()
        if df.empty:
            return pd.DataFrame()
        c = df.groupby("fingerprint").agg(
            次数=("factor_name", "size"),
            用过的名字=("factor_name", lambda x: " / ".join(sorted(set(x)))),
        )
        return c[c["次数"] > 1].sort_values("次数", ascending=False)
