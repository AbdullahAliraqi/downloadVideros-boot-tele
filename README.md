# Telegram Video Downloader Bot

A Telegram video downloader for YouTube, Facebook, Instagram, TikTok, X, and Reddit.

## Download policy

The bot checks source-supported resolutions before downloading and prefers 1080p, then 720p, then 480p. It downloads the highest supported target first, measures the actual output size, and retries at the next lower supported target only when the real file exceeds 2000 MB.

Portrait video quality is classified by the shorter video dimension, so 1080x1920 is treated as 1080p.

## Production architecture

The primary production target is a single self-contained Docker application on blitz.cloud. The image keeps the public FastAPI service on port 8000 and runs the Local Telegram Bot API, Invidious Companion, and bgutil POT server on loopback inside the same container.

```text
Telegram
   ↓
Blitz public HTTPS → FastAPI bot
   ├── YouTube → local Companion → YouTube
   ├── Reddit  → Reddit resolver/downloader
   └── other supported platforms → native yt-dlp
   ↓
FFprobe / actual-size gate
   ↓
local Telegram Bot API
   ↓
Telegram
```

This single-container layout avoids relying on container-to-container networking for the Blitz deployment.

## Blitz deployment

Blitz builds this repository from GitHub when the project is connected and runs the repository Dockerfile. It expects one HTTP service/port, so the Dockerfile starts all internal services on loopback and exposes only port 8000.

Set these environment variables in the Blitz app:

- `BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `WEBHOOK_BASE_URL` to the public Blitz app URL when using webhooks
- `WEBHOOK_SECRET` when desired
- `YOUTUBE_PROXY_URL` when YouTube blocks the hosting egress IP
- `YOUTUBE_IPV6_BLOCK` when using a routable IPv6 block

`YOUTUBE_COMPANION_SECRET_KEY` is optional in Blitz. When omitted, the entrypoint generates a random 16-character value and stores it in the persistent `/data/youtube-companion` folder.

Do not set `TELEGRAM_API_BASE_URL` to `https://api.telegram.org` for the Blitz production image; the image provides the Local Bot API internally.

Blitz applies environment-variable changes on the next restart. Persistent folders survive restarts when they are among the app's kept folders. Configure the detected `/data/*` folders in Advanced settings when needed. citeturn886786search1

## YouTube

YouTube uses the official Invidious Companion project as the primary acquisition gateway. The Companion secret is internal only. Native yt-dlp remains a one-time fallback and can optionally use a Netscape-format cookies file.

A successful `/health` response is not a YouTube success signal. The real gate is:

1. Companion starts.
2. Companion obtains a usable YouTube session / PO token.
3. The player endpoint resolves a public YouTube video.
4. The bot selects the highest source-supported resolution.
5. FFprobe validates the resulting MP4.
6. The actual file size stays within the 2000 MB planning limit or the documented quality fallback occurs.
7. The Local Telegram Bot API sends the file.

The Telegram Local Bot API binary is taken from the official aiogram container and listens only on loopback inside the Blitz container. The official image documents local mode and port 8081. citeturn725909search0turn725909search1

## Local Docker Compose

The repository also keeps a conventional three-service `docker-compose.yml` for a normal VPS/Docker host. In that mode, the entrypoint is disabled for the bot container and the three services communicate over the Compose network.

```bash
docker compose up -d --build
docker compose ps
```

## Security

Real values for `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `WEBHOOK_SECRET`, and any YouTube cookies must stay out of Git history.

Do not commit a real `YOUTUBE_COMPANION_SECRET_KEY`. Blitz generates one automatically when it is not provided.
