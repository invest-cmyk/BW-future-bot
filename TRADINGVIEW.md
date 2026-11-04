# Connect TradingView to this platform

TradingView does not offer a direct "link this Python bot" API.
The standard integration is **Alerts → Webhook**.

```
TradingView chart / Pine strategy
        ↓  Alert fires
   Webhook POST (JSON)
        ↓
  This server  /webhook/tradingview
        ↓
  CEO desk (you approve)  OR  time-limited delegation
        ↓
  Paper / broker execution
```

## 1. Start the webhook server

```bash
cd futures_autopilot
pip install -r requirements.txt

export TV_WEBHOOK_SECRET="pick-a-long-random-secret"
python main.py --tradingview
# listens on http://0.0.0.0:8080
```

## 2. Expose a public HTTPS URL

TradingView requires a public URL (not localhost).

Options:
- **ngrok** (quick test): `ngrok http 8080` → use the https URL
- **Render / Railway / VPS** with HTTPS

Webhook URL to put in TradingView:

```text
https://YOUR_PUBLIC_HOST/webhook/tradingview
```

## 3. Create a TradingView alert

1. Open chart (e.g. NQ1!, ES1!, GC1!, CL1!).
2. Alert → Conditions (price cross, Pine strategy order, etc.).
3. Notifications → **Webhook URL** → paste your URL.
4. Message body (JSON):

```json
{
  "secret": "pick-a-long-random-secret",
  "symbol": "{{ticker}}",
  "action": "BUY",
  "qty": 1,
  "price": {{close}},
  "strategy": "My setup",
  "confidence": 0.75
}
```

For **strategy alerts**, you can use:

```json
{
  "secret": "pick-a-long-random-secret",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "qty": "{{strategy.order.contracts}}",
  "price": {{close}},
  "strategy": "{{strategy.order.comment}}"
}
```

Note: `action` must resolve to BUY or SELL (TradingView strategy uses `buy`/`sell` – our parser accepts BUY/SELL/LONG/SHORT).

## 4. CEO approval flow

Default: alert → **PENDING** on CEO desk.

```bash
python main.py --ceo
# pending / approve <id> / reject <id>
```

Or via HTTP:

```bash
curl http://localhost:8080/ceo/pending
curl -X POST http://localhost:8080/ceo/approve/REC_ID
```

## 5. Optional: let Boss auto-trade TV alerts for a limited time

```bash
curl -X POST http://localhost:8080/ceo/delegate \
  -H "Content-Type: application/json" \
  -d '{"minutes": 60, "max_contracts": 1, "max_trades": 5}'
```

While delegation is active, TradingView alerts for mapped symbols can auto-approve (and paper-execute if `TV_AUTO_EXECUTE=1`).

## 6. Symbol mapping

| TradingView ticker examples | Team symbol |
|----------------------------|-------------|
| NQ1!, MNQ, NAS100          | NQ          |
| ES1!, MES                  | ES          |
| YM1!, MYM                  | YM          |
| RTY1!, M2K                 | RTY         |
| GC1!, MGC                  | GC          |
| CL1!, MCL                  | CL          |

## 7. Test without TradingView

```bash
curl -X POST http://127.0.0.1:8080/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"pick-a-long-random-secret","symbol":"NQ","action":"BUY","qty":1,"price":21000,"strategy":"test"}'
```

## Security

- Always set `TV_WEBHOOK_SECRET` and the same value in the alert JSON.
- Prefer HTTPS public endpoints only.
- Keep CEO approval on until you trust the alert → execution path.
- Start with paper broker only.
