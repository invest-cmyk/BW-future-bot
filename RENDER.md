# Deploy on Render.com

Two useful services:

1. **Dashboard** – Streamlit UI (teams / backtest / status)
2. **TradingView webhook** (optional) – receives TV alerts 24/7

---

## A. Put the code on GitHub first

1. Create a GitHub repo (e.g. `futures-autopilot`).
2. Upload project so **repo root** contains:

```text
dashboard/app.py
main.py
requirements.txt
agents/
teams/
ceo/
runners/
...
```

3. Push to `main`.

---

## B. Deploy the Streamlit dashboard

1. Go to [https://dashboard.render.com](https://dashboard.render.com) and sign up (GitHub login is fine).
2. **New +** → **Web Service**.
3. Connect the GitHub repo `futures-autopilot`.
4. Settings:

| Field | Value |
|--------|--------|
| Name | `futures-autopilot-dashboard` |
| Region | closest to you |
| Runtime | **Python** |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `streamlit run dashboard/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true` |
| Instance | **Free** |

5. Environment variables (optional):

| Key | Value |
|-----|--------|
| `PYTHON_VERSION` | `3.11.9` |
| `BROKER` | `paper` |

6. Click **Create Web Service**.
7. Wait for the build (green **Live**).
8. Open the URL, e.g. `https://futures-autopilot-dashboard.onrender.com`.

**Free tier note:** the service sleeps after ~15 minutes idle. First load after sleep can take 30–60 seconds.

---

## C. Deploy TradingView webhook (optional second service)

1. **New +** → **Web Service** again (same repo).
2. Settings:

| Field | Value |
|--------|--------|
| Name | `futures-tv-webhook` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn runners.tv_webhook_server:app --host 0.0.0.0 --port $PORT` |

3. Environment variables:

| Key | Value |
|-----|--------|
| `PYTHON_VERSION` | `3.11.9` |
| `TV_WEBHOOK_SECRET` | your long secret |
| `TV_AUTO_EXECUTE` | `0` (keep CEO approval) |
| `BROKER` | `paper` |

4. Deploy → URL like `https://futures-tv-webhook.onrender.com`.

5. In TradingView alert **Webhook URL**:

```text
https://futures-tv-webhook.onrender.com/webhook/tradingview
```

6. Alert JSON message must include the same secret:

```json
{
  "secret": "your long secret",
  "symbol": "{{ticker}}",
  "action": "BUY",
  "qty": 1,
  "price": {{close}},
  "strategy": "TV setup"
}
```

7. Test:

```bash
curl https://futures-tv-webhook.onrender.com/health
curl -X POST https://futures-tv-webhook.onrender.com/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"your long secret","symbol":"NQ","action":"BUY","qty":1,"price":21000}'
```

---

## D. Blueprint deploy (optional)

If `render.yaml` is in the repo root:

1. Render → **New +** → **Blueprint**
2. Select the repo
3. Render creates both services from `render.yaml`
4. Set `TV_WEBHOOK_SECRET` when prompted

---

## E. Common problems

| Problem | Fix |
|---------|-----|
| Build fails on Python version | Set env `PYTHON_VERSION` = `3.11.9` |
| App crashes on start | Start command must use `$PORT` and `0.0.0.0` |
| Module not found | Repo root must contain `dashboard/`, `agents/`, etc. |
| Site sleeps | Free tier; upgrade or ping with a cron health check |
| TradingView timeout | Free service asleep – open the webhook URL once, or use a paid always-on instance |

---

## F. After it’s live

- Dashboard: run cycles / backtest in the browser  
- Webhook: TV alerts → CEO pending (`/ceo/pending`)  
- Approve: `POST /ceo/approve/{id}` or local `python main.py --ceo`  

Keep **BROKER=paper** until you intentionally wire IBKR/Tradovate.
