"""
Base agent interface
"""

from abc import ABC, abstractmethod
from typing import Dict, List
import pandas as pd
from core.models import Signal


class BaseAgent(ABC):
    def __init__(self, agent_id: str, weight: float = 1.0):
        self.agent_id = agent_id
        self.weight = weight
        self.enabled = True

    @abstractmethod
    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        """
        Generate trading signals from the latest market data.
        market_data: {symbol: DataFrame with OHLCV columns}
        """
        pass

    def __repr__(self):
        status = "ON" if self.enabled else "OFF"
        return f"<{self.__class__.__name__} id={self.agent_id} weight={self.weight} [{status}]>"
