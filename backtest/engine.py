"""
Backtesting engine with simple walk-forward support.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np
from copy import deepcopy

from core.models import Signal, Side, Trade
from core.boss import BossAgent
from core.risk import RiskAgent
from agents.momentum import MomentumAgent
from agents.mean_reversion import MeanReversionAgent
from agents.breakout import BreakoutAgent
from agents.volatility import VolatilityAgent
from agents.seasonality import SeasonalityAgent
from agents.cot import COTAgent
from agents.orderflow import OrderFlowAgent
from config.settings import CONTRACTS, SIM, DEFAULT_UNIVERSE
from data.feed import fetch_history


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: List[Trade]
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate: float
    profit_factor: float
    n_trades: int
    params: dict = field(default_factory=dict)


def build_default_agents():
    return [
        MomentumAgent("momentum_1", weight=1.0),
        MeanReversionAgent("meanrev_1", weight=0.75),
        BreakoutAgent("breakout_1", weight=0.9),
        VolatilityAgent("vol_1", weight=0.6),
        SeasonalityAgent("seasonality_1", weight=0.45),
        COTAgent("cot_1", weight=0.55),
        OrderFlowAgent("orderflow_1", weight=0.6),
    ]


class Backtester:
    def __init__(self, agents=None, starting_equity: float = None):
        self.agents = agents or build_default_agents()
        self.starting_equity = starting_equity or SIM["starting_equity"]
        self.commission = SIM["commission_per_side"]
        self.slippage_ticks = SIM["slippage_ticks"]

    def run(self, market_data: Dict[str, pd.DataFrame],
            start: Optional[str] = None,
            end: Optional[str] = None) -> BacktestResult:
        """
        Event-driven style backtest on daily bars.
        At each bar the Boss sees only data up to that point (no look-ahead).
        """
        # Align all symbols to common index
        common_idx = None
        for df in market_data.values():
            common_idx = df.index if common_idx is None else common_idx.intersection(df.index)
        common_idx = common_idx.sort_values()

        if start:
            common_idx = common_idx[common_idx >= pd.Timestamp(start)]
        if end:
            common_idx = common_idx[common_idx <= pd.Timestamp(end)]

        if len(common_idx) < 60:
            raise ValueError("Not enough bars for backtest")

        boss = BossAgent(deepcopy(self.agents), RiskAgent())
        boss.equity = self.starting_equity
        boss.cash = self.starting_equity
        boss.peak_equity = self.starting_equity
        boss.day_start_equity = self.starting_equity

        equity_curve = []
        dates = []

        # Warm-up: need enough history for indicators
        warm = 60
        for i in range(warm, len(common_idx)):
            ts = common_idx[i]
            # Slice data up to current bar (inclusive)
            window = {}
            prices = {}
            for sym, df in market_data.items():
                w = df.loc[:ts].copy()
                if len(w) < 30:
                    continue
                window[sym] = w
                prices[sym] = float(w["close"].iloc[-1])

            if not window:
                continue

            # New day detection (simple)
            if i == warm or common_idx[i].date() != common_idx[i-1].date():
                boss.new_day()

            boss.run_cycle(window, prices)

            equity_curve.append(boss.equity)
            dates.append(ts)

        eq = pd.Series(equity_curve, index=dates, name="equity")
        return self._compute_stats(eq, boss.trades)

    def walk_forward(self, market_data: Dict[str, pd.DataFrame],
                     train_bars: int = 120,
                     test_bars: int = 40,
                     step_bars: int = 40) -> List[BacktestResult]:
        """
        Simple walk-forward:
        - Train window (currently just used for warm-up / stability)
        - Test window (out-of-sample)
        - Roll forward by step_bars
        """
        # Get common index
        common_idx = None
        for df in market_data.values():
            common_idx = df.index if common_idx is None else common_idx.intersection(df.index)
        common_idx = common_idx.sort_values()

        results = []
        start = 0
        while start + train_bars + test_bars <= len(common_idx):
            train_end = common_idx[start + train_bars - 1]
            test_start = common_idx[start + train_bars]
            test_end = common_idx[min(start + train_bars + test_bars - 1, len(common_idx)-1)]

            print(f"Walk-forward window: test {test_start.date()} → {test_end.date()}")

            # For this simple version we just run the test period
            # (agents are not re-optimized; you can add parameter search later)
            res = self.run(market_data, start=str(test_start.date()), end=str(test_end.date()))
            res.params = {
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date())
            }
            results.append(res)
            start += step_bars

        return results

    def _compute_stats(self, equity: pd.Series, trades: List[Trade]) -> BacktestResult:
        if equity.empty:
            return BacktestResult(equity, [], self.starting_equity, 0, 0, 0, 0, 0, 0)

        rets = equity.pct_change().dropna()
        total_ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100

        # Max drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak
        max_dd = dd.min() * 100

        # Sharpe (daily, assume 252)
        sharpe = 0.0
        if rets.std() > 0:
            sharpe = (rets.mean() / rets.std()) * np.sqrt(252)

        # Trade stats
        closed = [t for t in trades if t.exit_price is not None]
        n = len(closed)
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        win_rate = len(wins) / n * 100 if n else 0.0
        gross_profit = sum(t.pnl for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1e-9
        pf = gross_profit / gross_loss if gross_loss else 0.0

        return BacktestResult(
            equity_curve=equity,
            trades=trades,
            final_equity=float(equity.iloc[-1]),
            total_return_pct=round(total_ret, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe=round(sharpe, 2),
            win_rate=round(win_rate, 1),
            profit_factor=round(pf, 2),
            n_trades=n
        )


def run_quick_backtest(symbols: List[str] = None, period: str = "1y") -> BacktestResult:
    symbols = symbols or DEFAULT_UNIVERSE
    print(f"Fetching {period} data for {symbols}...")
    data = fetch_history(symbols, period=period, interval="1d")
    bt = Backtester()
    print("Running backtest...")
    result = bt.run(data)
    print("\n=== Backtest Results ===")
    print(f"Final equity   : ${result.final_equity:,.2f}")
    print(f"Total return   : {result.total_return_pct:.2f}%")
    print(f"Max drawdown   : {result.max_drawdown_pct:.2f}%")
    print(f"Sharpe (ann.)  : {result.sharpe:.2f}")
    print(f"Trades         : {result.n_trades}")
    print(f"Win rate       : {result.win_rate:.1f}%")
    print(f"Profit factor  : {result.profit_factor:.2f}")
    return result


if __name__ == "__main__":
    run_quick_backtest()
