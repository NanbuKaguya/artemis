"""全局配置。

设计原则：所有"会让你亏钱"的参数集中在这里，且默认值一律偏保守。
调参的方向应该是"我有证据所以放松"，而不是"回测不好看所以放松"。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json

from .rules import CostModel, DEFAULT_COST


@dataclass
class GuardConfig:
    """排雷层：硬性剔除规则。这一层的目的不是提高收益，是砍掉左尾。"""

    exclude_st: bool = True                     # 剔除 ST/*ST
    exclude_delisting_risk: bool = True         # 剔除退市风险警示
    exclude_suspended: bool = True              # 剔除停牌
    min_days_since_ipo: int = 120               # 次新股观察期（避开高波动+无历史）
    min_adv20: float = 5e7                      # 20 日日均成交额下限（元）
    max_position_adv_ratio: float = 0.05        # 单票持仓 <= 5% 的 20 日日均成交额
    min_market_cap: float = 3.0e9               # 总市值下限（元）—— 市值退市红线之上
    max_pledge_ratio: float | None = 0.50       # 大股东质押比例上限（数据可得时启用）
    exclude_recent_violation_days: int = 365    # 近 N 日被立案调查/违规处罚则剔除
    exclude_audit_qualified: bool = True        # 剔除非标准审计意见
    max_goodwill_to_equity: float | None = 0.30 # 商誉/净资产上限，防商誉爆雷
    exclude_pending_unlock_days: int = 0        # >0 时剔除 N 日内有大额解禁的票


@dataclass
class RegimeConfig:
    """择时层：决定总仓位，而不是决定买哪只。

    A 股的 beta 波动远大于多数散户的 alpha，控制总仓位的收益/风险比
    高于挑股票。这里用"多信号投票"而非单一指标，避免单点失效。
    """

    benchmark: str = "000300"          # 沪深300 作为市场状态基准
    breadth_universe: str = "all"      # 市场宽度的计算范围
    trend_fast: int = 20
    trend_slow: int = 60
    vol_window: int = 20
    vol_high_pct: float = 0.80         # 波动率分位 > 0.8 视为高波动
    breadth_window: int = 20
    min_position: float = 0.20         # 最低仓位（不清空，避免踏空）
    max_position: float = 0.95         # 最高仓位（永不满仓，留子弹）
    position_step: float = 0.10        # 仓位调整最小步长，避免频繁微调


@dataclass
class PortfolioConfig:
    """组合层：分散度与集中度约束。"""

    n_holdings: int = 20               # 目标持仓只数
    max_weight: float = 0.10           # 单票权重上限
    min_weight: float = 0.02           # 单票权重下限（低于此不值得占用一个坑）
    max_industry_weight: float = 0.30  # 单行业权重上限
    weighting: str = "equal"           # equal | inv_vol | score
    rebalance_freq: str = "W"          # D | W | M —— 频率越高，成本磨损越大
    max_turnover_per_rebalance: float = 0.30  # 单次调仓换手上限，抑制过度交易
    # 缓冲带：已持仓的股票，只要排名还在前 n_holdings * buffer 名内就继续持有。
    # 这是降低换手最有效的单一手段 —— 它消灭了大量"第 20 名和第 21 名换来换去"
    # 的无意义交易，而这种交易对收益几乎没贡献，对成本却是实打实的。
    hold_buffer: float = 1.6


@dataclass
class RiskConfig:
    """风控层：亏钱时的行为规则。写死在代码里，因为人在亏钱时不可信。"""

    stop_loss_pct: float = 0.12                # 单票止损线（自成本价）
    trailing_stop_pct: float = 0.18            # 单票移动止盈回撤线（自最高价）
    max_holding_days: int = 60                 # 最长持有期，强制换血
    portfolio_dd_warn: float = 0.08            # 组合回撤预警：降档
    portfolio_dd_derisk: float = 0.12          # 组合回撤降仓：仓位砍半
    portfolio_dd_halt: float = 0.18            # 组合回撤熔断：清仓 + 停止开新仓
    halt_cooldown_days: int = 20               # 熔断后冷却期
    max_daily_new_positions: int = 5           # 单日最多开仓数，防情绪化梭哈
    crowding_zscore_halt: float = 2.5          # 因子拥挤度 z 分超限则停用该因子


@dataclass
class ValidationConfig:
    """反过拟合门槛：策略"能上实盘"的准入线。不达标就不许上，没有例外。"""

    train_end: str = "2021-12-31"      # 样本内截止
    valid_end: str = "2023-12-31"      # 样本外验证截止
    # 剩余为"从未看过"的锁箱数据（holdout），只允许在最终决策前看一次

    min_oos_sharpe: float = 0.8
    max_oos_drawdown: float = 0.20
    min_oos_is_ratio: float = 0.50     # 样本外夏普 >= 样本内的 50%
    min_trades: int = 100              # 交易样本量下限，防小样本幻觉
    max_pbo: float = 0.35              # 过拟合概率上限（组合对称交叉验证）
    min_param_plateau_ratio: float = 0.60  # 参数邻域内 >=60% 的组合仍需为正
    require_random_control: bool = True     # 必须跑赢随机选股对照组


@dataclass
class ArtemisConfig:
    """总配置。"""

    account_size: float = 1_000_000.0
    cost: CostModel = field(default_factory=lambda: DEFAULT_COST)
    guard: GuardConfig = field(default_factory=GuardConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    data_dir: Path = field(default_factory=lambda: Path("./data_cache"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def turnover_budget(self) -> dict:
        """把成本换算成"换手率预算"——策略每年能承受多少换手。

        这是个被严重低估的约束：很多回测漂亮的策略，实盘就是被换手磨死的。
        """
        rt_bps = self.cost.round_trip_bps()
        return {
            "round_trip_bps": rt_bps,
            "cost_at_100pct_annual_turnover": rt_bps / 1e4,
            "max_annual_turnover_for_2pct_cost": 0.02 / (rt_bps / 1e4),
            "note": "年化成本 = 年换手率 × round_trip。要求成本 < 年化超额的 1/4。",
        }


DEFAULT_CONFIG = ArtemisConfig()
