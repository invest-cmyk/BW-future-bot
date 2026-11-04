"""
Symbol-specific trading team.
Each team only works one futures product and produces a TeamRecommendation for the CEO.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import copy

import pandas as pd

from agents.base import BaseAgent
from agents.momentum import MomentumAgent
from agents.mean_reversion import MeanReversionAgent
from agents.breakout import BreakoutAgent
from agents.volatility import VolatilityAgent
from agents.seasonality import SeasonalityAgent
from agents.cot import COTAgent
from agents.orderflow import OrderFlowAgent
from agents.setup import SetupAgent
from agents.data_collector import DataCollectorAgent
from agents.news_collector import NewsCollectorAgent
from core.models import Signal, Side
from core.risk import RiskAgent
from config.settings import CONTRACTS


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


@dataclass
class TeamRecommendation:
    team_id: str
    team_name: str
    symbol: str
    action: Action
    confidence: float
    size_contracts: int
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    reason: str = ""
    agent_votes: Dict[str, str] = field(default_factory=dict)
    setup_grade: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "PENDING"  # PENDING / APPROVED / REJECTED / EXPIRED / EXECUTED
    recommendation_id: str = ""

    def pretty(self) -> str:
        lines = [
            f"📋 {self.team_name} → {self.symbol}",
            f"   Action     : {self.action.value}",
            f"   Confidence : {self.confidence:.0%}",
            f"   Size       : {self.size_contracts} contract(s)",
        ]
        if self.entry:
            lines.append(f"   Entry      : {self.entry:.2f}")
        if self.stop:
            lines.append(f"   Stop       : {self.stop:.2f}")
        if self.target:
            lines.append(f"   Target     : {self.target:.2f}")
        if self.setup_grade:
            lines.append(f"   Setup grade: {self.setup_grade}")
        lines.append(f"   Reason     : {self.reason}")
        if self.agent_votes:
            votes = ", ".join(f"{k}:{v}" for k, v in self.agent_votes.items())
            lines.append(f"   Votes      : {votes}")
        lines.append(f"   Status     : {self.status}  |  id={self.recommendation_id}")
        return "\n".join(lines)


def _build_team_agents(symbol: str) -> List[BaseAgent]:
    """Fresh agent instances scoped in usage to one symbol via filtered market_data."""
    tag = symbol.lower()
    return [
        DataCollectorAgent(f"data_{tag}", weight=0.4),
        SetupAgent(f"setup_{tag}", weight=0.95, min_grade="B"),
        MomentumAgent(f"mom_{tag}", weight=1.0),
        MeanReversionAgent(f"mr_{tag}", weight=0.75),
        BreakoutAgent(f"bo_{tag}", weight=0.9),
        VolatilityAgent(f"vol_{tag}", weight=0.6),
        SeasonalityAgent(f"season_{tag}", weight=0.45),
        COTAgent(f"cot_{tag}", weight=0.55),
        OrderFlowAgent(f"of_{tag}", weight=0.6),
        # News is shared-style but still runs; symbol relevance is inside the agent
        NewsCollectorAgent(f"news_{tag}", weight=0.55),
    ]


class Team:
    """
    One team = one symbol.
    Runs its agents only on that symbol and produces a single TeamRecommendation for the CEO.
    """

    def __init__(self, team_id: str, team_name: str, symbol: str):
        if symbol not in CONTRACTS:
            raise ValueError(f"Unknown futures symbol for team: {symbol}")
        self.team_id = team_id
        self.team_name = team_name
        self.symbol = symbol
        self.agents = _build_team_agents(symbol)
        self.risk = RiskAgent()
        self.last_recommendation: Optional[TeamRecommendation] = None
        self.last_setup_report = None
        self.last_data_report = None
        self.last_news_report = None

    def run(self, market_data: Dict[str, pd.DataFrame],
            prices: Dict[str, float],
            equity: float = 100_000.0) -> Optional[TeamRecommendation]:
        """
        Run all team agents on THIS symbol only. Aggregate into one recommendation.
        """
        if self.symbol not in market_data:
            return None

        # Filter market data to this symbol only
        local_data = {self.symbol: market_data[self.symbol]}
        local_prices = {self.symbol: prices.get(self.symbol, 0.0)}

        all_signals: List[Signal] = []
        votes: Dict[str, str] = {}

        for agent in self.agents:
            if not agent.enabled:
                continue
            try:
                sigs = agent.generate(local_data)
                # Keep only this symbol
                sigs = [s for s in sigs if s.symbol == self.symbol]
                all_signals.extend(sigs)
                if sigs:
                    # majority side from this agent
                    longs = sum(1 for s in sigs if s.side == Side.LONG)
                    shorts = sum(1 for s in sigs if s.side == Side.SHORT)
                    if longs > shorts:
                        votes[agent.agent_id] = "BUY"
                    elif shorts > longs:
                        votes[agent.agent_id] = "SELL"
                    else:
                        votes[agent.agent_id] = "HOLD"
                # Capture reports
                if hasattr(agent, "get_last_report"):
                    rep = agent.get_last_report()
                    if rep is None:
                        continue
                    if agent.agent_id.startswith("setup"):
                        self.last_setup_report = rep
                    elif agent.agent_id.startswith("data"):
                        self.last_data_report = rep
                    elif agent.agent_id.startswith("news"):
                        self.last_news_report = rep
            except Exception as e:
                print(f"⚠️  {self.team_name} agent {agent.agent_id} failed: {e}")

        # Risk filter (news-aware)
        safe = self.risk.filter(
            all_signals,
            equity=equity,
            peak_equity=equity,
            day_start_equity=equity,
            positions={},
            prices=local_prices,
            news_report=self.last_news_report,
        )

        rec = self._aggregate(safe, votes, local_prices.get(self.symbol))
        self.last_recommendation = rec
        return rec

    def _aggregate(self, signals: List[Signal], votes: Dict[str, str],
                   price: Optional[float]) -> TeamRecommendation:
        import uuid
        rid = str(uuid.uuid4())[:8]

        if not signals:
            return TeamRecommendation(
                team_id=self.team_id,
                team_name=self.team_name,
                symbol=self.symbol,
                action=Action.HOLD,
                confidence=0.0,
                size_contracts=0,
                entry=price,
                reason="No consensus signals after risk filter",
                agent_votes=votes,
                recommendation_id=rid,
                status="PENDING",
            )

        buy_score = sum(s.confidence * s.size_contracts for s in signals if s.side == Side.LONG)
        sell_score = sum(s.confidence * s.size_contracts for s in signals if s.side == Side.SHORT)

        # Setup grade if any
        setup_grade = None
        setup_meta = None
        for s in signals:
            if s.metadata.get("setup"):
                setup_grade = s.metadata.get("grade")
                setup_meta = s.metadata
                break

        if buy_score > sell_score * 1.1:
            action = Action.BUY
            side_sigs = [s for s in signals if s.side == Side.LONG]
        elif sell_score > buy_score * 1.1:
            action = Action.SELL
            side_sigs = [s for s in signals if s.side == Side.SHORT]
        else:
            return TeamRecommendation(
                team_id=self.team_id,
                team_name=self.team_name,
                symbol=self.symbol,
                action=Action.HOLD,
                confidence=0.0,
                size_contracts=0,
                entry=price,
                reason=f"Conflict buy={buy_score:.2f} vs sell={sell_score:.2f}",
                agent_votes=votes,
                recommendation_id=rid,
                status="PENDING",
            )

        best = max(side_sigs, key=lambda x: x.confidence)
        conf = min(best.confidence, 0.95)
        size = max(1, min(best.size_contracts, 3))

        entry = price
        stop = target = None
        if setup_meta:
            entry = setup_meta.get("entry") or price
            stop = setup_meta.get("stop")
            target = setup_meta.get("target")
        elif best.stop_ticks and price and self.symbol in CONTRACTS:
            tick = CONTRACTS[self.symbol].tick_size
            if action == Action.BUY:
                stop = price - best.stop_ticks * tick
                target = price + (best.target_ticks or best.stop_ticks * 2) * tick
            else:
                stop = price + best.stop_ticks * tick
                target = price - (best.target_ticks or best.stop_ticks * 2) * tick

        reason = best.reason
        if setup_grade:
            reason = f"Setup {setup_grade} | {reason}"

        return TeamRecommendation(
            team_id=self.team_id,
            team_name=self.team_name,
            symbol=self.symbol,
            action=action,
            confidence=conf,
            size_contracts=size,
            entry=entry,
            stop=stop,
            target=target,
            reason=reason,
            agent_votes=votes,
            setup_grade=setup_grade,
            recommendation_id=rid,
            status="PENDING",
        )
