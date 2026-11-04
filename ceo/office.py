"""
CEO Office – you are the CEO.
Teams report recommendations here for approval.
You can also grant the Boss time-limited permission to trade on your behalf.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import json
from pathlib import Path

from teams.team import TeamRecommendation, Action


class DelegationScope(str, Enum):
    NONE = "NONE"
    ALL_TEAMS = "ALL_TEAMS"
    SINGLE_TEAM = "SINGLE_TEAM"


@dataclass
class DelegationGrant:
    """Time-limited authority for the Boss to execute without per-trade CEO approval."""
    active: bool = False
    scope: DelegationScope = DelegationScope.NONE
    team_ids: List[str] = field(default_factory=list)  # if SINGLE_TEAM / subset
    expires_at: Optional[datetime] = None
    max_contracts_per_trade: int = 2
    max_trades_remaining: int = 10
    granted_at: Optional[datetime] = None
    note: str = ""

    def is_valid(self) -> bool:
        if not self.active:
            return False
        if self.expires_at and datetime.now(timezone.utc) >= self.expires_at:
            return False
        if self.max_trades_remaining <= 0:
            return False
        return True

    def allows_team(self, team_id: str) -> bool:
        if not self.is_valid():
            return False
        if self.scope == DelegationScope.ALL_TEAMS:
            return True
        if self.scope == DelegationScope.SINGLE_TEAM:
            return team_id in self.team_ids
        return False

    def pretty(self) -> str:
        if not self.active:
            return "Delegation: OFF (CEO approval required for every trade)"
        if not self.is_valid():
            return "Delegation: EXPIRED or exhausted"
        exp = self.expires_at.strftime("%Y-%m-%d %H:%M UTC") if self.expires_at else "no expiry"
        teams = "ALL" if self.scope == DelegationScope.ALL_TEAMS else ",".join(self.team_ids)
        return (
            f"Delegation: ON | scope={teams} | expires={exp} | "
            f"max_size={self.max_contracts_per_trade} | trades_left={self.max_trades_remaining}"
        )


class CEOOffice:
    """
    Central desk where all 6 teams report.
    CEO (you) approves/rejects, or grants time-limited autopilot to the Boss.
    """

    def __init__(self, state_file: Optional[str] = None):
        self.pending: Dict[str, TeamRecommendation] = {}
        self.history: List[TeamRecommendation] = []
        self.delegation = DelegationGrant()
        self.state_file = Path(state_file) if state_file else Path("ceo_state.json")
        self._load()

    # ----- Team reporting -----
    def receive(self, rec: TeamRecommendation) -> str:
        """Team submits recommendation. Returns recommendation_id."""
        if rec.action == Action.HOLD:
            rec.status = "HOLD"
            self.history.append(rec)
            return rec.recommendation_id

        # If Boss has valid delegation for this team → auto-approve
        if self.delegation.allows_team(rec.team_id):
            if rec.size_contracts > self.delegation.max_contracts_per_trade:
                rec.size_contracts = self.delegation.max_contracts_per_trade
            rec.status = "APPROVED"
            rec.reason = f"[CEO DELEGATED] {rec.reason}"
            self.delegation.max_trades_remaining -= 1
            self.history.append(rec)
            self._save()
            print(f"✅ CEO DELEGATION auto-approved {rec.team_name} {rec.action.value} {rec.symbol}")
            return rec.recommendation_id

        rec.status = "PENDING"
        self.pending[rec.recommendation_id] = rec
        self._save()
        print(f"⏳ PENDING CEO approval: {rec.team_name} {rec.action.value} {rec.symbol} "
              f"(id={rec.recommendation_id})")
        return rec.recommendation_id

    # ----- CEO decisions -----
    def approve(self, recommendation_id: str, note: str = "") -> Optional[TeamRecommendation]:
        rec = self.pending.pop(recommendation_id, None)
        if not rec:
            print(f"❌ No pending recommendation id={recommendation_id}")
            return None
        rec.status = "APPROVED"
        if note:
            rec.reason = f"{rec.reason} | CEO note: {note}"
        self.history.append(rec)
        self._save()
        print(f"✅ CEO APPROVED {rec.team_name} {rec.action.value} {rec.symbol}")
        return rec

    def reject(self, recommendation_id: str, note: str = "") -> Optional[TeamRecommendation]:
        rec = self.pending.pop(recommendation_id, None)
        if not rec:
            print(f"❌ No pending recommendation id={recommendation_id}")
            return None
        rec.status = "REJECTED"
        if note:
            rec.reason = f"{rec.reason} | CEO reject: {note}"
        self.history.append(rec)
        self._save()
        print(f"🚫 CEO REJECTED {rec.team_name} {rec.action.value} {rec.symbol}")
        return rec

    def approve_all(self) -> List[TeamRecommendation]:
        ids = list(self.pending.keys())
        out = []
        for i in ids:
            r = self.approve(i)
            if r:
                out.append(r)
        return out

    def reject_all(self) -> List[TeamRecommendation]:
        ids = list(self.pending.keys())
        out = []
        for i in ids:
            r = self.reject(i)
            if r:
                out.append(r)
        return out

    # ----- Delegation (Boss trades on CEO behalf) -----
    def grant_delegation(
        self,
        minutes: int = 60,
        scope: str = "ALL_TEAMS",
        team_ids: Optional[List[str]] = None,
        max_contracts: int = 2,
        max_trades: int = 10,
        note: str = "",
    ) -> DelegationGrant:
        """
        Grant Boss permission to buy/sell without asking each time.
        Limited by time and trade count.
        """
        exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        sc = DelegationScope.ALL_TEAMS if scope == "ALL_TEAMS" else DelegationScope.SINGLE_TEAM
        self.delegation = DelegationGrant(
            active=True,
            scope=sc,
            team_ids=team_ids or [],
            expires_at=exp,
            max_contracts_per_trade=max_contracts,
            max_trades_remaining=max_trades,
            granted_at=datetime.now(timezone.utc),
            note=note,
        )
        self._save()
        print(f"🔑 CEO granted delegation: {self.delegation.pretty()}")
        return self.delegation

    def revoke_delegation(self):
        self.delegation = DelegationGrant(active=False)
        self._save()
        print("🔒 CEO revoked all delegation. Approval required again.")

    # ----- Views -----
    def list_pending(self) -> List[TeamRecommendation]:
        return list(self.pending.values())

    def briefing(self) -> str:
        lines = [
            "=" * 60,
            "  CEO DESK – Team Reports",
            "=" * 60,
            self.delegation.pretty(),
            "",
        ]
        pending = self.list_pending()
        if not pending:
            lines.append("No pending recommendations.")
        else:
            lines.append(f"PENDING APPROVALS ({len(pending)}):")
            lines.append("-" * 40)
            for rec in pending:
                lines.append(rec.pretty())
                lines.append("")
        recent = [h for h in self.history[-8:] if h.status in ("APPROVED", "REJECTED", "HOLD")]
        if recent:
            lines.append("RECENT DECISIONS:")
            for h in recent:
                lines.append(f"  [{h.status}] {h.team_name} {h.action.value} {h.symbol} conf={h.confidence:.0%}")
        return "\n".join(lines)

    # ----- Persistence -----
    def _save(self):
        try:
            data = {
                "delegation": {
                    "active": self.delegation.active,
                    "scope": self.delegation.scope.value,
                    "team_ids": self.delegation.team_ids,
                    "expires_at": self.delegation.expires_at.isoformat() if self.delegation.expires_at else None,
                    "max_contracts_per_trade": self.delegation.max_contracts_per_trade,
                    "max_trades_remaining": self.delegation.max_trades_remaining,
                    "note": self.delegation.note,
                },
                "pending_ids": list(self.pending.keys()),
            }
            self.state_file.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load(self):
        try:
            if not self.state_file.exists():
                return
            data = json.loads(self.state_file.read_text())
            d = data.get("delegation", {})
            exp = d.get("expires_at")
            self.delegation = DelegationGrant(
                active=bool(d.get("active")),
                scope=DelegationScope(d.get("scope", "NONE")),
                team_ids=d.get("team_ids") or [],
                expires_at=datetime.fromisoformat(exp) if exp else None,
                max_contracts_per_trade=int(d.get("max_contracts_per_trade", 2)),
                max_trades_remaining=int(d.get("max_trades_remaining", 0)),
                note=d.get("note") or "",
            )
        except Exception:
            pass
