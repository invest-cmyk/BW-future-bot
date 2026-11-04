"""
Commitment of Traders (COT) style agent.
Uses a simplified proxy (commercial vs non-commercial positioning bias).
In production you would pull the official CFTC COT report weekly.
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from agents.base import BaseAgent
from core.models import Signal, Side


class COTAgent(BaseAgent):
    """
    Proxy COT agent.
    Real implementation should download the latest CFTC COT report.
    Here we create a deterministic pseudo-signal from recent price action
    + a mild mean-reversion of speculative positioning proxy.
    """

    def __init__(self, agent_id: str = "cot_1", weight: float = 0.55):
        super().__init__(agent_id, weight)

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol, df in market_data.items():
            if len(df) < 40:
                continue

            # Proxy: large speculative net position approximated by
            # recent cumulative return vs longer-term (crowded trade detection)
            close = df["close"]
            short_ret = close.pct_change(10).iloc[-1]
            long_ret = close.pct_change(40).iloc[-1]

            # When short-term has run far ahead of longer-term → crowded
            divergence = short_ret - long_ret

            # Fade extreme speculative positioning
            if divergence > 0.04:          # specs likely long and crowded
                conf = min(abs(divergence) * 8, 0.7) * self.weight
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.SHORT,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=28,
                    target_ticks=40,
                    reason=f"COT-proxy: crowded long (div={divergence:.2%})"
                ))
            elif divergence < -0.04:       # specs likely short and crowded
                conf = min(abs(divergence) * 8, 0.7) * self.weight
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=symbol,
                    side=Side.LONG,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=28,
                    target_ticks=40,
                    reason=f"COT-proxy: crowded short (div={divergence:.2%})"
                ))
        return signals
