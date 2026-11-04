"""
Market data helpers for futures.
Uses yfinance continuous contracts where possible.
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Yahoo Finance futures symbols (continuous)
YF_MAP = {
    "ES": "ES=F",
    "NQ": "NQ=F",
    "YM": "YM=F",
    "RTY": "RTY=F",
    "CL": "CL=F",
    "GC": "GC=F",
    "SI": "SI=F",
    "6E": "6E=F",
    "ZB": "ZB=F",
    "ZN": "ZN=F",
}


def fetch_history(symbols: List[str], period: str = "6mo", interval: str = "1d") -> Dict[str, pd.DataFrame]:
    """
    Fetch historical data. Falls back to synthetic data if yfinance unavailable.
    """
    try:
        import yfinance as yf
        data = {}
        for sym in symbols:
            yf_sym = YF_MAP.get(sym, f"{sym}=F")
            df = yf.download(yf_sym, period=period, interval=interval, progress=False, auto_adjust=True)
            if df.empty:
                print(f"⚠️  No data for {sym}, generating synthetic")
                data[sym] = _synthetic(sym, days=120)
            else:
                df = df.rename(columns=str.lower)
                # Handle multi-index columns from yfinance
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                data[sym] = df[["open", "high", "low", "close", "volume"]].dropna()
        return data
    except Exception as e:
        print(f"yfinance unavailable ({e}). Using synthetic data.")
        return {sym: _synthetic(sym, days=120) for sym in symbols}


def _synthetic(symbol: str, days: int = 120, start_price: float = None) -> pd.DataFrame:
    """Generate realistic random-walk futures data for testing"""
    np.random.seed(hash(symbol) % 2**32)
    if start_price is None:
        defaults = {"ES": 5200, "NQ": 18500, "CL": 75, "GC": 2350, "YM": 40000}
        start_price = defaults.get(symbol, 1000)

    dates = pd.date_range(end=datetime.utcnow(), periods=days, freq="B")
    returns = np.random.normal(0.0003, 0.012, days)
    # mild trend + mean reversion component
    prices = start_price * np.cumprod(1 + returns)

    df = pd.DataFrame(index=dates)
    df["close"] = prices
    df["open"] = df["close"].shift(1).fillna(start_price)
    df["high"] = df[["open", "close"]].max(axis=1) * (1 + np.abs(np.random.normal(0, 0.004, days)))
    df["low"] = df[["open", "close"]].min(axis=1) * (1 - np.abs(np.random.normal(0, 0.004, days)))
    df["volume"] = np.random.randint(50_000, 400_000, days)
    return df


def latest_prices(market_data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
    return {sym: float(df["close"].iloc[-1]) for sym, df in market_data.items()}
