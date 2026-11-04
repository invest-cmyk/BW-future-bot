"""
News / LLM sentiment agent (placeholder).
In production: feed headlines into an LLM or a dedicated sentiment model.
Here we use a simple keyword-based mock so the system runs offline.
"""

from typing import Dict, List
import pandas as pd
from agents.base import BaseAgent
from core.models import Signal, Side


# Mock recent headlines for demo (replace with real news API + LLM)
MOCK_HEADLINES = {
    "ES": [
        "Fed officials signal patience on further cuts",
        "Soft landing narrative gains traction among strategists",
        "Equity futures steady ahead of key data",
    ],
    "NQ": [
        "Mega-cap tech leads overnight gains",
        "AI spending remains robust according to cloud providers",
        "Nasdaq futures supported by semiconductor strength",
    ],
    "CL": [
        "OPEC+ maintains production stance",
        "Inventory draw smaller than expected",
        "Geopolitical premium remains elevated",
    ],
    "GC": [
        "Safe-haven demand supports gold",
        "Real yields edge lower, bullish for bullion",
        "Central bank buying continues in Asia",
    ],
}

BULLISH_KEYWORDS = {"gains", "strength", "supported", "bullish", "soft landing", "robust", "demand", "buying"}
BEARISH_KEYWORDS = {"cuts", "draw", "elevated", "patience", "risk", "weak", "selloff", "pressure"}


class NewsLLMAgent(BaseAgent):
    """
    Lightweight news sentiment proxy.
    Replace `get_headlines` + scoring with a real LLM call for production.
    """

    def __init__(self, agent_id: str = "news_llm_1", weight: float = 0.5):
        super().__init__(agent_id, weight)

    def get_headlines(self, symbol: str) -> List[str]:
        return MOCK_HEADLINES.get(symbol, [])

    def score_text(self, text: str) -> float:
        text = text.lower()
        score = 0.0
        for w in BULLISH_KEYWORDS:
            if w in text:
                score += 0.25
        for w in BEARISH_KEYWORDS:
            if w in text:
                score -= 0.25
        return max(min(score, 1.0), -1.0)

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals = []
        for symbol in market_data.keys():
            headlines = self.get_headlines(symbol)
            if not headlines:
                continue

            scores = [self.score_text(h) for h in headlines]
            avg = sum(scores) / len(scores)

            if abs(avg) < 0.15:
                continue

            conf = min(abs(avg) * 1.4, 0.7) * self.weight
            side = Side.LONG if avg > 0 else Side.SHORT

            signals.append(Signal(
                agent_id=self.agent_id,
                symbol=symbol,
                side=side,
                confidence=conf,
                size_contracts=1,
                stop_ticks=20,
                target_ticks=35,
                reason=f"News sentiment {avg:+.2f} from {len(headlines)} headlines"
            ))
        return signals
