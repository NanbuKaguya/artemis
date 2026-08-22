"""因子挖掘流水线（端到端）。

流程：
  1. 载入数据 + 排雷            → 确定研究样本
  2. 建立"已有因子库"基准       → 新因子必须超越它才有意义
  3. 批量检验候选因子           → 每次试验自动写研究日志
  4. 联合筛选                   → FDR + Harvey-Liu-Zhu 门槛 + 冗余检验
  5. 报告累计多重检验惩罚       → 你一共搜索了多大的空间

刻意在候选池里混入三类因子，用来检验流水线本身：
  · 已在库中的因子的变体   → 应被"冗余"否决
  · 纯随机噪音             → 应被 FDR 否决
  · 同一想法的参数变体     → 演示搜索空间如何爆炸

真实数据上用法一样，把 load_data() 换成从 BarStore 读即可。
"""
from __future__ import annotations

import sys, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from artemis.data.synthetic import make_market
from artemis.guard.rules import Guard
from artemis.alpha import factors as F
from artemis.alpha.mining import FactorMiner, FactorSpec
from artemis.alpha.research_log import ResearchLog

pd.set_option("display.width", 200)


# --------------------------------------------------------------------------
# 候选因子定义。每个都必须写清经济逻辑，否则 FactorSpec 会拒绝。
# --------------------------------------------------------------------------
def _px(bars, col="close"):
    return bars[col].unstack("code")


def _back(wide, index):
    return wide.stack(future_stack=True).reindex(index)


def make_candidates(seed: int = 0) -> list[FactorSpec]:
    rng = np.random.default_rng(seed)
    specs: list[FactorSpec] = []

    # --- 类别 A：已有库中因子的近亲，应被判为冗余 ---
    for w in (15, 25):
        specs.append(FactorSpec(
            name=f"reversal_{w}",
            hypothesis="短期反转：A股散户占比高，情绪驱动的超涨超跌会均值回复",
            formula=f"-(close/close.shift({w})-1)",
            fn=lambda b, w=w: _back(-(_px(b) / _px(b).shift(w) - 1), b.index),
            source="grid", parent="reversal_20",
        ))

    # --- 类别 B：真实的新想法 ---
    specs.append(FactorSpec(
        name="downside_vol_60",
        hypothesis="下行波动率：投资者对下跌的厌恶远大于对上涨的偏好，只惩罚下行波动比总波动更贴近真实风险定价",
        formula="-std(min(ret,0), 60)",
        fn=lambda b: _back(-_px(b).pct_change().clip(upper=0).rolling(60, min_periods=30).std(), b.index),
    ))
    specs.append(FactorSpec(
        name="turnover_trend",
        hypothesis="换手率趋势：换手率快速抬升说明筹码正在从长期持有者转向短线资金，抛压结构在恶化",
        formula="-(turnover_ma5 / turnover_ma60 - 1)",
        fn=lambda b: _back(
            -((b["amount"] / b["float_mv"]).unstack("code").rolling(5, min_periods=3).mean()
              / (b["amount"] / b["float_mv"]).unstack("code").rolling(60, min_periods=30).mean() - 1),
            b.index),
    ))
    specs.append(FactorSpec(
        name="range_compression",
        hypothesis="波幅压缩：近期日内波幅相对历史压缩，说明分歧收敛、筹码沉淀，往往先于方向性突破",
        formula="-(range_ma10 / range_ma60)",
        fn=lambda b: _back(
            -(((_px(b, "high") - _px(b, "low")) / _px(b)).rolling(10, min_periods=5).mean()
              / ((_px(b, "high") - _px(b, "low")) / _px(b)).rolling(60, min_periods=30).mean()),
            b.index),
    ))
    specs.append(FactorSpec(
        name="close_position_20",
        hypothesis="收盘位置：收盘价在近期高低区间中的相对位置，反映日内多空力量的持续方向",
        formula="(close - min_20) / (max_20 - min_20)",
        fn=lambda b: _back(
            (_px(b) - _px(b, "low").rolling(20, min_periods=10).min())
            / (_px(b, "high").rolling(20, min_periods=10).max()
               - _px(b, "low").rolling(20, min_periods=10).min()).replace(0, np.nan),
            b.index),
    ))

    # --- 类别 C：同一想法的参数变体，演示搜索空间爆炸 ---
    for fast, slow in [(5, 20), (10, 40), (20, 60), (10, 60)]:
        specs.append(FactorSpec(
            name=f"ma_ratio_{fast}_{slow}",
            hypothesis="均线比价：快线相对慢线的位置度量趋势强度，趋势延续源于信息扩散的时滞",
            formula=f"ma{fast}/ma{slow}-1",
            fn=lambda b, f=fast, s=slow: _back(
                _px(b).rolling(f, min_periods=max(2, f // 2)).mean()
                / _px(b).rolling(s, min_periods=s // 2).mean() - 1, b.index),
            source="grid", parent="ma_ratio",
        ))

    # --- 类别 D：纯噪音对照，应被 FDR 全部否决 ---
    for i in range(4):
        specs.append(FactorSpec(
            name=f"noise_control_{i}",
            hypothesis="对照组：纯随机数，不应通过任何筛选。它的存在是为了检验筛选器本身",
            formula=f"random_seed_{i}",
            fn=lambda b, i=i: pd.Series(
                np.random.default_rng(1000 + i).normal(size=len(b)), index=b.index),
            source="control",
        ))
    return specs


def main(seed: int = 7, n_stocks: int = 250, n_days: int = 1400):
    t0 = time.time()
    print(f"载入数据（{n_stocks} 只 × {n_days} 天）...")
    bars, _ = make_market(n_stocks=n_stocks, n_days=n_days, seed=seed)
    mask = Guard().apply(bars).mask
    print(f"  {len(bars):,} 行，排雷后可交易样本占 {mask.mean():.1%}\n")

    # --- 已有因子库：新因子必须相对它有增量 ---
    lib_names = ["momentum_120_20", "low_vol_60", "turnover_20", "reversal_20"]
    lib_raw = F.compute(bars, lib_names)
    existing = pd.DataFrame(
        {c: F.prepare(lib_raw[c], bars) for c in lib_raw.columns}, index=bars.index)
    print(f"已有因子库：{', '.join(lib_names)}\n")

    log = ResearchLog("./research_log.jsonl")
    miner = FactorMiner(bars, mask=mask, existing=existing, log=log, horizon=5)

    specs = make_candidates()
    print(f"检验 {len(specs)} 个候选因子：")
    miner.test_many(specs)

    print("\n" + "=" * 100)
    print("联合筛选：FDR(10%) + Harvey-Liu-Zhu t≥3.0 + 冗余检验(保留率≥50%)")
    print("=" * 100)
    rep = miner.screen(alpha=0.10)
    cols = ["factor_name", "icir", "t_stat", "p_value", "retention", "max_corr", "verdict"]
    print(rep[cols].round(3).to_string(index=False))

    print("\n" + "=" * 100)
    n_pass = int((rep.verdict == "候选").sum())
    print(f"入选 {n_pass} / {len(rep)} 个")
    ctrl = rep[rep.factor_name.str.startswith("noise_control")]
    print(f"噪音对照组：{len(ctrl)} 个，入选 {int((ctrl.verdict=='候选').sum())} 个"
          f" —— {'筛选器工作正常' if (ctrl.verdict=='候选').sum()==0 else '⚠ 筛选器漏检'}")

    print("\n--- 各否决原因分布 ---")
    print(rep.verdict.value_counts().to_string())

    print("\n--- 累计多重检验惩罚（含历史所有轮次）---")
    pen = miner.multiple_testing_penalty()
    for k, v in pen.items():
        print(f"  {k}: {v}")

    print("\n--- 研究日志 ---")
    print(log.summary().T.to_string(header=False))
    dup = log.duplicates()
    if not dup.empty:
        print(f"\n  被重复测试的因子 {len(dup)} 个（同一公式换了名字）")

    print(f"\n耗时 {time.time()-t0:.0f}s")
    return rep


if __name__ == "__main__":
    main()
