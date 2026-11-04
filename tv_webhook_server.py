#!/usr/bin/env python3
"""
TradingView Webhook Server
==========================
Receives alert webhooks from TradingView and queues them on the CEO desk.

Run:
  export TV_WEBHOOK_SECRET="your-secret"
  python runners/tv_webhook_server.py
  # or: uvicorn runners.tv_webhook_server:app --host 0.0.0.0 --port 8080

TradingView alert URL (after you expose the server):
  https://YOUR_PUBLIC_HOST/webhook/tradingview

Local test:
  curl -X POST http://127.0.0.1:8080/webhook/tradingview \\
    -H "Content-Type: application/json" \\
    -d '{"secret":"your-secret","symbol":"NQ","action":"BUY","qty":1,"price":21000}'
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn

from integrations.tradingview import parse_tradingview_webhook, TV_ALERT_TEMPLATE
from ceo.office import CEOOffice
from teams.team import Action
from brokers.paper import PaperBroker
from core.models import Side
from data.feed import latest_prices, fetch_history
from teams.roster import team_symbols

app = FastAPI(title="Futures Autopilot – TradingView Webhook", version="1.0")
ceo = CEOOffice()
WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "CHANGE_ME")
AUTO_EXECUTE_DELEGATED = os.getenv("TV_AUTO_EXECUTE", "1") == "1"


def _check_secret(payload: dict, header_secret: str = None):
    secret = header_secret or payload.get("secret") or payload.get("passphrase")
    if WEBHOOK_SECRET and WEBHOOK_SECRET != "CHANGE_ME":
        if secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")


@app.get("/")
def root():
    return {
        "service": "Futures Autopilot TradingView bridge",
        "webhook": "POST /webhook/tradingview",
        "ceo_pending": "GET /ceo/pending",
        "health": "GET /health",
        "delegation": ceo.delegation.pretty(),
    }


@app.get("/health")
def health():
    return {"ok": True, "pending": len(ceo.list_pending()), "delegation": ceo.delegation.pretty()}


@app.get("/ceo/pending")
def ceo_pending():
    return {
        "pending": [
            {
                "id": r.recommendation_id,
                "team": r.team_name,
                "symbol": r.symbol,
                "action": r.action.value,
                "confidence": r.confidence,
                "size": r.size_contracts,
                "entry": r.entry,
                "reason": r.reason,
            }
            for r in ceo.list_pending()
        ],
        "delegation": ceo.delegation.pretty(),
    }


@app.post("/ceo/approve/{rec_id}")
def ceo_approve(rec_id: str):
    rec = ceo.approve(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")
    _maybe_execute(rec)
    return {"status": rec.status, "id": rec.recommendation_id}


@app.post("/ceo/reject/{rec_id}")
def ceo_reject(rec_id: str):
    rec = ceo.reject(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")
    return {"status": rec.status, "id": rec.recommendation_id}


@app.post("/ceo/delegate")
async def ceo_delegate(request: Request):
    body = await request.json()
    minutes = int(body.get("minutes", 60))
    max_contracts = int(body.get("max_contracts", 1))
    max_trades = int(body.get("max_trades", 5))
    g = ceo.grant_delegation(
        minutes=minutes,
        scope="ALL_TEAMS",
        max_contracts=max_contracts,
        max_trades=max_trades,
        note="Granted via API",
    )
    return {"delegation": g.pretty()}


@app.post("/ceo/revoke")
def ceo_revoke():
    ceo.revoke_delegation()
    return {"delegation": ceo.delegation.pretty()}


@app.get("/tradingview/template")
def tv_template():
    """JSON template to paste into TradingView alert webhook message."""
    return {
        "instructions": [
            "1. On TradingView, create an Alert on your chart or strategy.",
            "2. Enable Webhook URL → https://YOUR_HOST/webhook/tradingview",
            "3. Paste the JSON template below into the Message field.",
            "4. Set action to BUY or SELL (or use strategy placeholders).",
            "5. Set secret to the same TV_WEBHOOK_SECRET as this server.",
        ],
        "message_template": TV_ALERT_TEMPLATE,
        "placeholders": {
            "{{ticker}}": "Symbol",
            "{{close}}": "Last price",
            "{{strategy.order.action}}": "strategy BUY/SELL (strategy alerts)",
            "{{strategy.order.contracts}}": "size (strategy alerts)",
        },
    }


@app.post("/webhook/tradingview")
async def tradingview_webhook(
    request: Request,
    x_tv_secret: str = Header(None, alias="X-TV-Secret"),
):
    """
    Main endpoint for TradingView alerts.
    """
    try:
        payload = await request.json()
    except Exception:
        # TradingView sometimes sends form/text
        body = await request.body()
        text = body.decode("utf-8", errors="ignore")
        payload = {"message": text, "text": text}

    if not isinstance(payload, dict):
        payload = {"message": str(payload)}

    _check_secret(payload, x_tv_secret)

    rec = parse_tradingview_webhook(payload)
    ceo.receive(rec)

    executed = False
    if rec.status == "APPROVED" and AUTO_EXECUTE_DELEGATED:
        executed = _maybe_execute(rec)

    return JSONResponse({
        "ok": True,
        "recommendation_id": rec.recommendation_id,
        "symbol": rec.symbol,
        "action": rec.action.value,
        "status": rec.status,
        "executed": executed,
        "team": rec.team_name,
        "message": "Queued for CEO" if rec.status == "PENDING" else rec.status,
    })


def _maybe_execute(rec) -> bool:
    if rec.action not in (Action.BUY, Action.SELL):
        return False
    if rec.status not in ("APPROVED", "EXECUTED"):
        return False
    try:
        symbols = team_symbols()
        data = fetch_history(symbols, period="5d", interval="1d")
        prices = latest_prices(data)
        broker = PaperBroker()
        broker.update_prices(prices)
        side = Side.LONG if rec.action == Action.BUY else Side.SHORT
        result = broker.place_order(rec.symbol, side, rec.size_contracts)
        if result.get("status") == "filled":
            rec.status = "EXECUTED"
            print(f"⚡ TV→executed {rec.action.value} {rec.size_contracts} {rec.symbol}")
            return True
    except Exception as e:
        print(f"Execute failed: {e}")
    return False


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"TradingView webhook server on http://0.0.0.0:{port}")
    print(f"Webhook URL path: POST /webhook/tradingview")
    print(f"Secret configured: {WEBHOOK_SECRET != 'CHANGE_ME'}")
    print(ceo.delegation.pretty())
    uvicorn.run(app, host="0.0.0.0", port=port)
