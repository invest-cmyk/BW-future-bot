"""
Interactive Brokers (IBKR) stub.
Requires ib_insync + TWS / IB Gateway running with API enabled.
This is a skeleton so you can plug in your credentials later.
"""

from typing import Dict, List, Optional
from brokers.base import BrokerBase
from core.models import Side, Position


class IBKRBroker(BrokerBase):
    """
    Skeleton for Interactive Brokers.
    Install: pip install ib_insync
    Then connect to TWS or IB Gateway (paper or live).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        self.host = host
        self.port = port
        self.client_id = client_id
        self._connected = False
        # self.ib = IB()  # uncomment when ib_insync installed

    def connect(self):
        raise NotImplementedError(
            "Install ib_insync and uncomment connection code. "
            "Example:\n"
            "  from ib_insync import IB\n"
            "  self.ib = IB()\n"
            "  self.ib.connect(self.host, self.port, clientId=self.client_id)"
        )

    def get_account(self) -> dict:
        raise NotImplementedError("Connect first")

    def get_positions(self) -> Dict[str, Position]:
        raise NotImplementedError("Connect first")

    def place_order(self, symbol: str, side: Side, qty: int,
                    order_type: str = "MARKET",
                    limit_price: Optional[float] = None,
                    stop_price: Optional[float] = None) -> dict:
        raise NotImplementedError(
            "Map futures symbol to IB Contract (e.g. ContFuture('ES', 'CME')) "
            "and use self.ib.placeOrder(...)"
        )

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    def get_open_orders(self) -> List[dict]:
        raise NotImplementedError
