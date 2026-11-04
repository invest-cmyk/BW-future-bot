"""
Real-time decision loop.
Re-fetches data and lets the Boss decide every N minutes.
"""

import time
import signal
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.momentum import MomentumAgent
from agents.mean_reversion import MeanReversionAgent
from agents.breakout import BreakoutAgent
from agents.volatility import VolatilityAgent
from agents.seasonality import SeasonalityAgent
from agents.cot import COTAgent
from agents.news_collector import NewsCollectorAgent
from agents.data_collector import DataCollectorAgent
from agents.setup import SetupAgent
from agents.orderflow import OrderFlowAgent
from core.boss import BossAgent
from core.risk import RiskAgent
from data.feed import fetch_history, latest_prices
from brokers.paper import PaperBroker
from config.settings import DEFAULT_UNIVERSE


def build_full_system(broker=None):
    agents = [
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
    risk = RiskAgent()
    boss = BossAgent(agents, risk)
    return boss, broker or PaperBroker()


def run_loop(interval_minutes: float = 15.0, max_cycles: int = None):
    """
    Continuously run decision cycles.
    interval_minutes: how often to re-decide
    max_cycles: stop after N cycles (None = forever)
    """
    print("=" * 60)
    print("  FUTURES AUTOPILOT – REAL-TIME LOOP")
    print(f"  Interval: every {interval_minutes} minutes")
    print("=" * 60)

    boss, broker = build_full_system()
    universe = DEFAULT_UNIVERSE
    cycle = 0
    running = True

    def handle_sig(sig, frame):
        nonlocal running
        print("\nShutdown signal received. Finishing current cycle...")
        running = False

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    while running:
        cycle += 1
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n{'='*50}")
        print(f"Cycle {cycle} | {now}")
        print(f"{'='*50}")

        try:
            market_data = fetch_history(universe, period="3mo", interval="1d")
            prices = latest_prices(market_data)
            broker.update_prices(prices)

            print("Prices:", {s: f"{p:.2f}" for s, p in prices.items()})

            # Boss decides (uses its internal portfolio for now)
            approved = boss.run_cycle(market_data, prices)

            # Optionally mirror decisions to the paper broker
            for sig in approved:
                broker.place_order(sig.symbol, sig.side, sig.size_contracts)

            acct = broker.get_account()
            print(f"Paper Broker → Equity: ${acct['equity']:,.2f} | "
                  f"Cash: ${acct['cash']:,.2f} | Positions: {acct['open_positions']}")

            if approved:
                print(f"Signals taken: {len(approved)}")
            else:
                print("No new trades this cycle.")

        except Exception as e:
            print(f"Cycle error: {e}")

        if max_cycles and cycle >= max_cycles:
            print(f"\nReached max_cycles={max_cycles}. Stopping.")
            break

        if not running:
            break

        sleep_sec = interval_minutes * 60
        print(f"\nSleeping {interval_minutes} min until next cycle... (Ctrl+C to stop)")
        # Interruptible sleep
        for _ in range(int(sleep_sec)):
            if not running:
                break
            time.sleep(1)

    print("\nReal-time loop stopped.")
    print("Final paper account:", broker.get_account())
    return boss, broker


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=15.0, help="Minutes between cycles")
    parser.add_argument("--cycles", type=int, default=None, help="Max cycles (default forever)")
    args = parser.parse_args()
    run_loop(interval_minutes=args.interval, max_cycles=args.cycles)
