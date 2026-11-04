"""
Mean-reversion agent for futures (especially useful on range-bound sessions)
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from agents.base import BaseAgent
from core.models import Signal, Side


class MeanReversionAgent(BaseAgent):
    """
    Z-score mean reversion on short lookback.
    Better on quieter sessions or mean-reverting products (bonds, some FX).
    """

    def __init__(self, agent_id: str = "meanrev_1", weight: float = 0.8,
                 lookback: int = 20, entry_z: float = 1.8, exit_z: float = 0.4):
        super().__init__(agent_id, weight)
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol, df in market_data.items():
            if len(df) < self.lookback + 5:
                continue

            close = df["close"]
            ma = close.rolling(self.lookback).mean()
            std = close.rolling(self.lookback).std()
            z = ((close - ma) / std).iloc[-1]

            if np.isnan(z):
                continue

            conf = min(abs(z) / 3.0, 0.9) * self.weight

            if z <= -self.entry_z:
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.LONG,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=18,
                    target_ticks=30,
                    reason=f"Mean-rev z={z:.2f} (oversold)"
                ))
            elif z >= self.entry_z:
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.SHORT,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=18,
                    target_ticks=30,
                    reason=f"Mean-rev z={z:.2f} (overbought)"
                ))
        return signals
