"""
Streamlit dashboard for the Futures Multi-Agent Autopilot.
Run with: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from data.feed import fetch_history, latest_prices
from config.settings import DEFAULT_UNIVERSE, CONTRACTS, RISK, SIM
from core.boss import BossAgent
from core.risk import RiskAgent
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
from backtest.engine import Backtester, run_quick_backtest
from brokers.paper import PaperBroker


# Render-safe: must be the first Streamlit command
st.set_page_config(page_title="Futures Autopilot", page_icon="📈", layout="wide")

st.title("📈 Futures Multi-Agent Autopilot")
st.caption("Boss + specialized agents | Simulation & Research")

# Sidebar
st.sidebar.header("Controls")
universe = st.sidebar.multiselect("Universe", list(CONTRACTS.keys()), default=DEFAULT_UNIVERSE)
interval = st.sidebar.slider("Real-time interval (min)", 5, 60, 15)
run_cycle = st.sidebar.button("Run Decision Cycle Now", type="primary")
run_bt = st.sidebar.button("Run Quick Backtest")

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Live / Paper", "Agents", "Backtest", "Risk & Config", "Broker Setup"
])


@st.cache_data(ttl=300)
def load_data(symbols):
    return fetch_history(symbols, period="6mo", interval="1d")


def build_agents():
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


# ---------- Tab 1: Live / Paper ----------
with tab1:
    st.subheader("Current Market & Decision Cycle")

    if not universe:
        st.warning("Select at least one symbol.")
    else:
        data = load_data(tuple(universe))
        prices = latest_prices(data)

        cols = st.columns(len(universe))
        for i, sym in enumerate(universe):
            with cols[i]:
                p = prices.get(sym, 0)
                st.metric(sym, f"{p:,.2f}")

        if run_cycle or "last_result" not in st.session_state:
            boss = BossAgent(build_agents(), RiskAgent())
            paper = PaperBroker()
            paper.update_prices(prices)
            approved = boss.run_cycle(data, prices)
            for s in approved:
                paper.place_order(s.symbol, s.side, s.size_contracts)
            st.session_state["last_result"] = {
                "approved": approved,
                "boss_status": boss.status(),
                "paper": paper.get_account(),
                "positions": paper.get_positions(),
                "time": datetime.utcnow().isoformat()
            }

        res = st.session_state.get("last_result")
        if res:
            st.success(f"Last cycle: {res['time']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Paper Equity", f"${res['paper']['equity']:,.2f}")
            c2.metric("Cash", f"${res['paper']['cash']:,.2f}")
            c3.metric("Open Positions", res['paper']['open_positions'])

            if res["approved"]:
                st.write("**Signals taken**")
                rows = [{
                    "Symbol": s.symbol,
                    "Side": s.side.value,
                    "Contracts": s.size_contracts,
                    "Confidence": round(s.confidence, 2),
                    "Agent": s.agent_id,
                    "Reason": s.reason
                } for s in res["approved"]]
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("No trades taken (no consensus or risk block).")

            if res["positions"]:
                st.write("**Open Positions**")
                pos_rows = [{
                    "Symbol": s,
                    "Side": p.side.value,
                    "Qty": p.qty,
                    "Avg Price": round(p.avg_price, 2),
                    "Unrealized": round(p.unrealized_pnl, 2)
                } for s, p in res["positions"].items()]
                st.dataframe(pd.DataFrame(pos_rows), use_container_width=True)


# ---------- Tab 2: Agents ----------
with tab2:
    st.subheader("Active Agents")
    agents = build_agents()
    for a in agents:
        st.markdown(f"**{a.agent_id}** (`{a.__class__.__name__}`) — weight `{a.weight}` — {'🟢 enabled' if a.enabled else '🔴 disabled'}")
    st.markdown("""
    | Agent | Style |
    |-------|-------|
    | Momentum | Trend (ROC + MA) |
    | Mean-Reversion | Z-score |
    | Breakout | Donchian |
    | Volatility | Regime / expansion |
    | Seasonality | Month + day-of-week bias |
    | COT | Crowded positioning proxy |
    | News Collector | Live RSS headlines + report to Boss |
    | Data Collector | Prices, vol, trend, calendar, roll notes |
    | Setup Agent | Multi-factor setups graded A/B/C + report |
    | Order-Flow | Volume + pressure proxy |
    """)


# ---------- Tab 3: Backtest ----------
with tab3:
    st.subheader("Backtest Engine")
    if run_bt:
        with st.spinner("Running backtest (this may take a moment)..."):
            try:
                result = run_quick_backtest(universe or DEFAULT_UNIVERSE, period="1y")
                st.session_state["bt_result"] = result
            except Exception as e:
                st.error(str(e))

    if "bt_result" in st.session_state:
        r = st.session_state["bt_result"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Final Equity", f"${r.final_equity:,.2f}")
        c2.metric("Return", f"{r.total_return_pct:.2f}%")
        c3.metric("Max DD", f"{r.max_drawdown_pct:.2f}%")
        c4.metric("Sharpe", f"{r.sharpe:.2f}")

        c5, c6, c7 = st.columns(3)
        c5.metric("Trades", r.n_trades)
        c6.metric("Win Rate", f"{r.win_rate:.1f}%")
        c7.metric("Profit Factor", f"{r.profit_factor:.2f}")

        st.line_chart(r.equity_curve)
    else:
        st.info("Click **Run Quick Backtest** in the sidebar.")


# ---------- Tab 4: Risk & Config ----------
with tab4:
    st.subheader("Risk Parameters")
    st.json(RISK)
    st.subheader("Simulation Settings")
    st.json(SIM)
    st.subheader("Contract Specs (selected)")
    for s in (universe or DEFAULT_UNIVERSE):
        if s in CONTRACTS:
            c = CONTRACTS[s]
            st.write(f"**{c.symbol}** – {c.name} | Mult ${c.multiplier} | Tick ${c.tick_value} | Day margin ~${c.margin_day:,.0f}")


# ---------- Tab 5: Broker Setup ----------
with tab5:
    st.subheader("Broker Connections")
    st.markdown("""
    ### Paper Broker (built-in)
    Fully functional simulation. Used by default.

    ### Interactive Brokers
    - Install: `pip install ib_insync`
    - Start TWS or IB Gateway with API enabled (paper port usually 7497)
    - See `brokers/ibkr_stub.py` for the skeleton

    ### Tradovate
    - Popular for futures paper & live
    - Get API credentials from Tradovate
    - See `brokers/tradovate_stub.py`

    ### Real-time loop
    ```bash
    python runners/realtime.py --interval 15
    ```
    """)

st.sidebar.markdown("---")
st.sidebar.caption("Simulation only. Futures are leveraged. Trade at your own risk.")
