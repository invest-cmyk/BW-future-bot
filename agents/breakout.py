"""
Breakout agent – classic Donchian / range breakout for futures
"""

from typing import Dict, List
import pandas as pd
from agents.base import BaseAgent
from core.models import Signal, Side


class BreakoutAgent(BaseAgent):
    """
    Donchian channel breakout.
    Strong on trending futures (indices, crude, gold).
    """

    def __init__(self, agent_id: str = "breakout_1", weight: float = 0.9,
                 channel: int = 20, atr_period: int = 14):
        super().__init__(agent_id, weight)
        self.channel = channel
        self.atr_period = atr_period

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol, df in market_data.items():
            if len(df) < max(self.channel, self.atr_period) + 5:
                continue

            high = df["high"]
            low = df["low"]
            close = df["close"]

            upper = high.rolling(self.channel).max().iloc[-2]  # previous bar
            lower = low.rolling(self.channel).min().iloc[-2]
            price = close.iloc[-1]

            # ATR for stop sizing
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(self.atr_period).mean().iloc[-1]

            conf = 0.75 * self.weight

            if price > upper:
                stop_ticks = max(12, int((atr * 1.2) / 0.25))  # rough for ES-like
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.LONG,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=stop_ticks,
                    target_ticks=stop_ticks * 2,
                    reason=f"Donchian breakout above {upper:.2f}"
                ))
            elif price < lower:
                stop_ticks = max(12, int((atr * 1.2) / 0.25))
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.SHORT,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=stop_ticks,
                    target_ticks=stop_ticks * 2,
                    reason=f"Donchian breakout below {lower:.2f}"
                ))
        return signals
