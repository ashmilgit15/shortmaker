#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"

if [ -f /app/frontend/package.json ]; then
  cd /app/frontend
  npm run build
  cd /app
fi

# Start bgutil PO Token HTTP server in the background if available
# This generates Proof-of-Origin tokens to bypass YouTube bot detection
BGUTIL_SERVER="/opt/bgutil-ytdlp-pot-provider/server/build/main.js"
if [ -f "$BGUTIL_SERVER" ] && command -v node >/dev/null 2>&1; then
  echo "[shortmaker] Starting bgutil PO Token server on port 4416..."
  TOKEN_TTL="${SHORTMAKER_YTDLP_POT_TOKEN_TTL:-12}" \
  node "$BGUTIL_SERVER" --port 4416 &
  BGUTIL_PID=$!
  echo "[shortmaker] bgutil PO Token server started (PID $BGUTIL_PID)"
  # Give it a moment to initialize
  sleep 2
fi

exec python -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-level info
