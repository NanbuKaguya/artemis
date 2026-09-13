"""带 A 股真实摩擦的回测引擎。

回测引擎的唯一使命是：让你在电脑上亏的钱，和你在市场里亏的钱一样多。
任何让回测比现实好看的简化，都是在骗你自己的钱。

本引擎强制处理以下摩擦（每一条都对应一类真实亏损）：
  T+1              当日买入不可卖出 —— 你没有你以为的那么灵活
  涨停不可买        一字板挂单排队也买不到，回测里买进去是幻觉
  跌停不可卖        最需要跑的时候跑不掉，这是回撤的放大器
  停牌不可交易      停牌期间净值是"假"的，复牌可能直接跳空
  退市强制清算      按退市整理期折价处理，不是简单地从池子里消失
  最小交易单位      100 股/科创板 200 股，小资金的实际约束
  完整交易成本      佣金(含最低5元) + 印花税 + 过户费 + 滑点
  执行价 = T+1 开盘  T 日收盘的信号不可能以 T 日收盘价成交

信号约定：target_weights 的第 T 行 = T 日收盘后决定的目标权重，
引擎会在 T+1 开盘执行。引擎内部再做一次 shift，调用方不要自己 shift。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import ArtemisConfig, DEFAULT_CONFIG
from ..rules import CostModel, classify_board, price_limit_pct, round_limit_price, Board


@dataclass
class BacktestResult:
    equity: pd.Series                 # 净值曲线
    positions: pd.DataFrame           # 每日持仓市值 (date x code)
    trades: pd.DataFrame              # 成交明细
    daily: pd.DataFrame               # 每日账户快照
    blocked: pd.DataFrame             # 被摩擦挡下的交易 —— 回测与实盘的差距就藏在这里
    config: ArtemisConfig = field(repr=False, default=None)

    @property
    def returns(self) -> pd.Series:
        return self.equity.pct_change().fillna(0)


class Backtester:
    def __init__(self, cfg: ArtemisConfig | None = None, delist_haircut: float = 0.45):
        """delist_haircut: 退市清算的折价。A 股退市整理期通常腰斩以上，
        默认 45% 已经算温和。设成 0 就是在自欺欺人。"""
        self.cfg = cfg or DEFAULT_CONFIG
        self.delist_haircut = delist_haircut

    def run(
        self,
        bars: pd.DataFrame,
        target_weights: pd.DataFrame,
        position_scale: pd.Series | None = None,
        verbose: bool = False,
    ) -> BacktestResult:
        """
        target_weights: DataFrame (date x code)，行内权重和 <= 1，代表股票仓位占总资产比例
        position_scale: 可选的总仓位缩放（择时层输出），index=date
        """
        cost: CostModel = self.cfg.cost
        risk = self.cfg.risk

        dates = bars.index.get_level_values("date").unique().sort_values()
        codes = bars.index.get_level_values("code").unique().sort_values()

        # --- 宽表化，循环里只查 numpy，速度差一个数量级 ---
        def W(col):
            return bars[col].unstack("code").reindex(index=dates, columns=codes)

        op, hi, lo, cl = W("open").values, W("high").values, W("low").values, W("close").values
        pc = W("prev_close").values
        # 复权因子是阶梯函数，只在除权日跳变 —— 缺失时正确的补法是
        # 按股票 ffill，而不是填 1.0。填 1.0 等于说"这天没有过任何除权"，
        # 会让成本价和现价落在两套口径上，算出一段凭空的盈亏。
        adj = W("adj_factor").ffill().fillna(1.0).values
        # 缺失时一律往"更难成交"的方向取：
        #   is_st 未知 -> 当成 ST（涨跌停更窄，更多单子打不掉）
        #   停牌未知   -> 当成停牌
        #   上市未知   -> 当成不可交易
        # 回测的默认值必须偏悲观，否则你看到的净值曲线是数据缺失变出来的。
        st = W("is_st").fillna(True).values.astype(bool)
        susp = W("is_suspended").fillna(True).values.astype(bool)
        alive = W("is_tradable").fillna(False).values.astype(bool)
        amt = W("amount").fillna(0.0).values

        tw = target_weights.reindex(index=dates, columns=codes).fillna(0.0).values
        scale = (position_scale.reindex(dates).ffill().fillna(1.0).values
                 if position_scale is not None else np.ones(len(dates)))

        # --- 涨跌停价格网格 ---
        base_lim = np.array([price_limit_pct(c) for c in codes])
        # ST 只压缩主板的 10% -> 5%。创业板/科创板 ST 仍是 20%，
        # 北交所 ST 仍是 30% —— 别把它们一律按 20% 处理。
        st_lim = np.where(base_lim > 0.15, base_lim, 0.05)
        lim = np.where(st, st_lim[None, :], base_lim[None, :])
        up_px = np.round(pc * (1 + lim), 2)
        dn_px = np.round(pc * (1 - lim), 2)

        # 价格未知时不许成交。
        # 这里是 NaN 最容易造成"乐观偏差"的地方：昨收缺失 -> 涨停价是 NaN
        # -> `op >= nan` 求值为 False -> 系统认为"没涨停，可以买"。
        # 新股上市首日的 prev_close 恰恰就是 NaN，而那天的涨幅最极端。
        px_unknown = ~np.isfinite(pc) | ~np.isfinite(op)
        cannot_buy = susp | ~alive | px_unknown | (op >= up_px - 1e-6) | (op <= 0)
        cannot_sell = susp | ~alive | px_unknown | (op <= dn_px + 1e-6) | (op <= 0)

        lot = np.array([200 if classify_board(c) is Board.STAR else 100 for c in codes])
        adv20 = pd.DataFrame(amt, index=dates, columns=codes).rolling(20, min_periods=5).mean().values

        n_d, n_c = len(dates), len(codes)
        shares = np.zeros(n_c)
        cost_basis = np.zeros(n_c)      # 加权平均成本（后复权口径）
        peak_px = np.zeros(n_c)         # 持仓期最高价，用于移动止盈
        buy_date_idx = np.full(n_c, -1) # T+1 约束：记录建仓日
        cash = self.cfg.account_size

        equity_hist, pos_hist, daily_rows = [], [], []
        trades, blocked = [], []
        halt_until = -1
        peak_equity = cash

        for t in range(n_d):
            date = dates[t]
            px_t = cl[t]
            valid_px = np.where(alive[t] & (px_t > 0), px_t, 0.0)

            # ---------- 1. 退市强制清算 ----------
            just_dead = (shares > 0) & (~alive[t])
            if just_dead.any():
                for j in np.where(just_dead)[0]:
                    last_px = cl[t - 1, j] if t > 0 and cl[t - 1, j] > 0 else cost_basis[j]
                    proceeds = shares[j] * last_px * (1 - self.delist_haircut)
                    cash += proceeds - cost.sell_cost(proceeds)
                    trades.append(dict(date=date, code=codes[j], side="delist",
                                       shares=shares[j], price=last_px * (1 - self.delist_haircut),
                                       amount=proceeds, reason="退市清算"))
                    shares[j] = 0.0; cost_basis[j] = 0.0; peak_px[j] = 0.0

            # ---------- 2. 组合层风控：回撤熔断 ----------
            equity_now = cash + float((shares * valid_px).sum())
            peak_equity = max(peak_equity, equity_now)
            dd = equity_now / peak_equity - 1 if peak_equity > 0 else 0.0

            if dd <= -risk.portfolio_dd_halt and t > halt_until:
                halt_until = t + risk.halt_cooldown_days
            in_halt = t <= halt_until

            derisk_mult = 1.0
            if dd <= -risk.portfolio_dd_derisk:
                derisk_mult = 0.5
            elif dd <= -risk.portfolio_dd_warn:
                derisk_mult = 0.75

            # ---------- 3. 目标权重 ----------
            # tw[t-1] 是 T-1 收盘算出的目标，在 T 开盘执行 —— 引擎内部完成滞后
            w_target = tw[t - 1] if t >= 1 else np.zeros(n_c)
            gross = scale[t - 1] if t >= 1 else 0.0
            w_target = w_target * gross * derisk_mult
            if in_halt:
                w_target = np.zeros(n_c)

            # ---------- 4. 个股风控：止损 / 移动止盈 / 超期 ----------
            held = shares > 0
            if held.any():
                adj_px = px_t * adj[t]
                peak_px = np.where(held, np.maximum(peak_px, adj_px), peak_px)
                pnl = np.divide(adj_px, cost_basis, out=np.ones(n_c), where=cost_basis > 0) - 1
                drawdown_from_peak = np.divide(adj_px, peak_px, out=np.ones(n_c), where=peak_px > 0) - 1
                force_exit = held & (
                    (pnl <= -risk.stop_loss_pct)
                    | (drawdown_from_peak <= -risk.trailing_stop_pct)
                    | ((t - buy_date_idx) > risk.max_holding_days)
                )
                w_target = np.where(force_exit, 0.0, w_target)

            # ---------- 5. 生成订单 ----------
            equity_for_sizing = equity_now
            target_value = w_target * equity_for_sizing
            cur_value = shares * valid_px
            delta_value = target_value - cur_value

            # 单次调仓换手上限：抑制过度交易
            max_turn = self.cfg.portfolio.max_turnover_per_rebalance * equity_for_sizing
            total_turn = np.abs(delta_value).sum()
            if total_turn > max_turn > 0:
                delta_value *= max_turn / total_turn

            # ---------- 6. 卖出（先卖后买，保证现金可用）----------
            sell_idx = np.where((delta_value < 0) & (shares > 0))[0]
            for j in sell_idx:
                if cannot_sell[t, j]:
                    blocked.append(dict(date=date, code=codes[j], side="sell",
                                        reason="跌停/停牌无法卖出",
                                        want=float(-delta_value[j])))
                    continue
                if buy_date_idx[j] == t:
                    # 防御性检查。T+1 主要由执行顺序保证：卖出循环在买入循环
                    # 之前运行，所以当日买入的股票不可能在当日进入卖出流程。
                    # 这行是防止未来有人调换两个循环的顺序而悄悄破坏 T+1。
                    blocked.append(dict(date=date, code=codes[j], side="sell",
                                        reason="T+1 当日买入不可卖出",
                                        want=float(-delta_value[j])))
                    continue
                px = op[t, j]
                if px <= 0:
                    continue
                want_sh = min(shares[j], -delta_value[j] / px)
                # 剩余不足一手则全部卖出（交易所规则）
                if shares[j] - want_sh < lot[j]:
                    want_sh = shares[j]
                want_sh = float(np.floor(want_sh)) if want_sh < shares[j] else float(shares[j])
                if want_sh <= 0:
                    continue
                fill = px * (1 - cost.slippage_bps / 1e4)
                turnover = want_sh * fill
                cash += turnover - cost.sell_cost(turnover)
                shares[j] -= want_sh
                if shares[j] <= 0:
                    cost_basis[j] = 0.0; peak_px[j] = 0.0; buy_date_idx[j] = -1
                trades.append(dict(date=date, code=codes[j], side="sell", shares=want_sh,
                                   price=fill, amount=turnover, reason="调仓/风控"))

            # ---------- 7. 买入 ----------
            buy_idx = np.where(delta_value > 0)[0]
            # 按需求金额从大到小买，现金不够时优先满足权重大的
            buy_idx = buy_idx[np.argsort(-delta_value[buy_idx])]
            n_new = 0
            for j in buy_idx:
                if cannot_buy[t, j]:
                    blocked.append(dict(date=date, code=codes[j], side="buy",
                                        reason="涨停/停牌无法买入", want=float(delta_value[j])))
                    continue
                if shares[j] == 0 and n_new >= self.cfg.risk.max_daily_new_positions:
                    blocked.append(dict(date=date, code=codes[j], side="buy",
                                        reason="单日开仓数量上限", want=float(delta_value[j])))
                    continue
                px = op[t, j]
                if px <= 0:
                    continue
                fill = px * (1 + cost.slippage_bps / 1e4)

                budget = min(delta_value[j], cash * 0.98)
                # 流动性约束：单日买入不超过 20 日均额的一定比例
                liq_cap = adv20[t, j] * self.cfg.guard.max_position_adv_ratio
                if np.isfinite(liq_cap) and liq_cap > 0:
                    if budget > liq_cap:
                        blocked.append(dict(date=date, code=codes[j], side="buy",
                                            reason="流动性上限截断",
                                            want=float(budget - liq_cap)))
                    budget = min(budget, liq_cap)

                want_sh = np.floor(budget / fill / lot[j]) * lot[j]
                if want_sh <= 0:
                    continue
                turnover = want_sh * fill
                fee = cost.buy_cost(turnover)
                if turnover + fee > cash:
                    continue
                new_total = shares[j] + want_sh
                adj_fill = fill * adj[t, j]
                cost_basis[j] = ((cost_basis[j] * shares[j] + adj_fill * want_sh) / new_total
                                 if new_total > 0 else 0.0)
                if shares[j] == 0:
                    peak_px[j] = adj_fill
                    buy_date_idx[j] = t
                    n_new += 1
                shares[j] = new_total
                cash -= turnover + fee
                trades.append(dict(date=date, code=codes[j], side="buy", shares=want_sh,
                                   price=fill, amount=turnover, reason="调仓"))

            # ---------- 8. 收盘估值 ----------
            mv = shares * valid_px
            equity = cash + float(mv.sum())
            equity_hist.append(equity)
            pos_hist.append(mv.copy())
            daily_rows.append(dict(
                date=date, equity=equity, cash=cash, stock_value=float(mv.sum()),
                position_pct=float(mv.sum()) / equity if equity > 0 else 0.0,
                n_holdings=int((shares > 0).sum()), drawdown=dd, halted=in_halt,
                derisk_mult=derisk_mult,
            ))
            if verbose and t % 250 == 0:
                print(f"  {date.date()} equity={equity:,.0f} pos={mv.sum()/equity:.0%} n={int((shares>0).sum())}")

        equity_s = pd.Series(equity_hist, index=dates, name="equity")
        positions = pd.DataFrame(pos_hist, index=dates, columns=codes)
        return BacktestResult(
            equity=equity_s,
            positions=positions,
            trades=pd.DataFrame(trades),
            daily=pd.DataFrame(daily_rows).set_index("date"),
            blocked=pd.DataFrame(blocked),
            config=self.cfg,
        )
