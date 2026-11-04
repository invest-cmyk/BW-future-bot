"""
Seasonality agent for futures.
Uses simple day-of-week and month-of-year historical tendencies.
"""

from typing import Dict, List
from datetime import datetime
import pandas as pd
from agents.base import BaseAgent
from core.models import Signal, Side


# Simplified historical seasonal biases (illustrative, not live research)
# Positive = historically bullish tendency
SEASONAL_MONTH = {
    "ES":  {1: 0.3, 2: 0.1, 3: 0.4, 4: 0.2, 5: -0.1, 6: -0.2, 7: 0.1, 8: -0.3, 9: -0.4, 10: 0.3, 11: 0.5, 12: 0.4},
    "NQ":  {1: 0.4, 2: 0.2, 3: 0.3, 4: 0.1, 5: -0.2, 6: -0.1, 7: 0.2, 8: -0.2, 9: -0.3, 10: 0.4, 11: 0.5, 12: 0.3},
    "CL":  {1: 0.2, 2: 0.3, 3: 0.1, 4: -0.1, 5: -0.2, 6: 0.1, 7: 0.3, 8: 0.2, 9: -0.3, 10: -0.1, 11: 0.1, 12: 0.2},
    "GC":  {1: 0.4, 2: 0.3, 3: 0.1, 4: -0.1, 5: -0.2, 6: -0.1, 7: 0.1, 8: 0.2, 9: 0.3, 10: 0.2, 11: 0.1, 12: 0.3},
}

DOW_BIAS = {  # 0=Mon ... 6=Sun
    "ES":  {0: 0.1, 1: 0.2, 2: 0.0, 3: -0.1, 4: 0.15},
    "NQ":  {0: 0.15, 1: 0.25, 2: 0.05, 3: -0.15, 4: 0.1},
    "CL":  {0: 0.1, 1: 0.05, 2: 0.0, 3: -0.05, 4: 0.1},
    "GC":  {0: 0.2, 1: 0.1, 2: 0.05, 3: 0.0, 4: 0.15},
}


class SeasonalityAgent(BaseAgent):
    """
    Lightweight seasonal bias agent.
    Does not generate strong standalone signals; provides mild directional lean
    that the Boss can combine with other agents.
    """

    def __init__(self, agent_id: str = "seasonality_1", weight: float = 0.45):
        super().__init__(agent_id, weight)

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        now = datetime.utcnow()
        month = now.month
        dow = now.weekday()

        for symbol in market_data.keys():
            month_bias = SEASONAL_MONTH.get(symbol, {}).get(month, 0.0)
            dow_bias = DOW_BIAS.get(symbol, {}).get(dow, 0.0)
            total = (month_bias + dow_bias) / 2.0

            if abs(total) < 0.15:
                continue

            conf = min(abs(total) * 1.5, 0.65) * self.weight
            side = Side.LONG if total > 0 else Side.SHORT

            signals.append(Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                side=side,
                confidence=conf,
                size_contracts=1,
                stop_ticks=22,
                target_ticks=35,
                reason=f"Seasonal bias {total:+.2f} (month={month}, dow={dow})"
            ))
        return signals
