#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"

exec python -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-level info
