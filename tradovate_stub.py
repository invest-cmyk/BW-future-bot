"""
Tradovate API stub (popular for futures paper & live).
Requires API key / secret from Tradovate.
"""

from typing import Dict, List, Optional
from brokers.base import BrokerBase
from core.models import Side, Position


class TradovateBroker(BrokerBase):
    """
    Skeleton for Tradovate.
    Docs: https://api.tradovate.com/
    Typical flow: authenticate → get access token → place orders on demo or live.
    """

    def __init__(self, username: str = "", password: str = "",
                 app_id: str = "", app_version: str = "1.0",
                 demo: bool = True):
        self.username = username
        self.password = password
        self.app_id = app_id
        self.app_version = app_version
        self.demo = demo
        self.base_url = "https://demo.tradovateapi.com/v1" if demo else "https://live.tradovateapi.com/v1"
        self.token = None

    def authenticate(self):
        raise NotImplementedError(
            "POST /auth/accesstokenrequest with username/password/appId. "
            "Store the accessToken for subsequent calls."
        )

    def get_account(self) -> dict:
        raise NotImplementedError

    def get_positions(self) -> Dict[str, Position]:
        raise NotImplementedError

    def place_order(self, symbol: str, side: Side, qty: int,
                    order_type: str = "MARKET",
                    limit_price: Optional[float] = None,
                    stop_price: Optional[float] = None) -> dict:
        raise NotImplementedError(
            "POST /order/placeorder with accountSpec, action (Buy/Sell), "
            "symbol, orderQty, orderType, etc."
        )

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    def get_open_orders(self) -> List[dict]:
        raise NotImplementedError
