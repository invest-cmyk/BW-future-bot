"""
Momentum / Trend following agent for futures
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from agents.base import BaseAgent
from core.models import Signal, Side


class MomentumAgent(BaseAgent):
    """
    Classic trend-following using rate-of-change + moving average filter.
    Works well on index futures (ES, NQ) and energy.
    """

    def __init__(self, agent_id: str = "momentum_1", weight: float = 1.0,
                 lookback: int = 14, ma_period: int = 50, threshold: float = 0.008):
        super().__init__(agent_id, weight)
        self.lookback = lookback
        self.ma_period = ma_period
        self.threshold = threshold

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol, df in market_data.items():
            if len(df) < max(self.lookback, self.ma_period) + 5:
                continue

            close = df["close"]
            roc = close.pct_change(self.lookback).iloc[-1]
            ma = close.rolling(self.ma_period).mean().iloc[-1]
            price = close.iloc[-1]

            # Trend filter
            above_ma = price > ma
            below_ma = price < ma

            conf = min(abs(roc) / 0.03, 0.95) * self.weight

            if roc > self.threshold and above_ma:
                size = 1 if conf < 0.6 else 2
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.LONG,
                    confidence=conf,
                    size_contracts=size,
                    stop_ticks=25,
                    target_ticks=50,
                    reason=f"Momentum ROC={roc:.2%} + above MA{self.ma_period}"
                ))
            elif roc < -self.threshold and below_ma:
                size = 1 if conf < 0.6 else 2
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.SHORT,
                    confidence=conf,
                    size_contracts=size,
                    stop_ticks=25,
                    target_ticks=50,
                    reason=f"Momentum ROC={roc:.2%} + below MA{self.ma_period}"
                ))
        return signals
