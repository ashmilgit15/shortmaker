#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"

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
