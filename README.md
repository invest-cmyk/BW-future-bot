# Futures Multi-Agent Autopilot

A complete **multi-agent futures trading system** with Boss orchestration, risk management, real-time loop, backtesting, paper broker, and Streamlit dashboard.

## Architecture

```
Boss Agent (Orchestrator)
├── Momentum Agent
├── Mean-Reversion Agent
├── Breakout Agent
├── Volatility Agent
├── Seasonality Agent
├── COT (positioning) Agent
├── News Collector Agent (live RSS + report)
├── Order-Flow Proxy Agent
└── Risk Agent (leverage-aware)
```

Plus:
- Real-time decision loop
- Paper trading broker (fully working)
- IBKR & Tradovate stubs (ready to wire)
- Walk-forward capable backtester
- Streamlit dashboard

## Quick Start

```bash
cd futures_autopilot
pip install -r requirements.txt

# Single decision cycle
python main.py

# Real-time loop every 15 minutes
python main.py --realtime 15

# Quick backtest
python main.py --backtest

# Dashboard
python main.py --dashboard
# or: streamlit run dashboard/app.py
```

## Project Structure

```
futures_autopilot/
├── main.py                 # CLI entry
├── config/settings.py      # Contracts, risk, universe
├── core/
│   ├── models.py
│   ├── risk.py
│   └── boss.py
├── agents/                 # 8 specialized agents
├── brokers/
│   ├── paper.py            # Working paper broker
│   ├── ibkr_stub.py
│   └── tradovate_stub.py
├── runners/realtime.py     # Continuous loop
├── backtest/engine.py      # Backtest + walk-forward
├── dashboard/app.py        # Streamlit UI
└── data/feed.py
```

## Supported Futures

ES, NQ, YM, RTY, CL, GC, SI, 6E, ZB, ZN  
(edit `config/settings.py` to change)

## Important Warnings

- **Simulation / research only** by default.
- Futures are highly leveraged. Losses can exceed deposits.
- Always paper-trade extensively.
- You are responsible for regulatory compliance.
- News/LLM and COT agents currently use proxies – replace with real data feeds for production.

## Next Steps You Can Request

- Wire real IBKR or Tradovate credentials
- Add proper CFTC COT downloader
- Connect a real news API + LLM for sentiment
- Intraday (5m / 15m) data + loop
- Parameter optimization in walk-forward
- Telegram / Discord alerts
