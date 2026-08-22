"""因子挖掘流水线。

挖掘的本质是**大规模多重检验**，这一点几乎所有散户量化都没意识到。

你测 500 个因子，用 p<0.05 筛选，即使所有因子真实无效，也会有约 25 个
"显著"。你挑出它们，做成组合，回测漂亮，上实盘归零。这不是运气不好，
这是统计学的必然。

本模块提供三道针对挖掘场景的专门防线：

1. **增量价值检验** —— 新因子对已有因子库正交化后还剩多少 IC。
   剩不下的，无论单独看多漂亮都是冗余。冗余因子的危害不只是浪费
   一个仓位，它会让你误以为组合分散，实际是同一个赌注下了三遍。

2. **FDR 控制（Benjamini-Hochberg）** —— 不控制单个因子的 p 值，
   控制"入选的那批因子里假阳性的比例"。这才是挖掘场景该问的问题。

3. **Harvey-Liu-Zhu 门槛** —— 学术界已发表 300+ 因子，考虑到发表偏差
   和数据挖掘，新因子的 t 值门槛应该是 3.0 而不是 2.0。散户的搜索
   空间不比学术界小，门槛只该更高。

配套的 research_log.py 自动记录每次试验，因为上面三道防线全都依赖
"你到底试过多少次"这个数字，而人是记不住也不愿意记住的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
import pandas as pd
from scipy import stats

from . import factors as F
from .evaluate import evaluate_factor, forward_returns
from .research_log import ResearchLog, Trial


# --------------------------------------------------------------------------
# 1. 增量价值：对已有因子库正交化
# --------------------------------------------------------------------------
def orthogonalize(
    new: pd.Series, existing: pd.DataFrame, min_obs: int = 30
) -> pd.Series:
    """把新因子对已有因子做逐日截面回归，返回残差。

    残差 = 新因子中"已有因子解释不了"的部分。这才是它真正贡献的信息。
    """
    df = pd.concat([new.rename("__y"), existing], axis=1)

    def _resid(block: pd.DataFrame) -> pd.Series:
        b = block.dropna()
        if len(b) < min_obs or b.shape[1] < 2:
            return pd.Series(np.nan, index=block.index)
        y = b["__y"].values
        X = np.column_stack([np.ones(len(b)), b.drop(columns="__y").values])
        try:
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            return pd.Series(np.nan, index=block.index)
        return pd.Series(y - X @ coef, index=b.index).reindex(block.index)

    return df.groupby(level="date", group_keys=False).apply(_resid)


def incremental_value(
    new: pd.Series,
    existing: pd.DataFrame,
    bars: pd.DataFrame,
    mask: pd.Series | None = None,
    horizon: int = 5,
) -> dict:
    """新因子相对已有因子库的增量价值。

    返回：
      raw_icir       新因子自己的 ICIR
      resid_icir     正交化后残差的 ICIR ← 这才是它值不值一个仓位的依据
      retention      resid_icir / raw_icir，保留率。低于 0.5 说明大半是冗余
      max_corr       与已有因子的最大截面相关
      corr_with      相关性最高的那个因子
    """
    if existing is None or existing.empty:
        rep = evaluate_factor(new, bars, mask=mask, horizon=horizon, quick=True)
        return {"raw_icir": rep.stats["icir"], "resid_icir": rep.stats["icir"],
                "retention": 1.0, "max_corr": 0.0, "corr_with": None}

    raw = evaluate_factor(new, bars, mask=mask, horizon=horizon, quick=True).stats["icir"]
    resid = orthogonalize(new, existing)
    try:
        res_icir = evaluate_factor(resid, bars, mask=mask, horizon=horizon, quick=True).stats["icir"]
    except ValueError:
        res_icir = 0.0

    # 逐日截面相关的均值
    corrs = {}
    for c in existing.columns:
        pair = pd.DataFrame({"a": new, "b": existing[c]}).dropna()
        if pair.empty:
            continue
        daily = pair.groupby(level="date").apply(
            lambda g: g["a"].corr(g["b"], method="spearman") if len(g) >= 20 else np.nan)
        corrs[c] = float(daily.mean())
    if corrs:
        top = max(corrs, key=lambda k: abs(corrs[k]))
        max_corr, corr_with = corrs[top], top
    else:
        max_corr, corr_with = 0.0, None

    return {
        "raw_icir": raw,
        "resid_icir": res_icir,
        "retention": float(res_icir / raw) if raw != 0 else 0.0,
        "max_corr": max_corr,
        "corr_with": corr_with,
    }


# --------------------------------------------------------------------------
# 2. 多重检验校正
# --------------------------------------------------------------------------
def benjamini_hochberg(pvalues: Iterable[float], alpha: float = 0.10) -> np.ndarray:
    """Benjamini-Hochberg FDR 控制。返回布尔数组：哪些假设可以拒绝原假设。

    与 Bonferroni 的区别：Bonferroni 控制"至少犯一次错"的概率，
    在测几百个因子时严苛到几乎什么都选不出来。BH 控制的是
    "入选的这批里假阳性占比"，对挖掘场景更合适 —— 你能接受
    10 个因子里有 1 个是假的，不能接受 10 个里有 5 个是假的。
    """
    p = np.asarray(list(pvalues), dtype=float)
    n = len(p)
    if n == 0:
        return np.array([], dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresholds = alpha * np.arange(1, n + 1) / n
    passed = ranked <= thresholds
    if not passed.any():
        return np.zeros(n, dtype=bool)
    k = np.max(np.where(passed)[0])
    out = np.zeros(n, dtype=bool)
    out[order[: k + 1]] = True
    return out


def ic_pvalue(ic_mean: float, ic_std: float, n_days: int) -> float:
    """由 IC 序列的均值/标准差/样本量算双侧 p 值。"""
    if ic_std <= 0 or n_days < 3 or not np.isfinite(ic_mean):
        return 1.0
    t = ic_mean / (ic_std / np.sqrt(n_days))
    return float(2 * (1 - stats.t.cdf(abs(t), df=n_days - 1)))


HLZ_THRESHOLD = 3.0   # Harvey, Liu & Zhu (2016)：新因子的 t 值门槛


def screen(
    trials: pd.DataFrame,
    alpha: float = 0.10,
    hlz_t: float = HLZ_THRESHOLD,
    min_retention: float = 0.5,
    min_abs_icir: float = 0.5,
) -> pd.DataFrame:
    """对一批因子试验做联合筛选。

    trials 需含列：factor_name, ic_mean, ic_std, n_days, t_stat, icir,
    以及可选的 retention。

    输出在原表基础上追加：p_value / bh_pass / hlz_pass / retention_pass / verdict
    """
    df = trials.copy()
    if df.empty:
        return df

    df["p_value"] = [ic_pvalue(r.ic_mean, r.ic_std, r.n_days) for r in df.itertuples()]
    df["bh_pass"] = benjamini_hochberg(df["p_value"], alpha=alpha)
    df["hlz_pass"] = df["t_stat"].abs() >= hlz_t
    if "retention" in df.columns:
        df["retention_pass"] = df["retention"].fillna(0) >= min_retention
    else:
        df["retention_pass"] = True
    df["icir_pass"] = df["icir"].abs() >= min_abs_icir

    def _verdict(r) -> str:
        if not r.bh_pass:
            return "否决：未通过 FDR"
        if not r.hlz_pass:
            return f"否决：t={abs(r.t_stat):.2f} < {hlz_t}"
        if not r.retention_pass:
            return f"否决：与已有因子冗余（保留率 {r.retention:.0%}）"
        if not r.icir_pass:
            return "否决：ICIR 过低"
        return "候选"

    df["verdict"] = [_verdict(r) for r in df.itertuples()]
    return df.sort_values("p_value")


# --------------------------------------------------------------------------
# 3. 挖掘循环
# --------------------------------------------------------------------------
@dataclass
class FactorSpec:
    """一个待检验的因子规格。"""

    name: str
    hypothesis: str                       # 经济逻辑，必填
    fn: Callable[[pd.DataFrame], pd.Series]
    formula: str = ""
    source: str = "manual"
    parent: str | None = None

    def __post_init__(self):
        if len(self.hypothesis.strip()) < 10:
            raise ValueError(
                f"因子 {self.name} 缺少经济逻辑。说不清'谁在犯错、"
                f"为什么这个错误能持续'的因子，不允许进入挖掘流水线。"
            )
        if not self.formula:
            self.formula = f"{self.name}@{self.fn.__name__}"


class FactorMiner:
    """因子挖掘器。

    用法：
        miner = FactorMiner(bars, mask, existing=current_library, log=ResearchLog())
        miner.test(spec)          # 逐个测，每次自动写日志
        report = miner.screen()   # 联合筛选（FDR + HLZ + 冗余）
    """

    def __init__(
        self,
        bars: pd.DataFrame,
        mask: pd.Series | None = None,
        existing: pd.DataFrame | None = None,
        log: ResearchLog | None = None,
        horizon: int = 5,
        universe: str = "A股全市场(已排雷)",
        neutralize: bool = True,
    ):
        self.bars = bars
        self.mask = mask
        self.existing = existing
        self.log = log or ResearchLog()
        self.horizon = horizon
        self.universe = universe
        self.neutralize = neutralize
        self.results: list[dict] = []

        d = bars.index.get_level_values("date")
        self.period = f"{d.min().date()}~{d.max().date()}"

    def test(self, spec: FactorSpec, verbose: bool = True) -> dict:
        """检验一个因子。无论结果好坏都写进研究日志。"""
        try:
            raw = spec.fn(self.bars)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [失败] {spec.name}: {e}")
            return {"factor_name": spec.name, "error": str(e)[:80]}

        prepped = F.prepare(raw, self.bars, neutral=self.neutralize)
        rep = evaluate_factor(prepped, self.bars, mask=self.mask,
                              name=spec.name, horizon=self.horizon, quick=True)
        s = rep.stats

        inc = incremental_value(prepped, self.existing, self.bars,
                                mask=self.mask, horizon=self.horizon)

        row = {
            "factor_name": spec.name, "hypothesis": spec.hypothesis,
            "formula": spec.formula, "source": spec.source, "parent": spec.parent,
            "ic_mean": s["ic_mean"], "ic_std": s["ic_std"], "icir": s["icir"],
            "t_stat": s["t_stat"], "monotonicity": s["monotonicity"],
            "ls_ann": s["ls_ann"], "autocorr": s["autocorr"], "n_days": s["n_days"],
            "resid_icir": inc["resid_icir"], "retention": inc["retention"],
            "max_corr": inc["max_corr"], "corr_with": inc["corr_with"],
        }
        self.results.append(row)

        self.log.record(Trial(
            factor_name=spec.name, hypothesis=spec.hypothesis, formula=spec.formula,
            universe=self.universe, period=self.period, horizon=self.horizon,
            ic_mean=s["ic_mean"], icir=s["icir"], t_stat=s["t_stat"],
            monotonicity=s["monotonicity"], ls_ann=s["ls_ann"],
            autocorr=s["autocorr"], n_days=s["n_days"],
            resid_icir=inc["resid_icir"], retention=inc["retention"],
            max_corr_existing=inc["max_corr"], corr_with=inc["corr_with"],
            source=spec.source, parent=spec.parent,
        ))

        if verbose:
            print(f"  {spec.name:<24} IC {s['ic_mean']:+.4f}  ICIR {s['icir']:+.2f}  "
                  f"t {s['t_stat']:+.2f}  保留率 {inc['retention']:.0%}")
        return row

    def test_many(self, specs: Iterable[FactorSpec], verbose: bool = True) -> pd.DataFrame:
        for sp in specs:
            self.test(sp, verbose=verbose)
        return pd.DataFrame(self.results)

    def screen(self, alpha: float = 0.10, **kw) -> pd.DataFrame:
        """联合筛选。注意：这里传入的是**本轮**所有试验，
        FDR 校正必须基于完整的搜索空间，不能只拿好看的那几个来算。"""
        if not self.results:
            return pd.DataFrame()
        return screen(pd.DataFrame(self.results), alpha=alpha, **kw)

    def multiple_testing_penalty(self, min_retention: float = 0.5) -> dict:
        """报告累计的多重检验惩罚。

        关于独立性：DSR 假设各次试验相互独立。但挖掘时你往往会测一堆
        近亲因子（同一想法的参数变体、已有因子的变形），它们的 ICIR
        高度相关且集中在相近的量级，会把 sigma_SR 抬得虚高，
        进而把"运气门槛"抬到不合理的位置 —— 方向上偏保守，但仍然是错的。

        所以 sigma_SR 只用**非冗余**试验（保留率 >= min_retention）估计，
        而试验次数仍用全量 —— 你确实搜索过那么大的空间，这份惩罚跑不掉。
        """
        from ..validate.antifit import deflated_sharpe

        df = self.log.load()
        n = self.log.trial_count()
        if df.empty or n < 2:
            return {"累计试验数": n, "note": "试验次数不足，无法估计惩罚"}

        d = df.drop_duplicates("fingerprint", keep="last")
        if "retention" not in d.columns:
            # 日志里没有冗余信息时如实说明，而不是静默按全量算 ——
            # 静默的 fallback 会让一个错误的 DSR 看起来像个正确的 DSR。
            return {"累计试验数": n,
                    "note": "研究日志缺少 retention 字段，无法剔除冗余试验；"
                            "sigma_SR 会被近亲因子抬高，DSR 结果偏保守且不可靠"}
        indep = d[d["retention"].fillna(1.0) >= min_retention]
        pool = indep if len(indep) >= 2 else d
        degraded = len(indep) < 2

        icirs = pool["icir"].dropna().values
        if len(icirs) < 2:
            return {"累计试验数": n, "note": "有效样本不足"}

        n_obs = len(self.bars.index.get_level_values("date").unique())
        best = float(np.nanmax(np.abs(icirs)))
        sigma = float(np.nanstd(icirs, ddof=1))
        dsr = deflated_sharpe(sharpe=best, n_trials=n, n_obs=n_obs, sigma_sr=sigma)

        return {
            "累计试验数": n,
            "其中非冗余": f"{len(indep)}" + ("（不足2个，已退回全量估计）" if degraded else ""),
            "sigma_SR(仅非冗余)": round(sigma, 3),
            "非冗余中的最优ICIR": round(best, 3),
            "运气可解释的ICIR": round(dsr.get("expected_max_sharpe_from_luck", np.nan), 3),
            "DSR": round(dsr.get("dsr", np.nan), 3),
            "结论": dsr.get("verdict", "—"),
        }
