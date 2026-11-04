"""
Boss Agent – the orchestrator that collects signals, applies risk,
resolves conflicts, and manages the portfolio.
"""

from typing import Dict, List, Optional
from datetime import datetime
import uuid
import pandas as pd

from core.models import Signal, Position, Trade, Side
from core.risk import RiskAgent
from config.settings import CONTRACTS, SIM, RISK
from agents.base import BaseAgent


class BossAgent:
    def __init__(self, agents: List[BaseAgent], risk_agent: Optional[RiskAgent] = None):
        self.agents = agents
        self.risk = risk_agent or RiskAgent()

        self.equity = SIM["starting_equity"]
        self.cash = self.equity
        self.peak_equity = self.equity
        self.day_start_equity = self.equity

        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.commission = SIM["commission_per_side"]
        self.slippage_ticks = SIM["slippage_ticks"]
        self.last_news_report = None  # filled by NewsCollectorAgent
        self.last_data_report = None  # filled by DataCollectorAgent
        self.last_setup_report = None  # filled by SetupAgent
        self.last_risk_report = None  # filled by RiskAgent every cycle

    def run_cycle(self, market_data: Dict[str, pd.DataFrame], prices: Dict[str, float]) -> List[Signal]:
        """
        One full decision cycle:
        0. Check stops / force exits
        1. Collect signals from all enabled agents
        2. Risk filter
        3. Conflict resolution + consensus
        4. Execute approved orders (simulation)
        """
        # 0. Manage open risk first
        self._check_stops(prices)

        # 1. Gather proposals
        all_signals: List[Signal] = []
        for agent in self.agents:
            if not agent.enabled:
                continue
            try:
                sigs = agent.generate(market_data)
                all_signals.extend(sigs)
                # Capture structured reports from collector / setup agents
                if hasattr(agent, "get_last_report"):
                    report = agent.get_last_report()
                    if report is None:
                        pass
                    elif agent.agent_id.startswith("news"):
                        self.last_news_report = report
                        print(f"Boss received NEWS report: bias={getattr(report, 'overall_bias', '?')} score={getattr(report, 'bias_score', 0)}")
                    elif agent.agent_id.startswith("data"):
                        self.last_data_report = report
                        print(f"Boss received DATA report: regime={getattr(report, 'market_regime', '?')} vol={getattr(report, 'vol_environment', '?')}")
                    elif agent.agent_id.startswith("setup"):
                        self.last_setup_report = report
                        n = len(getattr(report, 'setups', []) or [])
                        print(f"Boss received SETUP report: {n} setup(s) | {getattr(report, 'summary', '')}")
            except Exception as e:
                print(f"⚠️  Agent {agent.agent_id} failed: {e}")

        # 2. Risk filter ALWAYS runs so it can report on news (good or bad)
        #    even when strategy agents produced no signals.
        safe = self.risk.filter(
            all_signals,
            equity=self.equity,
            peak_equity=self.peak_equity,
            day_start_equity=self.day_start_equity,
            positions=self.positions,
            prices=prices,
            news_report=self.last_news_report,
        )
        if hasattr(self.risk, "get_last_report"):
            self.last_risk_report = self.risk.get_last_report()

        if not safe:
            return []

        # 3. Conflict resolution (per symbol)
        final = self._resolve_conflicts(safe)

        # 4. Execute
        for sig in final:
            self._execute(sig, prices.get(sig.symbol))

        # Update equity mark-to-market
        self._mark_to_market(prices)
        return final

    def _resolve_conflicts(self, signals: List[Signal]) -> List[Signal]:
        """
        Simple but effective consensus:
        - Group by symbol
        - Score LONG vs SHORT by confidence * size * agent weight
        - Only take the stronger side if edge is clear
        """
        from collections import defaultdict
        by_sym = defaultdict(list)
        for s in signals:
            if s.side != Side.FLAT:
                by_sym[s.symbol].append(s)

        approved = []
        for symbol, sigs in by_sym.items():
            long_score = sum(s.confidence * s.size_contracts for s in sigs if s.side == Side.LONG)
            short_score = sum(s.confidence * s.size_contracts for s in sigs if s.side == Side.SHORT)

            if long_score > short_score * 1.15:          # require clear majority
                best = max((s for s in sigs if s.side == Side.LONG), key=lambda x: x.confidence)
                approved.append(best)
            elif short_score > long_score * 1.15:
                best = max((s for s in sigs if s.side == Side.SHORT), key=lambda x: x.confidence)
                approved.append(best)
            # else: conflict → stay flat

        return approved

    def _execute(self, signal: Signal, price: Optional[float]):
        if price is None or signal.size_contracts <= 0:
            return

        spec = CONTRACTS.get(signal.symbol)
        if not spec:
            print(f"❌ Unknown contract {signal.symbol}")
            return

        # Apply slippage
        slip = self.slippage_ticks * spec.tick_size
        fill_price = price + slip if signal.side == Side.LONG else price - slip

        # Commission
        commission = self.commission * signal.size_contracts

        # Open or add to position (simplified – no scaling for now)
        existing = self.positions.get(signal.symbol)

        if existing and existing.side == signal.side:
            # Average in
            total_qty = existing.qty + signal.size_contracts
            existing.avg_price = (existing.avg_price * existing.qty + fill_price * signal.size_contracts) / total_qty
            existing.qty = total_qty
        elif existing and existing.side != signal.side:
            # Opposite signal → close first (simplified)
            self._close_position(signal.symbol, price, reason="reverse")
            existing = None

        if not existing or existing.qty == 0:
            stop_price = None
            if signal.stop_ticks:
                stop_dist = signal.stop_ticks * spec.tick_size
                stop_price = fill_price - stop_dist if signal.side == Side.LONG else fill_price + stop_dist

            self.positions[signal.symbol] = Position(
                symbol=signal.symbol,
                side=signal.side,
                qty=signal.size_contracts,
                avg_price=fill_price,
                entry_time=datetime.utcnow(),
                stop_price=stop_price
            )

        self.cash -= commission
        print(f"✅ Boss EXECUTED {signal.side.value} {signal.size_contracts} {signal.symbol} "
              f"@ {fill_price:.2f} | conf={signal.confidence:.2f} | {signal.reason}")

        # Log trade entry
        self.trades.append(Trade(
            trade_id=str(uuid.uuid4())[:8],
            symbol=signal.symbol,
            side=signal.side,
            qty=signal.size_contracts,
            entry_price=fill_price,
            agent_id=signal.agent_id,
            reason=signal.reason,
            commission=commission
        ))

    def _check_stops(self, prices: Dict[str, float]):
        """Force exit if price has hit the stop level."""
        for sym, pos in list(self.positions.items()):
            if pos.qty == 0 or pos.stop_price is None:
                continue
            price = prices.get(sym)
            if price is None:
                continue
            hit = False
            if pos.side == Side.LONG and price <= pos.stop_price:
                hit = True
            elif pos.side == Side.SHORT and price >= pos.stop_price:
                hit = True
            if hit:
                self._close_position(sym, price, reason="stop hit")

    def _close_position(self, symbol: str, price: float, reason: str = ""):
        pos = self.positions.get(symbol)
        if not pos or pos.qty == 0:
            return

        spec = CONTRACTS[symbol]
        slip = self.slippage_ticks * spec.tick_size
        fill = price - slip if pos.side == Side.LONG else price + slip

        points = (fill - pos.avg_price) if pos.side == Side.LONG else (pos.avg_price - fill)
        pnl = points * spec.multiplier * pos.qty
        commission = self.commission * pos.qty
        net = pnl - commission

        self.cash += net
        print(f"🔄 Closed {pos.side.value} {pos.qty} {symbol} @ {fill:.2f} | PnL ${net:,.2f} | {reason}")

        # Update last matching trade
        for t in reversed(self.trades):
            if t.symbol == symbol and t.exit_price is None:
                t.exit_price = fill
                t.exit_time = datetime.utcnow()
                t.pnl = net
                break

        pos.qty = 0
        pos.side = Side.FLAT

    def _mark_to_market(self, prices: Dict[str, float]):
        unrealized = 0.0
        for sym, pos in self.positions.items():
            if pos.qty == 0:
                continue
            price = prices.get(sym, pos.avg_price)
            spec = CONTRACTS[sym]
            points = (price - pos.avg_price) if pos.side == Side.LONG else (pos.avg_price - price)
            pos.unrealized_pnl = points * spec.multiplier * pos.qty
            unrealized += pos.unrealized_pnl

        self.equity = self.cash + unrealized
        self.peak_equity = max(self.peak_equity, self.equity)

    def new_day(self):
        """Call at start of each trading day"""
        self.day_start_equity = self.equity

    def status(self) -> dict:
        open_pos = {s: p for s, p in self.positions.items() if p.qty > 0}
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "peak": round(self.peak_equity, 2),
            "open_positions": len(open_pos),
            "positions": {s: f"{p.side.value} {p.qty} @ {p.avg_price:.2f}" for s, p in open_pos.items()},
            "total_trades": len(self.trades),
        }
