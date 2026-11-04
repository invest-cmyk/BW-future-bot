"""
Risk management for leveraged futures
--------------------------------------
Risk Agent now:
  • Consumes the NewsCollectorAgent report every cycle
  • Tightens / loosens limits on bad vs good news
  • Always builds a structured RiskReport for the Boss
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.models import Signal, Position, Side
from config.settings import CONTRACTS, RISK


# ---------------------------------------------------------------------------
# Structured report delivered to the Boss every cycle
# ---------------------------------------------------------------------------
@dataclass
class RiskReport:
    timestamp: datetime
    equity: float
    peak_equity: float
    daily_pnl_pct: float
    drawdown_pct: float
    open_heat_pct: float
    remaining_heat_pct: float

    # News context (from NewsCollectorAgent)
    news_bias: str = "NEUTRAL"          # BULLISH / BEARISH / NEUTRAL
    news_score: float = 0.0
    news_summary: str = ""
    key_risks_from_news: List[str] = field(default_factory=list)
    news_regime: str = "NORMAL"         # NORMAL / CAUTION / DEFENSIVE / OPPORTUNITY

    # Actions taken this cycle
    signals_received: int = 0
    signals_approved: int = 0
    signals_blocked: int = 0
    size_reductions: int = 0
    blocked_reasons: List[str] = field(default_factory=list)
    adjustments: List[str] = field(default_factory=list)  # what news made us change

    # Effective limits after news adjustment
    effective_max_risk_per_trade: float = 0.0
    effective_max_heat: float = 0.0
    effective_max_daily_loss: float = 0.0
    trading_allowed: bool = True

    def pretty(self) -> str:
        lines = [
            f"🛡️  RISK REPORT  {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Equity        : ${self.equity:,.2f}  |  Peak ${self.peak_equity:,.2f}",
            f"Daily P&L     : {self.daily_pnl_pct:+.2%}",
            f"Drawdown      : {self.drawdown_pct:.2%}",
            f"Open heat     : {self.open_heat_pct:.2%}  (remaining {self.remaining_heat_pct:.2%})",
            "",
            f"News regime   : {self.news_regime}  |  bias {self.news_bias} ({self.news_score:+.2f})",
        ]
        if self.news_summary:
            lines.append(f"News summary  : {self.news_summary[:120]}...")
        if self.key_risks_from_news:
            lines.append("News risks    :")
            for r in self.key_risks_from_news[:3]:
                lines.append(f"  • {r[:90]}")
        lines += [
            "",
            f"Signals       : {self.signals_received} in → {self.signals_approved} approved "
            f"({self.signals_blocked} blocked, {self.size_reductions} size cuts)",
            f"Trading       : {'ALLOWED' if self.trading_allowed else 'BLOCKED'}",
            f"Limits        : risk/trade {self.effective_max_risk_per_trade:.2%}  |  "
            f"heat {self.effective_max_heat:.2%}  |  daily loss {self.effective_max_daily_loss:.2%}",
        ]
        if self.adjustments:
            lines.append("News adjustments:")
            for a in self.adjustments:
                lines.append(f"  → {a}")
        if self.blocked_reasons:
            lines.append("Block reasons:")
            for r in self.blocked_reasons[:5]:
                lines.append(f"  • {r}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "equity": self.equity,
            "daily_pnl_pct": round(self.daily_pnl_pct, 4),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "open_heat_pct": round(self.open_heat_pct, 4),
            "news_regime": self.news_regime,
            "news_bias": self.news_bias,
            "news_score": self.news_score,
            "signals_received": self.signals_received,
            "signals_approved": self.signals_approved,
            "signals_blocked": self.signals_blocked,
            "trading_allowed": self.trading_allowed,
            "adjustments": self.adjustments,
        }


class RiskAgent:
    """
    Risk filter + reporter.
    Always produces a RiskReport for the Boss.
    Incorporates news (good / bad) into position sizing and trading permission.
    """

    def __init__(self):
        self.base_max_risk_per_trade = RISK["max_risk_per_trade_pct"]
        self.base_max_heat = RISK["max_portfolio_heat"]
        self.max_contracts = RISK["max_contracts_per_symbol"]
        self.base_max_daily_loss = RISK["max_daily_loss_pct"]
        self.max_drawdown = RISK["max_drawdown_pct"]
        self.last_report: Optional[RiskReport] = None

    # ------------------------------------------------------------------
    def _news_regime(self, news_report) -> tuple:
        """
        Translate NewsReport into a risk regime and limit multipliers.
        Returns (regime_name, risk_mult, heat_mult, daily_loss_mult, adjustments)
        """
        if news_report is None:
            return "NORMAL", 1.0, 1.0, 1.0, ["No news report available → default limits"]

        bias = getattr(news_report, "overall_bias", "NEUTRAL") or "NEUTRAL"
        score = float(getattr(news_report, "bias_score", 0.0) or 0.0)
        risks = list(getattr(news_report, "key_risks", []) or [])

        adjustments = []

        # Strong negative news → DEFENSIVE
        if bias == "BEARISH" and score <= -0.25:
            regime = "DEFENSIVE"
            risk_m, heat_m, daily_m = 0.50, 0.55, 0.70
            adjustments.append(
                f"Strong bearish news (score {score:+.2f}) → cut risk 50%, heat 45%, tighter daily loss"
            )
        elif bias == "BEARISH" or score <= -0.12 or len(risks) >= 3:
            regime = "CAUTION"
            risk_m, heat_m, daily_m = 0.70, 0.75, 0.85
            adjustments.append(
                f"Negative / risky news (bias={bias}, score {score:+.2f}, "
                f"{len(risks)} key risks) → reduce risk ~30%"
            )
        elif bias == "BULLISH" and score >= 0.25:
            regime = "OPPORTUNITY"
            risk_m, heat_m, daily_m = 1.15, 1.10, 1.05
            adjustments.append(
                f"Strong bullish news (score {score:+.2f}) → modestly higher risk allowance"
            )
        elif bias == "BULLISH" or score >= 0.12:
            regime = "NORMAL"
            risk_m, heat_m, daily_m = 1.05, 1.05, 1.0
            adjustments.append(f"Mildly positive news (score {score:+.2f}) → slight risk uplift")
        else:
            regime = "NORMAL"
            risk_m, heat_m, daily_m = 1.0, 1.0, 1.0
            adjustments.append(f"Neutral news (score {score:+.2f}) → standard limits")

        # Extra caution if many explicit risk headlines
        if len(risks) >= 4 and regime in ("NORMAL", "OPPORTUNITY"):
            regime = "CAUTION"
            risk_m = min(risk_m, 0.75)
            heat_m = min(heat_m, 0.80)
            adjustments.append(f"{len(risks)} key risk headlines → forced CAUTION")

        return regime, risk_m, heat_m, daily_m, adjustments

    # ------------------------------------------------------------------
    def filter(self,
               signals: List[Signal],
               equity: float,
               peak_equity: float,
               day_start_equity: float,
               positions: Dict[str, Position],
               prices: Dict[str, float],
               news_report=None) -> List[Signal]:
        """
        Hard risk filters + news-aware adjustments.
        Always builds and stores a RiskReport for the Boss.
        """
        now = datetime.now(timezone.utc)
        daily_pnl_pct = (equity - day_start_equity) / day_start_equity if day_start_equity else 0.0
        dd = (equity - peak_equity) / peak_equity if peak_equity else 0.0
        open_risk = self._current_open_risk(positions, prices, equity)

        # --- News-driven limit adjustment ---
        regime, risk_m, heat_m, daily_m, adjustments = self._news_regime(news_report)

        eff_risk = self.base_max_risk_per_trade * risk_m
        eff_heat = self.base_max_heat * heat_m
        eff_daily = self.base_max_daily_loss * daily_m

        news_bias = getattr(news_report, "overall_bias", "NEUTRAL") if news_report else "NEUTRAL"
        news_score = float(getattr(news_report, "bias_score", 0.0) or 0.0) if news_report else 0.0
        news_summary = getattr(news_report, "summary", "") if news_report else ""
        key_risks = list(getattr(news_report, "key_risks", []) or []) if news_report else []

        blocked_reasons: List[str] = []
        size_reductions = 0
        trading_allowed = True

        # 1. Daily loss limit (news-adjusted)
        if daily_pnl_pct <= -eff_daily:
            msg = f"Daily loss limit hit ({daily_pnl_pct:.2%} ≤ -{eff_daily:.2%}) [news regime={regime}]"
            print(f"🛑 RiskAgent: {msg}. Blocking new trades.")
            blocked_reasons.append(msg)
            trading_allowed = False
            approved: List[Signal] = []
        # 2. Max drawdown from peak
        elif dd <= -self.max_drawdown:
            msg = f"Max drawdown hit ({dd:.2%})"
            print(f"🛑 RiskAgent: {msg}. System paused.")
            blocked_reasons.append(msg)
            trading_allowed = False
            approved = []
        else:
            remaining_heat = max(0.0, eff_heat - open_risk)
            approved = []

            for sig in signals:
                if sig.side == Side.FLAT or sig.size_contracts <= 0:
                    continue

                spec = CONTRACTS.get(sig.symbol)
                if not spec:
                    blocked_reasons.append(f"{sig.symbol}: unknown contract")
                    continue

                stop_ticks = sig.stop_ticks or RISK["default_stop_ticks"]
                risk_per_contract = stop_ticks * spec.tick_value
                total_risk = risk_per_contract * sig.size_contracts
                risk_pct = total_risk / equity if equity else 1.0

                original_size = sig.size_contracts

                # Cap size to max risk per trade (news-adjusted)
                if risk_pct > eff_risk:
                    max_contracts = max(1, int((eff_risk * equity) / risk_per_contract))
                    sig.size_contracts = min(sig.size_contracts, max_contracts)
                    if sig.size_contracts < original_size:
                        size_reductions += 1
                        adjustments.append(
                            f"{sig.symbol}: size {original_size}→{sig.size_contracts} "
                            f"(news-adjusted risk cap {eff_risk:.2%})"
                        )

                # Per-symbol contract limit
                current_qty = 0
                if sig.symbol in positions:
                    current_qty = positions[sig.symbol].qty
                if current_qty + sig.size_contracts > self.max_contracts:
                    sig.size_contracts = max(0, self.max_contracts - current_qty)
                    if sig.size_contracts < original_size:
                        size_reductions += 1

                if sig.size_contracts <= 0:
                    blocked_reasons.append(f"{sig.symbol}: size reduced to 0")
                    continue

                # Remaining heat
                new_risk_pct = (risk_per_contract * sig.size_contracts) / equity if equity else 1.0
                if new_risk_pct > remaining_heat:
                    blocked_reasons.append(
                        f"{sig.symbol}: would exceed remaining heat "
                        f"({new_risk_pct:.2%} > {remaining_heat:.2%})"
                    )
                    continue

                # Extra: under DEFENSIVE / CAUTION, reject low-confidence signals
                if regime in ("DEFENSIVE", "CAUTION") and sig.confidence < 0.45:
                    blocked_reasons.append(
                        f"{sig.symbol}: low confidence {sig.confidence:.2f} blocked in {regime} regime"
                    )
                    continue

                approved.append(sig)
                remaining_heat -= new_risk_pct

        remaining_heat_final = max(0.0, eff_heat - open_risk)

        report = RiskReport(
            timestamp=now,
            equity=equity,
            peak_equity=peak_equity,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=dd,
            open_heat_pct=open_risk,
            remaining_heat_pct=remaining_heat_final,
            news_bias=news_bias,
            news_score=news_score,
            news_summary=news_summary,
            key_risks_from_news=key_risks,
            news_regime=regime,
            signals_received=len(signals),
            signals_approved=len(approved),
            signals_blocked=len(signals) - len(approved),
            size_reductions=size_reductions,
            blocked_reasons=blocked_reasons,
            adjustments=adjustments,
            effective_max_risk_per_trade=eff_risk,
            effective_max_heat=eff_heat,
            effective_max_daily_loss=eff_daily,
            trading_allowed=trading_allowed,
        )
        self.last_report = report
        print("\n" + report.pretty() + "\n")
        return approved

    def get_last_report(self) -> Optional[RiskReport]:
        return self.last_report

    def _current_open_risk(self, positions: Dict[str, Position],
                           prices: Dict[str, float], equity: float) -> float:
        risk = 0.0
        for sym, pos in positions.items():
            if pos.qty == 0 or pos.side == Side.FLAT:
                continue
            spec = CONTRACTS.get(sym)
            if not spec or pos.stop_price is None:
                risk += 0.01 * equity
                continue
            dist = abs(prices.get(sym, pos.avg_price) - pos.stop_price)
            ticks = dist / spec.tick_size if spec.tick_size else 0
            risk += ticks * spec.tick_value * pos.qty
        return risk / equity if equity > 0 else 0.0
