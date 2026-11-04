"""
Core data models for the futures multi-agent system
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass
class Signal:
    """Proposal from a strategy agent to the Boss"""
    agent_id: str
    symbol: str
    side: Side
    confidence: float              # 0.0 – 1.0
    size_contracts: int            # suggested number of contracts
    stop_ticks: Optional[int] = None
    target_ticks: Optional[int] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class Position:
    symbol: str
    side: Side
    qty: int                       # number of contracts
    avg_price: float
    entry_time: datetime
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class Trade:
    trade_id: str
    symbol: str
    side: Side
    qty: int
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: datetime = field(default_factory=datetime.utcnow)
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    commission: float = 0.0
    agent_id: str = ""
    reason: str = ""


@dataclass
class MarketBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
