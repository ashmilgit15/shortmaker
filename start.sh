#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"
BGUTIL_PORT="${BGUTIL_PORT:-4416}"
BGUTIL_SERVER="/opt/bgutil-ytdlp-pot-provider/server/build/main.js"
BGUTIL_MAX_RETRIES=10

# Start bgutil PO Token HTTP server in the background if available
start_bgutil() {
  if [ ! -f "$BGUTIL_SERVER" ] || ! command -v node >/dev/null 2>&1; then
    echo "[shortmaker] bgutil not available — downloads will rely on player client fallbacks."
    return 1
  fi

  echo "[shortmaker] Starting bgutil PO Token server on port ${BGUTIL_PORT}..."
  TOKEN_TTL="${SHORTMAKER_YTDLP_POT_TOKEN_TTL:-12}" \
  node "$BGUTIL_SERVER" --port "${BGUTIL_PORT}" &
  BGUTIL_PID=$!
  echo "[shortmaker] bgutil process started (PID $BGUTIL_PID)"

  # Wait until the server is actually responding
  i=0
  while [ $i -lt $BGUTIL_MAX_RETRIES ]; do
    if curl -sf "http://127.0.0.1:${BGUTIL_PORT}/ping" >/dev/null 2>&1; then
      echo "[shortmaker] bgutil PO Token server is healthy on port ${BGUTIL_PORT}."
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done

  echo "[shortmaker] WARNING: bgutil server did not respond after ${BGUTIL_MAX_RETRIES}s."
  return 0
}

# Monitor bgutil in the background — restart if it crashes
monitor_bgutil() {
  while true; do
    sleep 30
    if [ -n "${BGUTIL_PID:-}" ]; then
      if ! kill -0 "$BGUTIL_PID" 2>/dev/null; then
        echo "[shortmaker] bgutil server crashed — restarting..."
        start_bgutil || true
      elif ! curl -sf "http://127.0.0.1:${BGUTIL_PORT}/ping" >/dev/null 2>&1; then
        echo "[shortmaker] bgutil server unresponsive — restarting..."
        kill "$BGUTIL_PID" 2>/dev/null || true
        start_bgutil || true
      fi
    fi
  done
}

start_bgutil || true

# Start background monitor
monitor_bgutil &
echo "[shortmaker] Background monitor started for bgutil server."

if [ -f /app/frontend/package.json ]; then
  cd /app/frontend
  npm run build
  cd /app
fi

exec python -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-level info
