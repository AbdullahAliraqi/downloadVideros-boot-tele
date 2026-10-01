# Telegram Video Downloader Bot

A Telegram video downloader for YouTube, Facebook, Instagram, TikTok, X, and Reddit.

## Download policy

The bot checks source-supported resolutions before downloading and prefers 1080p, then 720p, then 480p. It downloads the highest supported target first, measures the actual output size, and retries at the next lower supported target only when the real file exceeds 2000 MB.

Portrait video quality is classified by the shorter video dimension, so 1080x1920 is treated as 1080p.

## Local / VPS deployment

The production deployment is Docker Compose with the Local Telegram Bot API. Both the Bot API state and downloaded media use Docker named volumes; this avoids the Windows bind-mount failure that previously caused Telegram Bot API binlog crashes.

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
