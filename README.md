# Telegram Video Downloader Bot

A Telegram video downloader for YouTube, Facebook, Instagram, TikTok, X, and Reddit.

## Download policy

The bot checks source-supported resolutions before downloading and prefers 1080p, then 720p, then 480p. It downloads the highest supported target first, measures the actual output size, and retries at the next lower supported target only when the real file exceeds 2000 MB.

Portrait video quality is classified by the shorter video dimension, so 1080x1920 is treated as 1080p.

## Local / VPS deployment

The production deployment is Docker Compose with the Local Telegram Bot API. Both the Bot API state and downloaded media use Docker named volumes; this avoids the Windows bind-mount failure that previously caused Telegram Bot API binlog crashes.

### YouTube production path

YouTube uses native yt-dlp by default. Public Piped is optional and is used only when `PIPED_API_URLS` contains an instance that has been independently verified from the deployment environment.

When YouTube returns `Sign in to confirm you’re not a bot`, set `YTDLP_COOKIES_FILE` to a Netscape-format YouTube cookies file. yt-dlp documents cookies as a workaround for YouTube bot verification/authentication. Keep the file out of Git history; yt-dlp also warns that using an account can result in temporary or permanent account bans, so a dedicated account is preferable.

1. Copy `.env.example` to `.env`.
2. Put your real Telegram credentials in `.env`. Never commit it.
3. Run:

```bash
docker compose build
docker compose up -d
```

The bot starts its Telegram long-polling runner automatically and removes any webhook before polling.

## Moving the project to a VPS

Clone this repository on the VPS, create the VPS `.env`, then run the same Docker Compose commands above.

For the 2000 MB upload target, use the Local Telegram Bot API deployment in `docker-compose.yml`. The Render configuration is a separate hosted-Bot-API mode and is not the 2000 MB production path.

## Security

Real values for `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `WEBHOOK_SECRET` must stay out of Git history.


## Blitz Telegram upload path

Telegram's cloud Bot API is limited to 50 MB for bot uploads. Telegram's Local Bot API server allows uploads up to 2000 MB and requires your own `api_id` and `api_hash`.

This repository already contains the Local Bot API service in `docker-compose.yml`. On blitz.cloud, deploy the repository as a GitHub/Compose project rather than deploying only the root `Dockerfile`.

Blitz can run the services in a Compose project as separate parts while keeping their service-to-service addresses. The `bot` service uses `app.local_runner` and talks to the `telegram-bot-api` service at `http://telegram-bot-api:8081`. The Compose file already enables `TELEGRAM_LOCAL=1` and sets the upload target to 2000 MB.

Set these environment variables in the Blitz project:

```
BOT_TOKEN=<your existing bot token>
TELEGRAM_API_ID=<your Telegram api_id>
TELEGRAM_API_HASH=<your Telegram api_hash>
```

Do not set `TELEGRAM_API_BASE_URL=https://api.telegram.org` for the Compose deployment; the Compose service sets it internally to `http://telegram-bot-api:8081`.

Obtain `api_id` and `api_hash` from https://my.telegram.org. They are separate from the bot token.

After the Compose deployment is online, verify the `telegram-bot-api` part is healthy and the `bot` part is running. Then the bot uses Telegram Local Bot API for files up to the 2000 MB target.

The 50 MB cloud limit is a Telegram platform limit, not a Blitz limit.
