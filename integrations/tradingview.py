"""
TradingView integration
=======================
TradingView does not expose a full "connect my bot" API for arbitrary platforms.
The standard, reliable link is:

  TradingView Alert  →  Webhook POST (JSON)  →  this platform  →  CEO desk

You create alerts on TradingView (Pine or chart UI). Each alert sends a webhook
to our server. We parse it into a TeamRecommendation and queue it for the CEO
(or auto-approve under delegation).

Supported payload styles:
  1) Simple JSON you define in the alert message
  2) Common key names: symbol, side/action, qty, price, strategy, comment
"""

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import re
import uuid

from teams.team import TeamRecommendation, Action
from teams.roster import TEAM_DEFS


# Map TradingView symbols → our team symbols
TV_SYMBOL_MAP = {
    "NQ": "NQ", "NAS100": "NQ", "NASDAQ": "NQ", "NQ1!": "NQ", "MNQ": "NQ",
    "ES": "ES", "SPX": "ES", "SP500": "ES", "ES1!": "ES", "MES": "ES",
    "YM": "YM", "DJ30": "YM", "DJI": "YM", "YM1!": "YM", "MYM": "YM",
    "RTY": "RTY", "RUSSELL": "RTY", "RTY1!": "RTY", "M2K": "RTY",
    "GC": "GC", "GOLD": "GC", "XAU": "GC", "GC1!": "GC", "MGC": "GC",
    "CL": "CL", "OIL": "CL", "WTI": "CL", "CL1!": "CL", "MCL": "CL",
}

SYMBOL_TO_TEAM = {sym: (tid, name) for tid, name, sym in TEAM_DEFS}


def normalize_symbol(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().upper()
    # strip exchange prefixes: CME_NQ1!, NYMEX:CL1!, etc.
    s = s.replace(":", " ").replace("_", " ").replace("/", " ")
    parts = s.split()
    for p in reversed(parts):
        p = p.replace("!", "")
        if p in TV_SYMBOL_MAP:
            return TV_SYMBOL_MAP[p]
        # root letters only
        root = re.sub(r"[0-9].*$", "", p)
        if root in TV_SYMBOL_MAP:
            return TV_SYMBOL_MAP[root]
    if s in TV_SYMBOL_MAP:
        return TV_SYMBOL_MAP[s]
    return None


def normalize_action(raw: Any) -> Optional[Action]:
    if raw is None:
        return None
    t = str(raw).strip().upper()
    if t in ("BUY", "LONG", "ENTER_LONG", "BULL"):
        return Action.BUY
    if t in ("SELL", "SHORT", "ENTER_SHORT", "BEAR"):
        return Action.SELL
    if t in ("CLOSE", "EXIT", "FLAT", "CLOSE_LONG", "CLOSE_SHORT"):
        return Action.EXIT
    if t in ("HOLD", "NONE"):
        return Action.HOLD
    return None


def parse_tradingview_webhook(payload: Dict[str, Any]) -> TeamRecommendation:
    """
    Convert TradingView webhook JSON into a TeamRecommendation for the CEO.

    Recommended alert message (JSON mode) on TradingView:

    {
      "symbol": "{{ticker}}",
      "action": "BUY",
      "qty": 1,
      "price": {{close}},
      "strategy": "{{strategy.order.comment}}",
      "secret": "YOUR_WEBHOOK_SECRET"
    }

    Or free-text that includes SYMBOL and BUY/SELL.
    """
    # Allow nested "data" wrappers
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    symbol_raw = (
        data.get("symbol")
        or data.get("ticker")
        or data.get("sym")
        or data.get("instrument")
        or ""
    )
    action_raw = (
        data.get("action")
        or data.get("side")
        or data.get("order")
        or data.get("signal")
        or data.get("direction")
    )
    qty = data.get("qty") or data.get("quantity") or data.get("size") or 1
    try:
        qty = max(1, int(float(qty)))
    except (TypeError, ValueError):
        qty = 1

    price = data.get("price") or data.get("close") or data.get("entry")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None

    stop = data.get("stop") or data.get("sl")
    target = data.get("target") or data.get("tp")
    try:
        stop = float(stop) if stop is not None else None
    except (TypeError, ValueError):
        stop = None
    try:
        target = float(target) if target is not None else None
    except (TypeError, ValueError):
        target = None

    strategy = str(data.get("strategy") or data.get("comment") or data.get("message") or "TradingView alert")
    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.70
        confidence = max(0.0, min(confidence, 0.99))
    except (TypeError, ValueError):
        confidence = 0.70

    symbol = normalize_symbol(str(symbol_raw))
    action = normalize_action(action_raw)

    # Fallback: parse free-text "message" / "text"
    if (not symbol or not action) and isinstance(data.get("message") or data.get("text"), str):
        text = (data.get("message") or data.get("text") or "").upper()
        if not action:
            if "BUY" in text or "LONG" in text:
                action = Action.BUY
            elif "SELL" in text or "SHORT" in text:
                action = Action.SELL
            elif "EXIT" in text or "CLOSE" in text:
                action = Action.EXIT
        if not symbol:
            for key in TV_SYMBOL_MAP:
                if re.search(rf"\b{re.escape(key)}\b", text):
                    symbol = TV_SYMBOL_MAP[key]
                    break

    if not symbol:
        symbol = "ES"  # last resort; CEO will still see it
    if not action:
        action = Action.HOLD

    team_id, team_name = SYMBOL_TO_TEAM.get(symbol, ("team_tv", f"TradingView → {symbol}"))

    rid = str(uuid.uuid4())[:8]
    return TeamRecommendation(
        team_id=team_id,
        team_name=f"{team_name} (TradingView)",
        symbol=symbol,
        action=action,
        confidence=confidence,
        size_contracts=qty,
        entry=price,
        stop=stop,
        target=target,
        reason=f"TradingView: {strategy}",
        agent_votes={"tradingview": action.value},
        recommendation_id=rid,
        status="PENDING",
        timestamp=datetime.now(timezone.utc),
    )


# Example alert message to paste into TradingView (Webhook message field)
TV_ALERT_TEMPLATE = '''
{
  "secret": "CHANGE_ME",
  "symbol": "{{ticker}}",
  "action": "BUY",
  "qty": 1,
  "price": {{close}},
  "strategy": "My Pine strategy",
  "confidence": 0.75
}
'''.strip()
