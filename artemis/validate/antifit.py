"""反过拟合验证流水线。

这是整个系统里最该被认真对待的模块。理由很简单：
散户量化亏钱的头号原因不是"没找到好策略"，而是"把一个过拟合的策略
当成好策略上了实盘"。回测年化 100%、实盘半年亏 50% 的故事，
每天都在发生。

本模块提供五道闸门，全部通过才允许上实盘：
  1. 样本外检验     —— 训练/验证/锁箱三段切分，锁箱只看一次
  2. 滚动前推       —— walk-forward，模拟"你当时只知道过去"
  3. 随机对照       —— 你的策略必须显著跑赢随机选股，否则赚的是 beta 不是 alpha
  4. 参数高原       —— 最优参数的邻居也得能赚钱，否则是踩在针尖上
  5. PBO / DSR      —— 量化"这个回测有多大概率是撞运气撞出来的"

没有一道闸门是可选的。跳过任何一道，你就是在用真金白银做样本外测试。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Iterable

import numpy as np
import pandas as pd
from scipy import stats

from ..backtest.metrics import perf_stats

# 策略函数签名：(bars, params) -> equity curve (pd.Series)
StrategyFn = Callable[[pd.DataFrame, dict], pd.Series]


# ---------------------------------------------------------------- 1. 样本切分
@dataclass
class Split:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


def three_way_split(dates: pd.DatetimeIndex, train_end: str, valid_end: str) -> list[Split]:
    """训练 / 验证 / 锁箱。

    锁箱（holdout）的纪律：在你决定"这个策略要上实盘"之前，
    一次都不许看。看过一次，它就变成了验证集，你就又少了一道防线。
    """
    d = pd.DatetimeIndex(dates).sort_values()
    te, ve = pd.Timestamp(train_end), pd.Timestamp(valid_end)
    return [
        Split("train", d[0], te),
        Split("valid", te + pd.Timedelta(days=1), ve),
        Split("holdout", ve + pd.Timedelta(days=1), d[-1]),
    ]


# ---------------------------------------------------------------- 2. 滚动前推
def walk_forward(
    bars: pd.DataFrame,
    strategy: StrategyFn,
    params: dict,
    n_folds: int = 5,
    train_years: float = 3.0,
    test_years: float = 1.0,
) -> pd.DataFrame:
    """滚动前推检验：每一折只用过去的数据，测未来的一段。

    这是最接近真实交易的检验方式：你在 2020 年做决策时，
    不可能知道 2021 年会发生什么。
    """
    dates = bars.index.get_level_values("date").unique().sort_values()
    rows = []
    step = int(test_years * 252)
    train_n = int(train_years * 252)
    start = 0
    fold = 0
    while start + train_n + step <= len(dates) and fold < n_folds:
        tr_end = start + train_n
        te_end = min(tr_end + step, len(dates))
        test_slice = bars[bars.index.get_level_values("date").isin(dates[start:te_end])]
        eq = strategy(test_slice, params)
        # 只统计测试段
        eq_test = eq[eq.index >= dates[tr_end]]
        if len(eq_test) > 20:
            s = perf_stats(eq_test)
            rows.append({
                "fold": fold,
                "test_start": dates[tr_end].date(),
                "test_end": dates[te_end - 1].date(),
                "annual_return": s["annual_return"],
                "sharpe": s["sharpe"],
                "max_drawdown": s["max_drawdown"],
            })
        start += step
        fold += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. 随机对照
def random_control(
    bars: pd.DataFrame,
    strategy_equity: pd.Series,
    random_strategy: Callable[[pd.DataFrame, int], pd.Series],
    n_trials: int = 30,
) -> dict:
    """随机对照组。

    做法：用完全随机的分数跑同一套流水线 n 次，得到"运气分布"。
    然后问：我的策略在这个分布里排第几？

    这一步能救你的命。因为排雷层、择时层、止损本身就会产生正超额 ——
    如果不跟随机组比，你会把风控的功劳当成选股能力，
    然后在因子失效时毫无察觉。
    """
    my = perf_stats(strategy_equity)
    ctrl = []
    for i in range(n_trials):
        eq = random_strategy(bars, i)
        if eq is None or len(eq) < 20:
            continue
        ctrl.append(perf_stats(eq))
    if not ctrl:
        return {"error": "随机对照组全部失败"}

    c = pd.DataFrame(ctrl)
    out = {}
    for metric in ["annual_return", "sharpe", "calmar"]:
        vals = c[metric].dropna().values
        mine = my.get(metric, np.nan)
        pct = float((vals < mine).mean()) if len(vals) else np.nan
        out[metric] = {
            "strategy": float(mine),
            "control_mean": float(np.mean(vals)),
            "control_p95": float(np.percentile(vals, 95)),
            "percentile": pct,
            "beats_control": bool(pct >= 0.95),
        }
    out["n_trials"] = len(ctrl)
    out["verdict"] = "通过" if out["sharpe"]["beats_control"] else "未通过：与随机选股无显著差异"
    return out


# ---------------------------------------------------------------- 4. 参数高原
def parameter_plateau(
    bars: pd.DataFrame,
    strategy: StrategyFn,
    param_grid: dict[str, Iterable],
    metric: str = "sharpe",
) -> pd.DataFrame:
    """扫参数网格，看最优点周围是"高原"还是"针尖"。

    针尖 = 过拟合。真实的 edge 对参数不敏感：把持仓从 20 只改成 25 只、
    调仓从周频改成双周频，收益应该只是平滑变化，不该断崖。
    如果只有一组参数能赚钱，那组参数就是历史噪音的形状。
    """
    keys = list(param_grid)
    rows = []
    for combo in itertools.product(*[list(param_grid[k]) for k in keys]):
        p = dict(zip(keys, combo))
        try:
            eq = strategy(bars, p)
            s = perf_stats(eq)
            rows.append({**p, metric: s.get(metric, np.nan),
                         "annual_return": s.get("annual_return", np.nan),
                         "max_drawdown": s.get("max_drawdown", np.nan)})
        except Exception as e:  # noqa: BLE001
            rows.append({**p, metric: np.nan, "error": str(e)[:50]})
    df = pd.DataFrame(rows)
    if df[metric].notna().sum() > 0:
        df.attrs["positive_ratio"] = float((df[metric] > 0).mean())
        df.attrs["best"] = df.loc[df[metric].idxmax()].to_dict()
        df.attrs["median"] = float(df[metric].median())
        # 高原度：中位数 / 最优值。越接近 1 说明越像高原
        best = df[metric].max()
        df.attrs["plateau_ratio"] = float(df[metric].median() / best) if best > 0 else 0.0
    return df


# ---------------------------------------------------------------- 5. PBO / DSR
def pbo_cscv(returns_matrix: pd.DataFrame, n_splits: int = 8) -> dict:
    """组合对称交叉验证估计过拟合概率 (Bailey et al. 2015)。

    输入：每列是一个候选策略（或一组参数）的日收益序列。
    输出：PBO = "样本内最优的那个策略，在样本外落到中位数以下"的概率。

    直觉：如果你试了 100 组参数挑出最好的一组，PBO 会告诉你
    这个"最好"有多大概率纯属幸存者偏差。PBO > 0.5 意味着
    你的选优过程还不如随机挑一个。
    """
    R = returns_matrix.dropna(how="all").fillna(0)
    n_obs, n_strat = R.shape
    if n_strat < 2 or n_obs < n_splits * 4:
        return {"pbo": np.nan, "note": "样本不足，无法估计 PBO"}

    block = n_obs // n_splits
    blocks = [R.iloc[i * block:(i + 1) * block] for i in range(n_splits)]

    logits = []
    # 枚举所有把 n_splits 个块平分成 IS/OOS 的组合
    for is_idx in itertools.combinations(range(n_splits), n_splits // 2):
        oos_idx = [i for i in range(n_splits) if i not in is_idx]
        IS = pd.concat([blocks[i] for i in is_idx])
        OOS = pd.concat([blocks[i] for i in oos_idx])

        is_sharpe = IS.mean() / IS.std().replace(0, np.nan)
        oos_sharpe = OOS.mean() / OOS.std().replace(0, np.nan)
        if is_sharpe.isna().all() or oos_sharpe.isna().all():
            continue
        best = is_sharpe.idxmax()
        # 该策略在样本外的相对排名
        rank = oos_sharpe.rank(pct=True).get(best, np.nan)
        if np.isnan(rank):
            continue
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(np.log(rank / (1 - rank)))

    if not logits:
        return {"pbo": np.nan, "note": "无有效组合"}
    logits = np.array(logits)
    pbo = float((logits <= 0).mean())
    return {
        "pbo": pbo,
        "n_combinations": len(logits),
        "median_logit": float(np.median(logits)),
        "verdict": "通过" if pbo < 0.35 else ("警戒" if pbo < 0.5 else "不通过：选优过程无效"),
    }


def deflated_sharpe(
    sharpe: float,
    n_trials: int,
    n_obs: int,
    sigma_sr: float = 0.5,
    skew: float = 0.0,
    kurt: float = 3.0,
    periods_per_year: int = 252,
) -> dict:
    """收缩夏普比率 (Bailey & López de Prado, 2014)。

    你试了 200 组参数才挑出夏普 2.0 的策略，那个 2.0 里有多少是运气？
    DSR 给出扣除"多重检验红利"之后的真实置信度。

    参数
    ----
    sharpe      : 你最终选中那组参数的年化夏普
    n_trials    : 你一共试过多少组参数/多少个策略变体（诚实填写，这是关键）
    n_obs       : 回测的观测期数（交易日数）
    sigma_sr    : 各次试验的年化夏普的横截面标准差。这一项不能省 ——
                  它决定了"运气的方差有多大"。有实际试验记录时请传入
                  真实值（trial_sharpes.std()）；没有时 0.5 是常见量级。
    skew, kurt  : 策略日收益的偏度和峰度。A 股策略普遍左偏 + 厚尾，
                  两者都会侵蚀 DSR —— 这正是它比裸夏普诚实的地方。

    实践含义：每多试一组参数，你需要的夏普门槛就更高一点。
    这是对"调参调到满意为止"最直接的惩罚。
    """
    if n_trials < 2 or n_obs < 10 or sigma_sr <= 0:
        return {"dsr": np.nan, "note": "n_trials 需 >= 2, n_obs >= 10, sigma_sr > 0"}

    sqrt_p = np.sqrt(periods_per_year)
    sr_p = sharpe / sqrt_p                 # 转成单期夏普
    sigma_p = sigma_sr / sqrt_p            # 试验夏普的单期标准差

    # 多重检验下，纯运气能带来的期望最大夏普
    e = np.euler_gamma
    z1 = stats.norm.ppf(1 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    sr0_p = sigma_p * ((1 - e) * z1 + e * z2)

    denom = np.sqrt(max(1 - skew * sr_p + (kurt - 1) / 4 * sr_p ** 2, 1e-12))
    z = (sr_p - sr0_p) * np.sqrt(n_obs - 1) / denom
    dsr = float(stats.norm.cdf(z))

    return {
        "dsr": dsr,
        "expected_max_sharpe_from_luck": float(sr0_p * sqrt_p),
        "your_sharpe": sharpe,
        "n_trials": n_trials,
        "sigma_sr": sigma_sr,
        "verdict": "通过" if dsr > 0.95 else ("警戒" if dsr > 0.80 else "不通过：夏普可用运气解释"),
    }


def trial_log_to_dsr(trial_sharpes: Iterable[float], n_obs: int,
                     returns: pd.Series | None = None) -> dict:
    """从真实的试验记录直接算 DSR —— 这是推荐用法。

    把你调参过程中每一组参数的年化夏普都记下来（研究日志的价值就在这里），
    传进来。sigma_sr 用真实的横截面标准差，比拍脑袋的默认值可信得多。
    """
    arr = np.asarray([x for x in trial_sharpes if np.isfinite(x)], dtype=float)
    if arr.size < 2:
        return {"dsr": np.nan, "note": "至少需要 2 次试验记录"}
    skew = float(stats.skew(returns.dropna())) if returns is not None and len(returns.dropna()) > 8 else 0.0
    kurt = float(stats.kurtosis(returns.dropna(), fisher=False)) if returns is not None and len(returns.dropna()) > 8 else 3.0
    return deflated_sharpe(
        sharpe=float(arr.max()), n_trials=int(arr.size), n_obs=n_obs,
        sigma_sr=float(arr.std(ddof=1)), skew=skew, kurt=kurt,
    )


# ---------------------------------------------------------------- 总闸门
@dataclass
class GateResult:
    passed: bool
    checks: dict = field(default_factory=dict)

    def report(self) -> pd.DataFrame:
        rows = [{"闸门": k, "结论": v.get("verdict", "—"),
                 "关键值": v.get("key", "")} for k, v in self.checks.items()]
        return pd.DataFrame(rows)


def deployment_gate(
    oos_stats: dict,
    is_stats: dict,
    random_ctrl: dict | None,
    plateau: pd.DataFrame | None,
    pbo: dict | None,
    dsr: dict | None,
    cfg,
) -> GateResult:
    """上线闸门：全部通过才允许投真钱。

    这个函数刻意写成"默认拒绝"。你要做的不是说服它放行，
    而是拿出证据。
    """
    checks: dict[str, dict] = {}

    sh = oos_stats.get("sharpe", 0)
    checks["样本外夏普"] = {
        "verdict": "通过" if sh >= cfg.min_oos_sharpe else "不通过",
        "key": f"{sh:.2f} (要求 >= {cfg.min_oos_sharpe})",
    }
    dd = abs(oos_stats.get("max_drawdown", 1))
    checks["样本外回撤"] = {
        "verdict": "通过" if dd <= cfg.max_oos_drawdown else "不通过",
        "key": f"{dd:.1%} (要求 <= {cfg.max_oos_drawdown:.0%})",
    }
    is_sh = is_stats.get("sharpe", 0)
    ratio = sh / is_sh if is_sh > 0 else 0
    checks["样本外/样本内衰减"] = {
        "verdict": "通过" if ratio >= cfg.min_oos_is_ratio else "不通过",
        "key": f"{ratio:.0%} (要求 >= {cfg.min_oos_is_ratio:.0%})",
    }
    if random_ctrl and "sharpe" in random_ctrl:
        checks["随机对照"] = {
            "verdict": random_ctrl.get("verdict", "—"),
            "key": f"分位 {random_ctrl['sharpe']['percentile']:.0%}",
        }
    if plateau is not None and "plateau_ratio" in plateau.attrs:
        pr = plateau.attrs["plateau_ratio"]
        pos = plateau.attrs.get("positive_ratio", 0)
        checks["参数高原"] = {
            "verdict": "通过" if pos >= cfg.min_param_plateau_ratio else "不通过",
            "key": f"正收益参数占比 {pos:.0%}, 高原度 {pr:.2f}",
        }
    if pbo and not np.isnan(pbo.get("pbo", np.nan)):
        checks["PBO 过拟合概率"] = {
            "verdict": "通过" if pbo["pbo"] <= cfg.max_pbo else "不通过",
            "key": f"{pbo['pbo']:.0%} (要求 <= {cfg.max_pbo:.0%})",
        }
    if dsr and not np.isnan(dsr.get("dsr", np.nan)):
        checks["收缩夏普 DSR"] = {"verdict": dsr.get("verdict", "—"), "key": f"{dsr['dsr']:.2f}"}

    passed = all(v["verdict"] == "通过" for v in checks.values())
    return GateResult(passed=passed, checks=checks)
