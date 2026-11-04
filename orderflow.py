"""
Simple order-flow / volume-pressure proxy agent.
Real order-flow needs tick/DOM data. This uses volume + candle structure as a stand-in.
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from agents.base import BaseAgent
from core.models import Signal, Side


class OrderFlowAgent(BaseAgent):
    def __init__(self, agent_id: str = "orderflow_1", weight: float = 0.6):
        super().__init__(agent_id, weight)

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol, df in market_data.items():
            if len(df) < 30 or "volume" not in df.columns:
                continue

            recent = df.iloc[-8:]
            vol_ma = df["volume"].rolling(20).mean().iloc[-1]
            curr_vol = recent["volume"].mean()

            # Volume surge
            vol_ratio = curr_vol / vol_ma if vol_ma > 0 else 1.0

            # Directional pressure: close location in range
            body = recent["close"] - recent["open"]
            range_ = recent["high"] - recent["low"]
            pressure = (body / range_.replace(0, np.nan)).mean()

            if vol_ratio < 1.3 or abs(pressure) < 0.25:
                continue

            conf = min((vol_ratio - 1) * 0.6 + abs(pressure), 0.8) * self.weight
            side = Side.LONG if pressure > 0 else Side.SHORT

            signals.append(Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                side=side,
                confidence=conf,
                size_contracts=1,
                stop_ticks=18,
                target_ticks=32,
                reason=f"Orderflow proxy vol_ratio={vol_ratio:.2f} pressure={pressure:.2f}"
            ))
        return signals
