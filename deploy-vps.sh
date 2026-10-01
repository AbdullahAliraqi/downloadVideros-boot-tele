#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/AbdullahAliraqi/downloadVideros-boot-tele.git"
APP_DIR="${APP_DIR:-/opt/telegram-video-bot}"

if [ ! -d "$APP_DIR/.git" ]; then
  sudo mkdir -p "$APP_DIR"
  sudo chown "$USER:$USER" "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env. Fill in the Telegram credentials, then rerun this script."
  exit 0
fi

docker compose build
docker compose up -d
docker compose ps
