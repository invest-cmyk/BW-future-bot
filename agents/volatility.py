"""
Volatility regime agent – adjusts aggression based on ATR expansion/contraction
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from agents.base import BaseAgent
from core.models import Signal, Side


class VolatilityAgent(BaseAgent):
    """
    Detects volatility expansion and fades extreme moves or joins them
    depending on regime. Useful filter + opportunistic signals.
    """

    def __init__(self, agent_id: str = "vol_1", weight: float = 0.7,
                 atr_period: int = 14, lookback: int = 50):
        super().__init__(agent_id, weight)
        self.atr_period = atr_period
        self.lookback = lookback

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol, df in market_data.items():
            if len(df) < self.lookback + 10:
                continue

            high = df["high"]
            low = df["low"]
            close = df["close"]

            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(self.atr_period).mean()
            atr_pct = (atr / close).iloc[-1]
            atr_rank = atr.rank(pct=True).iloc[-1]  # 0-1 percentile

            # Recent return
            ret = close.pct_change(5).iloc[-1]

            conf = min(atr_rank * 1.1, 0.85) * self.weight

            # High volatility + strong directional move → momentum continuation bias
            if atr_rank > 0.75 and abs(ret) > 0.012:
                side = Side.LONG if ret > 0 else Side.SHORT
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=side,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=30,
                    target_ticks=45,
                    reason=f"Vol expansion (rank={atr_rank:.2f}) + direction"
                ))
            # Extreme low vol → potential breakout setup (we just note it, Boss can use)
            elif atr_rank < 0.20:
                # Low vol – no aggressive directional bet, just metadata signal
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.FLAT,
                    confidence=0.3,
                    size_contracts=0,
                    reason=f"Low volatility regime (rank={atr_rank:.2f})"
                ))
        return signals
