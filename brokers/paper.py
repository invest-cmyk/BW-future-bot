"""
Fully functional paper / simulation broker.
Tracks positions, cash, commissions, slippage.
"""

from typing import Dict, List, Optional
from datetime import datetime
import uuid
from brokers.base import BrokerBase
from core.models import Side, Position, Trade
from config.settings import CONTRACTS, SIM


class PaperBroker(BrokerBase):
    def __init__(self, starting_equity: float = None):
        self.equity = starting_equity or SIM["starting_equity"]
        self.cash = self.equity
        self.positions: Dict[str, Position] = {}
        self.orders: List[dict] = []
        self.trades: List[Trade] = []
        self.commission = SIM["commission_per_side"]
        self.slippage_ticks = SIM["slippage_ticks"]
        self._prices: Dict[str, float] = {}

    def update_prices(self, prices: Dict[str, float]):
        self._prices = prices
        self._mark_to_market()

    def get_account(self) -> dict:
        self._mark_to_market()
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "unrealized_pnl": round(self.equity - self.cash, 2),
            "open_positions": sum(1 for p in self.positions.values() if p.qty > 0),
        }

    def get_positions(self) -> Dict[str, Position]:
        return {s: p for s, p in self.positions.items() if p.qty > 0}

    def place_order(self, symbol: str, side: Side, qty: int,
                    order_type: str = "MARKET",
                    limit_price: Optional[float] = None,
                    stop_price: Optional[float] = None) -> dict:
        if qty <= 0:
            return {"status": "rejected", "reason": "qty <= 0"}

        price = self._prices.get(symbol)
        if price is None:
            return {"status": "rejected", "reason": f"no price for {symbol}"}

        spec = CONTRACTS.get(symbol)
        if not spec:
            return {"status": "rejected", "reason": f"unknown contract {symbol}"}

        # Slippage
        slip = self.slippage_ticks * spec.tick_size
        fill = price + slip if side == Side.LONG else price - slip

        commission = self.commission * qty
        order_id = str(uuid.uuid4())[:8]

        existing = self.positions.get(symbol)

        # Opposite side → reduce / close
        if existing and existing.side != side and existing.qty > 0:
            close_qty = min(qty, existing.qty)
            points = (fill - existing.avg_price) if existing.side == Side.LONG else (existing.avg_price - fill)
            pnl = points * spec.multiplier * close_qty - commission
            self.cash += pnl

            self.trades.append(Trade(
                trade_id=order_id,
                symbol=symbol,
                side=existing.side,
                qty=close_qty,
                entry_price=existing.avg_price,
                exit_price=fill,
                entry_time=existing.entry_time,
                exit_time=datetime.utcnow(),
                pnl=pnl,
                commission=commission
            ))

            existing.qty -= close_qty
            if existing.qty == 0:
                existing.side = Side.FLAT
            qty -= close_qty
            if qty <= 0:
                return {"status": "filled", "order_id": order_id, "fill_price": fill, "pnl": pnl}

        # Open / add
        if qty > 0:
            if existing and existing.side == side and existing.qty > 0:
                total = existing.qty + qty
                existing.avg_price = (existing.avg_price * existing.qty + fill * qty) / total
                existing.qty = total
            else:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    avg_price=fill,
                    entry_time=datetime.utcnow()
                )
            self.cash -= commission
            self.trades.append(Trade(
                trade_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                entry_price=fill,
                commission=commission
            ))

        self.orders.append({
            "order_id": order_id,
            "symbol": symbol,
            "side": side.value,
            "qty": qty,
            "fill_price": fill,
            "status": "filled",
            "time": datetime.utcnow().isoformat()
        })
        return {"status": "filled", "order_id": order_id, "fill_price": fill}

    def cancel_order(self, order_id: str) -> bool:
        # Paper broker fills immediately → nothing to cancel
        return False

    def get_open_orders(self) -> List[dict]:
        return []

    def _mark_to_market(self):
        unrealized = 0.0
        for sym, pos in self.positions.items():
            if pos.qty == 0:
                continue
            price = self._prices.get(sym, pos.avg_price)
            spec = CONTRACTS.get(sym)
            if not spec:
                continue
            points = (price - pos.avg_price) if pos.side == Side.LONG else (pos.avg_price - price)
            pos.unrealized_pnl = points * spec.multiplier * pos.qty
            unrealized += pos.unrealized_pnl
        self.equity = self.cash + unrealized
