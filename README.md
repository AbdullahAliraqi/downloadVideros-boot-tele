# Telegram Video Downloader Bot

A Telegram video downloader for YouTube, Facebook, Instagram, TikTok, X, and Reddit.

## Download policy

The bot checks source-supported resolutions before downloading and prefers 1080p, then 720p, then 480p. It downloads the highest supported target first, measures the actual output size, and retries at the next lower supported target only when the real file exceeds 2000 MB.

Portrait video quality is classified by the shorter video dimension, so 1080x1920 is treated as 1080p.

## Local / VPS deployment

The production deployment is Docker Compose with the Local Telegram Bot API. Both the Bot API state and downloaded media use Docker named volumes; this avoids the Windows bind-mount failure that previously caused Telegram Bot API binlog crashes.

### YouTube production path

YouTube is attempted through Piped first. The bot resolves the YouTube video through a documented public Piped API instance and downloads the returned MP4 stream, so the initial YouTube extraction request does not originate from the Blitz IP. The resolver tries multiple instances in sequence. The native yt-dlp pipeline remains the final fallback.

The public Piped instance list can change, so `PIPED_API_URLS` is configurable. Leave it empty to use the current documented defaults, or provide a comma-separated list of known instances.

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

Telegram's official cloud Bot API currently limits bot uploads to 50 MB. Telegram's local Bot API server raises the upload limit to 2000 MB and requires an `api_id` and `api_hash`.

For the 2000 MB target on Blitz, use two apps:

1. Keep this downloader app on Blitz.
2. Deploy the official-source-compatible `aiogram/telegram-bot-api:latest` Docker image as a second Blitz app.
3. In the Bot API app set `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `TELEGRAM_LOCAL=1`.
4. In this downloader app set:
   `TELEGRAM_API_BASE_URL=https://<your-bot-api-app>.blitz.cloud`
   `TELEGRAM_LOCAL_MODE=true`
   `TELEGRAM_MAX_UPLOAD_MB=2000`
   Keep `WEBHOOK_BASE_URL=https://abdullahaliraqi.blitz.cloud` (or your current downloader address).

The downloader continues using its normal HTTPS webhook. The local Bot API server is the component that talks to Telegram and exposes the 2000 MB local-mode upload capability.

The cloud 50 MB limit is a Telegram platform limit, not a Blitz limit.