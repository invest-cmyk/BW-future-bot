"""
Futures Autopilot Configuration
"""

from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class ContractSpec:
    symbol: str                  # e.g. "ES"
    name: str
    exchange: str
    multiplier: float            # $ per point
    tick_size: float
    tick_value: float            # multiplier * tick_size
    margin_day: float            # approximate day trading margin
    margin_overnight: float
    currency: str = "USD"

# Common liquid futures contracts
CONTRACTS: Dict[str, ContractSpec] = {
    "ES": ContractSpec("ES", "E-mini S&P 500", "CME", 50.0, 0.25, 12.50, 12000, 15000),
    "NQ": ContractSpec("NQ", "E-mini Nasdaq-100", "CME", 20.0, 0.25, 5.00, 16000, 20000),
    "YM": ContractSpec("YM", "E-mini Dow", "CBOT", 5.0, 1.0, 5.00, 8000, 10000),
    "RTY": ContractSpec("RTY", "E-mini Russell 2000", "CME", 50.0, 0.10, 5.00, 7000, 9000),
    "CL": ContractSpec("CL", "Crude Oil", "NYMEX", 1000.0, 0.01, 10.00, 6000, 8000),
    "GC": ContractSpec("GC", "Gold", "COMEX", 100.0, 0.10, 10.00, 9000, 11000),
    "SI": ContractSpec("SI", "Silver", "COMEX", 5000.0, 0.005, 25.00, 11000, 14000),
    "6E": ContractSpec("6E", "Euro FX", "CME", 125000.0, 0.00005, 6.25, 2500, 3500),
    "ZB": ContractSpec("ZB", "30-Year T-Bond", "CBOT", 1000.0, 1/32, 31.25, 4000, 5500),
    "ZN": ContractSpec("ZN", "10-Year T-Note", "CBOT", 1000.0, 1/64, 15.625, 1500, 2200),
}

# Default universe the system will trade
DEFAULT_UNIVERSE: List[str] = ["ES", "NQ", "CL", "GC"]

# Risk parameters (Boss + RiskAgent)
RISK = {
    "max_risk_per_trade_pct": 0.01,      # 1% of equity per trade
    "max_portfolio_heat": 0.06,          # max 6% total open risk
    "max_contracts_per_symbol": 4,
    "max_daily_loss_pct": 0.03,          # stop trading for the day if -3%
    "max_drawdown_pct": 0.10,            # pause system at -10% from peak
    "default_stop_ticks": 20,            # initial stop distance in ticks
}

# Simulation / paper settings
SIM = {
    "starting_equity": 100_000.0,
    "commission_per_side": 2.50,         # realistic round-turn ~$5
    "slippage_ticks": 1,
}

# Agent weights (Boss can override dynamically later)
AGENT_WEIGHTS = {
    "momentum": 1.0,
    "mean_reversion": 0.8,
    "breakout": 0.9,
    "volatility": 0.7,
}
