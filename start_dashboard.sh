#!/usr/bin/env bash
# Render start script for Streamlit dashboard
set -e
cd "$(dirname "$0")"

export STREAMLIT_SERVER_HEADLESS=true
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Render provides $PORT
PORT="${PORT:-10000}"

echo "Starting Streamlit on 0.0.0.0:${PORT}"
exec streamlit run dashboard/app.py \
  --server.port="${PORT}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false
