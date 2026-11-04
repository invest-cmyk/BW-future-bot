"""
Abstract broker interface.
All concrete brokers (Paper, IBKR, Tradovate, etc.) implement this.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from core.models import Side, Position, Trade


class BrokerBase(ABC):
    @abstractmethod
    def get_account(self) -> dict:
        """Return equity, cash, buying power, etc."""
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        pass

    @abstractmethod
    def place_order(self, symbol: str, side: Side, qty: int,
                    order_type: str = "MARKET",
                    limit_price: Optional[float] = None,
                    stop_price: Optional[float] = None) -> dict:
        """Place an order. Returns order id / status dict."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    def get_open_orders(self) -> List[dict]:
        pass

    def flatten(self, symbol: str) -> dict:
        """Convenience: close entire position in symbol."""
        positions = self.get_positions()
        pos = positions.get(symbol)
        if not pos or pos.qty == 0:
            return {"status": "flat"}
        close_side = Side.SHORT if pos.side == Side.LONG else Side.LONG
        return self.place_order(symbol, close_side, pos.qty)
