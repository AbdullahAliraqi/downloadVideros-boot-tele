#!/bin/sh
set -eu

log() {
  printf '%s | %s\n' "blitz-runtime" "$*";
}

if [ "${BLITZ_SINGLE_CONTAINER:-true}" != "true" ]; then
  exec "$@"
fi

: "${BOT_TOKEN:?BOT_TOKEN must be set}"

# Blitz runs this repository as one app/container. Use the Telegram Local Bot
# API only when its required API credentials are actually configured.
export YOUTUBE_COMPANION_BASE_URL=http://127.0.0.1:8282/companion
required_ports="8282"

if [ -n "${TELEGRAM_API_ID:-}" ] && [ -n "${TELEGRAM_API_HASH:-}" ]; then
  export TELEGRAM_LOCAL_MODE=true
  export TELEGRAM_MAX_UPLOAD_MB=2000
  export TELEGRAM_API_BASE_URL=http://127.0.0.1:8081
  required_ports="8081 8282"
  log "Telegram Local Bot API enabled."
else
  export TELEGRAM_LOCAL_MODE=false
  export TELEGRAM_MAX_UPLOAD_MB=50
  export TELEGRAM_API_BASE_URL="${TELEGRAM_API_BASE_URL:-https://api.telegram.org}"
  log "Telegram API credentials are not configured; using Telegram Cloud Bot API (50 MB limit)."
fi

mkdir -p /data/telegram-bot-api /data/youtube-companion /data/youtubei.js
umask 077

secret_file=/data/youtube-companion/secret
secret="${YOUTUBE_COMPANION_SECRET_KEY:-}"
if [ -z "$secret" ] && [ -f "$secret_file" ]; then
  secret="$(tr -d '\r\n' < "$secret_file")"
fi

if [ -z "$secret" ]; then
  secret="$(python -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(16)))')"
  printf '%s' "$secret" > "$secret_file"
  log "Generated persistent 16-character YouTube Companion secret."
fi

if [ "${#secret}" -ne 16 ]; then
  log "ERROR: YOUTUBE_COMPANION_SECRET_KEY must contain exactly 16 characters."
  exit 1
fi

export YOUTUBE_COMPANION_SECRET_KEY="$secret"

if [ "${BLITZ_PREFLIGHT_ONLY:-false}" = "true" ]; then
  log "Blitz preflight complete: Telegram mode and Companion secret are valid."
  exit 0
fi

telegram-bot-api \
  --dir=/data/telegram-bot-api \
  --temp-dir=/tmp/telegram-bot-api \
  --http-port=8081 \
  --http-stat-port=8082 \
  --http-ip-address=127.0.0.1 \
  --local &
telegram_pid=$!

HOST=127.0.0.1 \
PORT=8282 \
SERVER_BASE_PATH=/companion \
SERVER_SECRET_KEY="$YOUTUBE_COMPANION_SECRET_KEY" \
SERVER_VERIFY_REQUESTS=false \
CACHE_ENABLED=true \
CACHE_DIRECTORY=/var/tmp/youtubei.js \
JOBS_YOUTUBE_SESSION_PO_TOKEN_ENABLED=true \
JOBS_YOUTUBE_SESSION_FREQUENCY='*/5 * * * *' \
NETWORKING_FETCH_TIMEOUT_MS=30000 \
NETWORKING_FETCH_RETRY_ENABLED=true \
NETWORKING_FETCH_RETRY_TIMES=2 \
NETWORKING_FETCH_RETRY_INITIAL_DEBOUNCE=500 \
NETWORKING_FETCH_RETRY_DEBOUNCE_MULTIPLIER=2 \
PROXY="${YOUTUBE_PROXY_URL:-}" \
NETWORKING_IPV6_BLOCK="${YOUTUBE_IPV6_BLOCK:-}" \
invidious_companion &
companion_pid=$!

node /opt/bgutil-ytdlp-pot-provider/server/build/main.js --port 4416 &
pot_pid=$!

cleanup() {
  kill "$pot_pid" "$companion_pid" 2>/dev/null || true
  if [ -n "${telegram_pid:-}" ]; then
    kill "$telegram_pid" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

REQUIRED_PORTS="$required_ports" python - <<'PY'
import os
import socket
import time

services = tuple(("127.0.0.1", int(port)) for port in os.environ["REQUIRED_PORTS"].split())
deadline = time.time() + 60
while time.time() < deadline:
    ready = True
    for host, port in services:
        with socket.socket() as sock:
            sock.settimeout(1)
            try:
                sock.connect((host, port))
            except OSError:
                ready = False
                break
    if ready:
        break
    time.sleep(1)
else:
    raise SystemExit("Internal Telegram Bot API / YouTube Companion did not become ready")

print("Internal services ready.", flush=True)
PY

log "Internal services ready; starting public FastAPI service on port 8000."
exec "$@"
