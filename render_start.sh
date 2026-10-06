#!/usr/bin/env bash
# Render start command: runs the FastAPI backend privately on 127.0.0.1:8088
# and serves the Streamlit dashboard on Render's public $PORT.
set -euo pipefail

API="http://127.0.0.1:8088"

uvicorn app.main:app --host 127.0.0.1 --port 8088 &

for _ in $(seq 1 60); do
  curl -sf "$API/health" >/dev/null && break
  sleep 1
done

# Render's disk is ephemeral, so the index is gone after every restart or
# deploy. Index the bundled ShopFlow demo backend so the dashboard is ready to demo.
if ! curl -sf "$API/api/v1/index/status" | grep -q '"indexed":true'; then
  # Relative to the API's working directory (the repo root)
  curl -sf -X POST -G --data-urlencode "directory=sample_backend" "$API/api/v1/index/path" >/dev/null \
    && echo "Indexed sample_backend/" || echo "Auto-index failed; build it from the Codebase page"
fi

exec streamlit run frontend/streamlit_app.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
