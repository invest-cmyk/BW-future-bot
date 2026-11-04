"""
Data Collector Agent for Futures
================================
Gathers market data relevant to futures trading and delivers a structured
DataReport to the Boss every cycle (same pattern as News + Risk).

Collects:
  • Latest prices, volume, daily range
  • Volatility / ATR regime
  • Trend & momentum snapshot
  • Term-structure / roll proxy (when multi-expiry data available)
  • Open-interest proxy (volume-based when true OI unavailable)
  • Economic calendar highlights (static + weekday rules)
  • Contract specs reminder (multiplier, tick value, margin)
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import math

import pandas as pd
import numpy as np

from agents.base import BaseAgent
from core.models import Signal, Side
from config.settings import CONTRACTS


# ---------------------------------------------------------------------------
# Structured report delivered to the Boss
# ---------------------------------------------------------------------------
@dataclass
class SymbolSnapshot:
    symbol: str
    price: float
    change_pct: float          # vs prior bar
    volume: float
    volume_vs_avg: float       # vs 20-bar avg
    atr: float
    atr_pct: float             # ATR / price
    vol_regime: str            # LOW / NORMAL / HIGH
    trend: str                 # UP / DOWN / SIDEWAYS
    momentum_10: float         # 10-bar ROC
    high_20: float
    low_20: float
    position_in_range: float   # 0–1 (close location in 20-bar range)
    contango_proxy: Optional[float] = None   # positive = contango-ish
    notes: List[str] = field(default_factory=list)


@dataclass
class DataReport:
    timestamp: datetime
    symbols: List[str]
    snapshots: Dict[str, SymbolSnapshot]
    market_regime: str              # RISK_ON / RISK_OFF / MIXED / QUIET
    vol_environment: str            # LOW / NORMAL / HIGH
    upcoming_events: List[str]
    roll_notes: List[str]
    summary: str
    raw_bars_used: int = 0

    def pretty(self) -> str:
        lines = [
            f"📊 DATA REPORT  {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Market regime : {self.market_regime}  |  Vol: {self.vol_environment}",
            f"Summary       : {self.summary}",
            "",
        ]
        for sym, s in self.snapshots.items():
            lines.append(
                f"{sym}: {s.price:,.2f}  ({s.change_pct:+.2%})  "
                f"trend={s.trend}  mom10={s.momentum_10:+.2%}  "
                f"vol={s.vol_regime}  ATR%={s.atr_pct:.2%}  "
                f"vol×={s.volume_vs_avg:.1f}"
            )
            for n in s.notes[:2]:
                lines.append(f"     • {n}")
        if self.upcoming_events:
            lines.append("")
            lines.append("Calendar / events:")
            for e in self.upcoming_events[:5]:
                lines.append(f"  • {e}")
        if self.roll_notes:
            lines.append("")
            lines.append("Roll / structure:")
            for r in self.roll_notes:
                lines.append(f"  • {r}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "market_regime": self.market_regime,
            "vol_environment": self.vol_environment,
            "summary": self.summary,
            "symbols": {
                s: {
                    "price": snap.price,
                    "change_pct": round(snap.change_pct, 4),
                    "trend": snap.trend,
                    "vol_regime": snap.vol_regime,
                    "atr_pct": round(snap.atr_pct, 4),
                    "momentum_10": round(snap.momentum_10, 4),
                }
                for s, snap in self.snapshots.items()
            },
            "upcoming_events": self.upcoming_events,
            "roll_notes": self.roll_notes,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 2:
        return float("nan")
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _trend_label(close: pd.Series, fast: int = 20, slow: int = 50) -> str:
    if len(close) < slow + 2:
        return "SIDEWAYS"
    ma_f = close.rolling(fast).mean().iloc[-1]
    ma_s = close.rolling(slow).mean().iloc[-1]
    price = close.iloc[-1]
    if price > ma_f > ma_s:
        return "UP"
    if price < ma_f < ma_s:
        return "DOWN"
    return "SIDEWAYS"


def _vol_regime(atr_pct: float, history_atr_pct: pd.Series) -> str:
    if history_atr_pct is None or len(history_atr_pct.dropna()) < 20:
        if atr_pct < 0.008:
            return "LOW"
        if atr_pct > 0.020:
            return "HIGH"
        return "NORMAL"
    rank = (history_atr_pct.dropna() < atr_pct).mean()
    if rank < 0.25:
        return "LOW"
    if rank > 0.75:
        return "HIGH"
    return "NORMAL"


def _economic_calendar_notes(now: Optional[datetime] = None) -> List[str]:
    """
    Lightweight calendar awareness (no external API required).
    In production, replace with a real economic calendar feed.
    """
    now = now or datetime.now(timezone.utc)
    events = []
    # Weekday rules of thumb for US session
    if now.weekday() == 0:  # Monday
        events.append("Monday: often follow-through or gap-fill from Friday")
    if now.weekday() == 2:  # Wednesday
        events.append("Wednesday: typical FOMC / mid-week data window – watch vol")
    if now.weekday() == 4:  # Friday
        events.append("Friday: weekly closes, possible position squaring into weekend")
    # Month-end / quarter-end
    if now.day >= 28:
        events.append("Near month-end: possible rebalancing flows")
    if now.month in (3, 6, 9, 12) and now.day >= 20:
        events.append("Near quarter-end: institutional rebalancing risk")
    # First Friday of month often NFP (approximate)
    if now.weekday() == 4 and 1 <= now.day <= 7:
        events.append("First Friday window: Non-Farm Payrolls risk (US)")
    if not events:
        events.append("No major static calendar flag today – still watch scheduled data releases")
    return events


def _roll_notes(symbol: str, df: pd.DataFrame) -> List[str]:
    """
    Simple roll / structure notes.
    True term structure needs multiple expiries; we give practical reminders.
    """
    notes = []
    spec = CONTRACTS.get(symbol)
    if not spec:
        return notes
    notes.append(f"{symbol} ({spec.name}): mult=${spec.multiplier}, tick=${spec.tick_value}, "
                 f"day margin~${spec.margin_day:,.0f}")
    # Volume spike can mark roll activity
    if "volume" in df.columns and len(df) >= 25:
        vol = df["volume"]
        avg = vol.rolling(20).mean().iloc[-1]
        last = vol.iloc[-1]
        if avg and last > avg * 1.8:
            notes.append(f"{symbol}: elevated volume ({last/avg:.1f}× avg) – possible roll or event activity")
    return notes


# ---------------------------------------------------------------------------
# The Agent
# ---------------------------------------------------------------------------
class DataCollectorAgent(BaseAgent):
    """
    Collects futures market data → builds DataReport → reports to Boss.
    Optionally emits mild regime signals (Boss still decides).
    """

    def __init__(self, agent_id: str = "data_collector_1", weight: float = 0.4):
        super().__init__(agent_id, weight)
        self.last_report: Optional[DataReport] = None

    def build_report(self, market_data: Dict[str, pd.DataFrame]) -> DataReport:
        now = datetime.now(timezone.utc)
        snapshots: Dict[str, SymbolSnapshot] = {}
        trends = []
        vol_flags = []
        roll_notes: List[str] = []
        bars_used = 0

        for symbol, df in market_data.items():
            if df is None or len(df) < 25:
                continue
            df = df.copy()
            for col in ("open", "high", "low", "close"):
                if col not in df.columns:
                    continue
            close = df["close"]
            price = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) > 1 else price
            change = (price - prev) / prev if prev else 0.0

            volume = float(df["volume"].iloc[-1]) if "volume" in df.columns else 0.0
            vol_avg = float(df["volume"].rolling(20).mean().iloc[-1]) if "volume" in df.columns else 1.0
            vol_ratio = volume / vol_avg if vol_avg else 1.0

            atr = _atr(df, 14)
            atr_pct = atr / price if price and not math.isnan(atr) else 0.0

            # ATR% history for regime
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ], axis=1).max(axis=1)
            atr_series = (tr.rolling(14).mean() / close)
            vol_reg = _vol_regime(atr_pct, atr_series)

            trend = _trend_label(close)
            mom10 = float(close.pct_change(10).iloc[-1]) if len(close) > 10 else 0.0
            high20 = float(close.rolling(20).max().iloc[-1])
            low20 = float(close.rolling(20).min().iloc[-1])
            rng = high20 - low20
            pos_in_range = (price - low20) / rng if rng > 0 else 0.5

            notes = []
            if vol_ratio >= 1.8:
                notes.append(f"Volume surge {vol_ratio:.1f}× average")
            if vol_reg == "HIGH":
                notes.append("High volatility regime")
            if vol_reg == "LOW":
                notes.append("Compressed volatility – breakout risk")
            if abs(mom10) > 0.04:
                notes.append(f"Strong 10-bar momentum {mom10:+.1%}")
            if pos_in_range > 0.9:
                notes.append("Near 20-bar highs")
            if pos_in_range < 0.1:
                notes.append("Near 20-bar lows")

            snap = SymbolSnapshot(
                symbol=symbol,
                price=price,
                change_pct=change,
                volume=volume,
                volume_vs_avg=vol_ratio,
                atr=atr if not math.isnan(atr) else 0.0,
                atr_pct=atr_pct,
                vol_regime=vol_reg,
                trend=trend,
                momentum_10=mom10,
                high_20=high20,
                low_20=low20,
                position_in_range=pos_in_range,
                notes=notes,
            )
            snapshots[symbol] = snap
            trends.append(trend)
            vol_flags.append(vol_reg)
            roll_notes.extend(_roll_notes(symbol, df))
            bars_used = max(bars_used, len(df))

        # Market regime from trends
        up = trends.count("UP")
        down = trends.count("DOWN")
        if up >= 2 and down == 0:
            market_regime = "RISK_ON"
        elif down >= 2 and up == 0:
            market_regime = "RISK_OFF"
        elif not trends:
            market_regime = "QUIET"
        else:
            market_regime = "MIXED"

        high_vol = vol_flags.count("HIGH")
        low_vol = vol_flags.count("LOW")
        if high_vol >= 2:
            vol_env = "HIGH"
        elif low_vol >= 2:
            vol_env = "LOW"
        else:
            vol_env = "NORMAL"

        events = _economic_calendar_notes(now)

        # Summary line
        parts = [f"{market_regime} tape", f"{vol_env} volatility"]
        movers = sorted(snapshots.values(), key=lambda s: abs(s.change_pct), reverse=True)
        if movers:
            top = movers[0]
            parts.append(f"leader {top.symbol} {top.change_pct:+.2%}")
        summary = " | ".join(parts)

        report = DataReport(
            timestamp=now,
            symbols=list(snapshots.keys()),
            snapshots=snapshots,
            market_regime=market_regime,
            vol_environment=vol_env,
            upcoming_events=events,
            roll_notes=roll_notes,
            summary=summary,
            raw_bars_used=bars_used,
        )
        self.last_report = report
        return report

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        report = self.build_report(market_data)
        print("\n" + report.pretty() + "\n")

        # Mild regime-based signals (Boss + Risk still have final say)
        signals: List[Signal] = []
        for sym, snap in report.snapshots.items():
            # Prefer trend-aligned mild bias when vol not extreme
            if snap.vol_regime == "HIGH":
                continue  # let other agents handle chaotic tape
            if snap.trend == "UP" and snap.momentum_10 > 0.015:
                conf = min(0.35 + abs(snap.momentum_10) * 2, 0.55) * self.weight
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=sym,
                    side=Side.LONG,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=22,
                    target_ticks=35,
                    reason=f"Data regime UP + mom {snap.momentum_10:+.2%} | {snap.vol_regime} vol",
                    metadata={"data_report": True, "market_regime": report.market_regime},
                ))
            elif snap.trend == "DOWN" and snap.momentum_10 < -0.015:
                conf = min(0.35 + abs(snap.momentum_10) * 2, 0.55) * self.weight
                signals.append(Signal(
                    agent_id=self.agent_id,
                    symbol=sym,
                    side=Side.SHORT,
                    confidence=conf,
                    size_contracts=1,
                    stop_ticks=22,
                    target_ticks=35,
                    reason=f"Data regime DOWN + mom {snap.momentum_10:+.2%} | {snap.vol_regime} vol",
                    metadata={"data_report": True, "market_regime": report.market_regime},
                ))
        return signals

    def get_last_report(self) -> Optional[DataReport]:
        return self.last_report
