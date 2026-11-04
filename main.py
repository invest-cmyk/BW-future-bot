#!/usr/bin/env python3
"""
Futures Multi-Agent Autopilot – CLI entry point

Usage examples:
  python main.py                     # single decision cycle
  python main.py --realtime 15       # real-time loop every 15 min
  python main.py --backtest          # quick backtest
  python main.py --dashboard         # launch Streamlit UI
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents import (
    MomentumAgent, MeanReversionAgent, BreakoutAgent, VolatilityAgent,
    SeasonalityAgent, COTAgent, NewsCollectorAgent, DataCollectorAgent, SetupAgent, OrderFlowAgent
)
from core.boss import BossAgent
from core.risk import RiskAgent
from data.feed import fetch_history, latest_prices
from config.settings import DEFAULT_UNIVERSE
from backtest.engine import run_quick_backtest


def build_full_agents():
    return [
        MomentumAgent("momentum_1", weight=1.0),
        MeanReversionAgent("meanrev_1", weight=0.75),
        BreakoutAgent("breakout_1", weight=0.9),
        VolatilityAgent("vol_1", weight=0.6),
        SeasonalityAgent("seasonality_1", weight=0.45),
        COTAgent("cot_1", weight=0.55),
        NewsCollectorAgent("news_collector_1", weight=0.65),
        DataCollectorAgent("data_collector_1", weight=0.4),
        SetupAgent("setup_1", weight=0.95),
        OrderFlowAgent("orderflow_1", weight=0.6),
    ]


def single_cycle():
    print("=" * 60)
    print("  FUTURES MULTI-AGENT AUTOPILOT – Single Cycle")
    print("=" * 60)

    universe = DEFAULT_UNIVERSE
    print(f"Universe: {universe}")
    print("Fetching market data...")
    market_data = fetch_history(universe, period="6mo", interval="1d")
    prices = latest_prices(market_data)

    print("Latest prices:")
    for s, p in prices.items():
        print(f"  {s}: {p:,.2f}")

    boss = BossAgent(build_full_agents(), RiskAgent())
    print("\n🚀 Running decision cycle with all agents...\n")
    approved = boss.run_cycle(market_data, prices)

    print("\n" + "-" * 40)
    print("Boss Status:")
    for k, v in boss.status().items():
        print(f"  {k}: {v}")

    if approved:
        print(f"\nApproved signals: {len(approved)}")
        for s in approved:
            print(f"  → {s.side.value} {s.size_contracts} {s.symbol} "
                  f"(conf={s.confidence:.2f}) [{s.agent_id}] | {s.reason}")
    else:
        print("\nNo trades taken this cycle.")

    print("\n✅ Done. (Simulation only)")


def main():
    parser = argparse.ArgumentParser(description="Futures Multi-Agent Autopilot")
    parser.add_argument("--realtime", type=float, metavar="MINUTES",
                        help="Run continuous loop every N minutes")
    parser.add_argument("--cycles", type=int, default=None,
                        help="Max cycles for realtime mode")
    parser.add_argument("--backtest", action="store_true",
                        help="Run a quick 1-year backtest")
    parser.add_argument("--dashboard", action="store_true",
                        help="Launch Streamlit dashboard")
    parser.add_argument("--teams", action="store_true",
                        help="Run 6 symbol teams and report to CEO desk")
    parser.add_argument("--ceo", action="store_true",
                        help="Interactive CEO desk (approve/reject/delegate)")
    parser.add_argument("--delegate", type=int, metavar="MINUTES",
                        help="With --teams: grant Boss autopilot for N minutes")
    parser.add_argument("--tradingview", action="store_true",
                        help="Start TradingView webhook server")
    args = parser.parse_args()

    if args.tradingview:
        from runners.tv_webhook_server import app
        import uvicorn, os
        port = int(os.getenv("PORT", "8080"))
        print("TradingView webhook server → POST /webhook/tradingview")
        uvicorn.run(app, host="0.0.0.0", port=port)
        return

    if args.ceo:
        from runners.teams_cycle import interactive_ceo_session
        interactive_ceo_session()
        return

    if args.teams:
        from runners.teams_cycle import run_teams_cycle
        from ceo.office import CEOOffice
        ceo = CEOOffice()
        if args.delegate:
            ceo.grant_delegation(minutes=args.delegate, max_trades=20)
        run_teams_cycle(ceo=ceo)
        return

    if args.dashboard:
        import subprocess
        app = Path(__file__).parent / "dashboard" / "app.py"
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(app), "--server.headless", "true"])
        return

    if args.backtest:
        run_quick_backtest()
        return

    if args.realtime is not None:
        from runners.realtime import run_loop
        run_loop(interval_minutes=args.realtime, max_cycles=args.cycles)
        return

    single_cycle()


if __name__ == "__main__":
    main()
