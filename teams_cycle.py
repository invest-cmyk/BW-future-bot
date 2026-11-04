"""
Run all 6 teams → report to CEO desk.
Approved (or delegated) recommendations can be executed by the Boss/paper broker.
"""

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from teams.roster import build_teams, team_symbols
from teams.team import TeamRecommendation, Action
from ceo.office import CEOOffice
from data.feed import fetch_history, latest_prices
from brokers.paper import PaperBroker
from core.models import Side
from config.settings import SIM


def run_teams_cycle(
    ceo: Optional[CEOOffice] = None,
    execute_approved: bool = True,
    equity: float = None,
) -> List[TeamRecommendation]:
    """
    1. Fetch data for all team symbols
    2. Each team runs only on its symbol
    3. Recommendations go to CEO office
    4. If delegated or already approved path → paper execute
    """
    ceo = ceo or CEOOffice()
    equity = equity or SIM["starting_equity"]
    symbols = team_symbols()

    print("=" * 60)
    print("  6-TEAM CYCLE → CEO DESK")
    print("=" * 60)
    print(ceo.delegation.pretty())
    print(f"Universe: {symbols}\n")

    print("Fetching market data...")
    market_data = fetch_history(symbols, period="6mo", interval="1d")
    prices = latest_prices(market_data)
    for s, p in prices.items():
        print(f"  {s}: {p:,.2f}")

    teams = build_teams()
    recommendations: List[TeamRecommendation] = []

    print("\n--- Teams working ---\n")
    for team in teams:
        print(f"▶ {team.team_name} analyzing {team.symbol}...")
        rec = team.run(market_data, prices, equity=equity)
        if rec is None:
            print(f"  (no data for {team.symbol})")
            continue
        recommendations.append(rec)
        # Submit to CEO
        ceo.receive(rec)
        if rec.action != Action.HOLD:
            print(rec.pretty())
            print()

    print("\n" + ceo.briefing())

    # Execute auto-approved (delegation) trades
    if execute_approved:
        broker = PaperBroker(starting_equity=equity)
        broker.update_prices(prices)
        executed = 0
        for rec in recommendations:
            if rec.status == "APPROVED" and rec.action in (Action.BUY, Action.SELL):
                side = Side.LONG if rec.action == Action.BUY else Side.SHORT
                result = broker.place_order(rec.symbol, side, rec.size_contracts)
                if result.get("status") == "filled":
                    rec.status = "EXECUTED"
                    executed += 1
                    print(f"⚡ Executed {rec.action.value} {rec.size_contracts} {rec.symbol} @ {result.get('fill_price')}")
        if executed:
            print(f"\nPaper account: {broker.get_account()}")

    return recommendations


def interactive_ceo_session():
    """
    CLI for the CEO:
      - run cycle
      - list pending
      - approve / reject by id
      - grant / revoke delegation
    """
    ceo = CEOOffice()
    print(ceo.briefing())
    print("""
CEO COMMANDS:
  run              – run all 6 teams and collect recommendations
  pending          – list pending approvals
  approve <id>     – approve one recommendation
  reject <id>      – reject one recommendation
  approve_all      – approve everything pending
  reject_all       – reject everything pending
  delegate <min>   – grant Boss autopilot for N minutes (all teams)
  delegate_team <team_id> <min>  – grant for one team only
  revoke           – revoke delegation
  status           – show desk briefing
  quit             – exit
""")
    while True:
        try:
            cmd = input("CEO> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not cmd:
            continue
        parts = cmd.split()
        op = parts[0].lower()

        if op in ("quit", "exit", "q"):
            break
        elif op == "run":
            run_teams_cycle(ceo=ceo, execute_approved=True)
        elif op == "pending":
            for r in ceo.list_pending():
                print(r.pretty())
                print()
            if not ceo.list_pending():
                print("Nothing pending.")
        elif op == "approve" and len(parts) >= 2:
            ceo.approve(parts[1])
        elif op == "reject" and len(parts) >= 2:
            ceo.reject(parts[1])
        elif op == "approve_all":
            ceo.approve_all()
        elif op == "reject_all":
            ceo.reject_all()
        elif op == "delegate" and len(parts) >= 2:
            mins = int(parts[1])
            max_c = int(parts[2]) if len(parts) > 2 else 2
            max_t = int(parts[3]) if len(parts) > 3 else 10
            ceo.grant_delegation(minutes=mins, scope="ALL_TEAMS",
                                 max_contracts=max_c, max_trades=max_t)
        elif op == "delegate_team" and len(parts) >= 3:
            tid, mins = parts[1], int(parts[2])
            ceo.grant_delegation(minutes=mins, scope="SINGLE_TEAM",
                                 team_ids=[tid], max_contracts=2, max_trades=5)
        elif op == "revoke":
            ceo.revoke_delegation()
        elif op == "status":
            print(ceo.briefing())
        else:
            print("Unknown command. Type: run | pending | approve <id> | reject <id> | "
                  "approve_all | delegate <minutes> | revoke | status | quit")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true", help="CEO interactive desk")
    parser.add_argument("--delegate", type=int, metavar="MINUTES",
                        help="Grant delegation then run one cycle")
    args = parser.parse_args()

    if args.interactive:
        interactive_ceo_session()
    else:
        ceo = CEOOffice()
        if args.delegate:
            ceo.grant_delegation(minutes=args.delegate, max_trades=20)
        run_teams_cycle(ceo=ceo)
