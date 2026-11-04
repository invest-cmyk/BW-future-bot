"""
Setup Agent – multi-factor confluence detector for futures
=========================================================
Looks for clean, rule-based trade setups and reports them to the Boss
as a structured SetupReport (not just a raw directional vote).

Setup types:
  1. Trend pullback (with MA + structure)
  2. Breakout + hold / retest proxy
  3. Range fade (mean-reversion at extremes)
  4. Volatility squeeze → expansion bias

Each setup is graded A / B / C from confluence score.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import pandas as pd
import numpy as np

from agents.base import BaseAgent
from core.models import Signal, Side
from config.settings import CONTRACTS, RISK


class SetupType(str, Enum):
    TREND_PULLBACK = "TREND_PULLBACK"
    BREAKOUT_HOLD = "BREAKOUT_HOLD"
    RANGE_FADE = "RANGE_FADE"
    VOL_SQUEEZE = "VOL_SQUEEZE"


class SetupGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


@dataclass
class TradeSetup:
    symbol: str
    setup_type: SetupType
    side: Side
    grade: SetupGrade
    entry: float
    stop: float
    target: float
    risk_ticks: int
    reward_ticks: int
    rr: float                      # reward / risk
    confluence_score: float        # 0–1
    reasons: List[str] = field(default_factory=list)
    invalidation: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def pretty_line(self) -> str:
        return (
            f"{self.grade.value} | {self.side.value:5} {self.symbol} "
            f"{self.setup_type.value:16} entry={self.entry:.2f} "
            f"stop={self.stop:.2f} tgt={self.target:.2f} "
            f"R:R={self.rr:.1f} score={self.confluence_score:.2f}"
        )


@dataclass
class SetupReport:
    timestamp: datetime
    setups: List[TradeSetup]
    scanned_symbols: List[str]
    summary: str

    def pretty(self) -> str:
        lines = [
            f"🎯 SETUP REPORT  {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Scanned: {', '.join(self.scanned_symbols)}  |  Found: {len(self.setups)} setup(s)",
            f"Summary: {self.summary}",
            "",
        ]
        if not self.setups:
            lines.append("  (no clean setups this cycle)")
        for s in self.setups:
            lines.append(f"  {s.pretty_line()}")
            for r in s.reasons[:4]:
                lines.append(f"      • {r}")
            if s.invalidation:
                lines.append(f"      ✗ Invalidation: {s.invalidation}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "count": len(self.setups),
            "summary": self.summary,
            "setups": [
                {
                    "symbol": s.symbol,
                    "type": s.setup_type.value,
                    "side": s.side.value,
                    "grade": s.grade.value,
                    "entry": s.entry,
                    "stop": s.stop,
                    "target": s.target,
                    "rr": s.rr,
                    "score": s.confluence_score,
                    "reasons": s.reasons,
                }
                for s in self.setups
            ],
        }


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _tick_size(symbol: str) -> float:
    spec = CONTRACTS.get(symbol)
    return spec.tick_size if spec else 0.25


def _grade(score: float) -> SetupGrade:
    if score >= 0.75:
        return SetupGrade.A
    if score >= 0.55:
        return SetupGrade.B
    return SetupGrade.C


class SetupAgent(BaseAgent):
    """
    Multi-factor setup hunter.
    Only emits signals for Grade A/B setups; always builds SetupReport for Boss.
    """

    def __init__(self, agent_id: str = "setup_1", weight: float = 0.95,
                 min_grade: str = "B"):
        super().__init__(agent_id, weight)
        self.min_grade = min_grade  # "A", "B", or "C"
        self.last_report: Optional[SetupReport] = None

    def _allowed(self, grade: SetupGrade) -> bool:
        order = {"A": 3, "B": 2, "C": 1}
        return order.get(grade.value, 0) >= order.get(self.min_grade, 2)

    # ------------------------------------------------------------------
    def scan_symbol(self, symbol: str, df: pd.DataFrame) -> List[TradeSetup]:
        if len(df) < 55:
            return []
        setups: List[TradeSetup] = []
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)

        price = float(close.iloc[-1])
        atr = _atr(df, 14)
        if atr <= 0 or np.isnan(atr):
            return []
        tick = _tick_size(symbol)

        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])
        roc10 = float(close.pct_change(10).iloc[-1])
        vol_ma = float(volume.rolling(20).mean().iloc[-1]) or 1.0
        vol_ratio = float(volume.iloc[-1]) / vol_ma

        # Structure
        swing_high = float(high.rolling(10).max().iloc[-2])
        swing_low = float(low.rolling(10).min().iloc[-2])
        donch_high = float(high.rolling(20).max().iloc[-2])
        donch_low = float(low.rolling(20).min().iloc[-2])

        # ATR percentile-ish for squeeze
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_series = tr.rolling(14).mean()
        atr_rank = float((atr_series.dropna() < atr).mean()) if len(atr_series.dropna()) > 20 else 0.5

        # ---------- 1) Trend pullback ----------
        uptrend = price > ma20 > ma50 and roc10 > 0
        downtrend = price < ma20 < ma50 and roc10 < 0
        # Pullback: price near MA20 after trend
        dist_ma20 = abs(price - ma20) / atr

        if uptrend and dist_ma20 < 1.2:
            score = 0.45
            reasons = ["Uptrend: price > MA20 > MA50", f"Pullback near MA20 (dist {dist_ma20:.1f} ATR)"]
            if roc10 > 0.01:
                score += 0.12
                reasons.append(f"Positive momentum ROC10={roc10:+.2%}")
            if vol_ratio < 1.1:
                score += 0.10
                reasons.append("Volume not elevated on pullback (healthy)")
            if price > swing_low:
                score += 0.10
                reasons.append("Holding above recent swing low")
            if atr_rank < 0.4:
                score += 0.08
                reasons.append("Vol not extreme – cleaner pullback")

            stop = price - max(1.2 * atr, 8 * tick)
            target = price + max(2.0 * atr, 16 * tick)
            risk_ticks = max(1, int(round((price - stop) / tick)))
            reward_ticks = max(1, int(round((target - price) / tick)))
            rr = reward_ticks / risk_ticks
            if rr >= 1.5:
                score += 0.08
                reasons.append(f"R:R {rr:.1f}")
            grade = _grade(score)
            setups.append(TradeSetup(
                symbol=symbol,
                setup_type=SetupType.TREND_PULLBACK,
                side=Side.LONG,
                grade=grade,
                entry=round(price, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
                rr=round(rr, 2),
                confluence_score=round(min(score, 0.98), 2),
                reasons=reasons,
                invalidation=f"Close below {stop:.2f} or MA50 break",
            ))

        if downtrend and dist_ma20 < 1.2:
            score = 0.45
            reasons = ["Downtrend: price < MA20 < MA50", f"Pullback near MA20 (dist {dist_ma20:.1f} ATR)"]
            if roc10 < -0.01:
                score += 0.12
                reasons.append(f"Negative momentum ROC10={roc10:+.2%}")
            if vol_ratio < 1.1:
                score += 0.10
                reasons.append("Volume not elevated on pullback")
            if price < swing_high:
                score += 0.10
                reasons.append("Holding below recent swing high")
            if atr_rank < 0.4:
                score += 0.08
                reasons.append("Vol not extreme")

            stop = price + max(1.2 * atr, 8 * tick)
            target = price - max(2.0 * atr, 16 * tick)
            risk_ticks = max(1, int(round((stop - price) / tick)))
            reward_ticks = max(1, int(round((price - target) / tick)))
            rr = reward_ticks / risk_ticks
            if rr >= 1.5:
                score += 0.08
                reasons.append(f"R:R {rr:.1f}")
            grade = _grade(score)
            setups.append(TradeSetup(
                symbol=symbol,
                setup_type=SetupType.TREND_PULLBACK,
                side=Side.SHORT,
                grade=grade,
                entry=round(price, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
                rr=round(rr, 2),
                confluence_score=round(min(score, 0.98), 2),
                reasons=reasons,
                invalidation=f"Close above {stop:.2f} or MA50 break",
            ))

        # ---------- 2) Breakout hold (price beyond prior Donchian, holding) ----------
        if price > donch_high and close.iloc[-2] <= donch_high:
            score = 0.50
            reasons = [f"Breakout above 20-bar high {donch_high:.2f}"]
            if vol_ratio >= 1.3:
                score += 0.15
                reasons.append(f"Volume confirmation {vol_ratio:.1f}×")
            if price > ma20:
                score += 0.10
                reasons.append("Breakout above MA20")
            if roc10 > 0:
                score += 0.08
                reasons.append("Momentum aligned")
            stop = min(donch_high, price - 1.0 * atr)
            target = price + 2.0 * atr
            risk_ticks = max(1, int(round((price - stop) / tick)))
            reward_ticks = max(1, int(round((target - price) / tick)))
            rr = reward_ticks / risk_ticks
            grade = _grade(score)
            setups.append(TradeSetup(
                symbol=symbol,
                setup_type=SetupType.BREAKOUT_HOLD,
                side=Side.LONG,
                grade=grade,
                entry=round(price, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
                rr=round(rr, 2),
                confluence_score=round(min(score, 0.98), 2),
                reasons=reasons,
                invalidation=f"Close back inside range below {donch_high:.2f}",
            ))

        if price < donch_low and close.iloc[-2] >= donch_low:
            score = 0.50
            reasons = [f"Breakout below 20-bar low {donch_low:.2f}"]
            if vol_ratio >= 1.3:
                score += 0.15
                reasons.append(f"Volume confirmation {vol_ratio:.1f}×")
            if price < ma20:
                score += 0.10
                reasons.append("Breakout below MA20")
            if roc10 < 0:
                score += 0.08
                reasons.append("Momentum aligned")
            stop = max(donch_low, price + 1.0 * atr)
            target = price - 2.0 * atr
            risk_ticks = max(1, int(round((stop - price) / tick)))
            reward_ticks = max(1, int(round((price - target) / tick)))
            rr = reward_ticks / risk_ticks
            grade = _grade(score)
            setups.append(TradeSetup(
                symbol=symbol,
                setup_type=SetupType.BREAKOUT_HOLD,
                side=Side.SHORT,
                grade=grade,
                entry=round(price, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
                rr=round(rr, 2),
                confluence_score=round(min(score, 0.98), 2),
                reasons=reasons,
                invalidation=f"Close back inside range above {donch_low:.2f}",
            ))

        # ---------- 3) Range fade (mean reversion at extremes) ----------
        range_high = float(high.rolling(20).max().iloc[-1])
        range_low = float(low.rolling(20).min().iloc[-1])
        mid = (range_high + range_low) / 2
        width = range_high - range_low
        if width > 0:
            loc = (price - range_low) / width
            # Fade only in non-strong-trend / elevated stretch
            if loc >= 0.92 and not uptrend:
                score = 0.42
                reasons = [f"At top of 20-bar range ({loc:.0%})", "Fade bias (no strong uptrend)"]
                if vol_ratio > 1.2:
                    score += 0.10
                    reasons.append("Volume at extreme")
                if atr_rank > 0.5:
                    score += 0.08
                    reasons.append("Volatility supports mean-reversion risk")
                stop = price + 0.9 * atr
                target = mid
                risk_ticks = max(1, int(round((stop - price) / tick)))
                reward_ticks = max(1, int(round((price - target) / tick)))
                rr = reward_ticks / risk_ticks if risk_ticks else 0
                if rr >= 1.2:
                    score += 0.10
                grade = _grade(score)
                setups.append(TradeSetup(
                    symbol=symbol,
                    setup_type=SetupType.RANGE_FADE,
                    side=Side.SHORT,
                    grade=grade,
                    entry=round(price, 4),
                    stop=round(stop, 4),
                    target=round(target, 4),
                    risk_ticks=risk_ticks,
                    reward_ticks=reward_ticks,
                    rr=round(rr, 2),
                    confluence_score=round(min(score, 0.98), 2),
                    reasons=reasons,
                    invalidation=f"Break and hold above {range_high:.2f}",
                ))
            if loc <= 0.08 and not downtrend:
                score = 0.42
                reasons = [f"At bottom of 20-bar range ({loc:.0%})", "Fade bias (no strong downtrend)"]
                if vol_ratio > 1.2:
                    score += 0.10
                    reasons.append("Volume at extreme")
                if atr_rank > 0.5:
                    score += 0.08
                    reasons.append("Volatility supports mean-reversion risk")
                stop = price - 0.9 * atr
                target = mid
                risk_ticks = max(1, int(round((price - stop) / tick)))
                reward_ticks = max(1, int(round((target - price) / tick)))
                rr = reward_ticks / risk_ticks if risk_ticks else 0
                if rr >= 1.2:
                    score += 0.10
                grade = _grade(score)
                setups.append(TradeSetup(
                    symbol=symbol,
                    setup_type=SetupType.RANGE_FADE,
                    side=Side.LONG,
                    grade=grade,
                    entry=round(price, 4),
                    stop=round(stop, 4),
                    target=round(target, 4),
                    risk_ticks=risk_ticks,
                    reward_ticks=reward_ticks,
                    rr=round(rr, 2),
                    confluence_score=round(min(score, 0.98), 2),
                    reasons=reasons,
                    invalidation=f"Break and hold below {range_low:.2f}",
                ))

        # ---------- 4) Volatility squeeze (compression → directional bias from MA) ----------
        if atr_rank <= 0.20:
            score = 0.40
            reasons = [f"Volatility squeeze (ATR rank {atr_rank:.0%})"]
            side = Side.LONG if price >= ma20 else Side.SHORT
            reasons.append(f"Bias from MA20: {side.value}")
            if abs(roc10) < 0.01:
                score += 0.10
                reasons.append("Coiled price action (low ROC)")
            if vol_ratio < 0.9:
                score += 0.08
                reasons.append("Volume contraction with squeeze")
            stop_dist = max(1.1 * atr, 10 * tick)
            tgt_dist = max(2.2 * atr, 20 * tick)
            if side == Side.LONG:
                stop, target = price - stop_dist, price + tgt_dist
            else:
                stop, target = price + stop_dist, price - tgt_dist
            risk_ticks = max(1, int(round(abs(price - stop) / tick)))
            reward_ticks = max(1, int(round(abs(target - price) / tick)))
            rr = reward_ticks / risk_ticks
            grade = _grade(score)
            setups.append(TradeSetup(
                symbol=symbol,
                setup_type=SetupType.VOL_SQUEEZE,
                side=side,
                grade=grade,
                entry=round(price, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
                rr=round(rr, 2),
                confluence_score=round(min(score, 0.98), 2),
                reasons=reasons,
                invalidation="Squeeze resolves opposite to bias with volume",
            ))

        return setups

    # ------------------------------------------------------------------
    def build_report(self, market_data: Dict[str, pd.DataFrame]) -> SetupReport:
        all_setups: List[TradeSetup] = []
        symbols = list(market_data.keys())
        for sym, df in market_data.items():
            try:
                all_setups.extend(self.scan_symbol(sym, df))
            except Exception as e:
                print(f"⚠️  Setup scan failed for {sym}: {e}")

        # Prefer higher grade + score
        all_setups.sort(key=lambda s: ({"A": 3, "B": 2, "C": 1}[s.grade.value], s.confluence_score), reverse=True)

        n_a = sum(1 for s in all_setups if s.grade == SetupGrade.A)
        n_b = sum(1 for s in all_setups if s.grade == SetupGrade.B)
        if all_setups:
            top = all_setups[0]
            summary = (
                f"{len(all_setups)} setups ({n_a}A / {n_b}B) – "
                f"best: {top.grade.value} {top.side.value} {top.symbol} {top.setup_type.value}"
            )
        else:
            summary = "No clean multi-factor setups this cycle"

        report = SetupReport(
            timestamp=datetime.now(timezone.utc),
            setups=all_setups,
            scanned_symbols=symbols,
            summary=summary,
        )
        self.last_report = report
        return report

    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        report = self.build_report(market_data)
        print("\n" + report.pretty() + "\n")

        signals: List[Signal] = []
        for s in report.setups:
            if not self._allowed(s.grade):
                continue
            # Confidence from grade + confluence
            base = {"A": 0.85, "B": 0.65, "C": 0.45}[s.grade.value]
            conf = min(base * s.confluence_score * 1.15, 0.95) * self.weight
            signals.append(Signal(
                agent_id=self.agent_id,
                symbol=s.symbol,
                side=s.side,
                confidence=conf,
                size_contracts=2 if s.grade == SetupGrade.A else 1,
                stop_ticks=s.risk_ticks,
                target_ticks=s.reward_ticks,
                reason=f"SETUP {s.grade.value} {s.setup_type.value} R:R={s.rr} | {s.reasons[0] if s.reasons else ''}",
                metadata={
                    "setup": True,
                    "grade": s.grade.value,
                    "setup_type": s.setup_type.value,
                    "entry": s.entry,
                    "stop": s.stop,
                    "target": s.target,
                    "rr": s.rr,
                    "reasons": s.reasons,
                },
            ))
        return signals

    def get_last_report(self) -> Optional[SetupReport]:
        return self.last_report
