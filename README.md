# Telegram Video Downloader Bot

A Telegram video downloader for YouTube, Facebook, Instagram, TikTok, X, and Reddit.

## Download policy

The bot checks source-supported resolutions before downloading and prefers 1080p, then 720p, then 480p. It downloads the highest supported target first, measures the actual output size, and retries at the next lower supported target only when the real file exceeds 2000 MB.

Portrait video quality is classified by the shorter video dimension, so 1080x1920 is treated as 1080p.

## Production architecture

The production deployment is Docker Compose on the VPS with three cooperating services:

```text
Telegram
   ↓
bot
   ├── YouTube → youtube-companion → YouTube
   ├── Reddit  → Reddit resolver/downloader
   └── other supported platforms → native yt-dlp
   ↓
FFprobe / actual-size gate
   ↓
telegram-bot-api (Local Bot API)
   ↓
Telegram
```

The Local Telegram Bot API is the upload path for the 2000 MB target.

### YouTube production path

YouTube no longer depends on public Piped instances.

The primary YouTube path is the official Invidious Companion project, an internal service specifically designed to handle YouTube stream retrieval and attestation through youtubei.js. It exposes an internal player API and a refreshed `latest_version` stream path. The bot only uses Companion as a YouTube acquisition layer; resolution policy, file-size policy, FFmpeg probing, and Telegram delivery remain in this project.

The bot falls back to native yt-dlp once if Companion is unavailable or YouTube rejects the Companion path. Native yt-dlp can optionally use a Netscape-format YouTube cookies file and the same configured egress proxy.

The Companion service generates PO tokens automatically. It keeps its youtube.js cache in a persistent Docker volume and refreshes its YouTube session periodically.

### YouTube configuration

Set `YOUTUBE_COMPANION_SECRET_KEY` to a random value of exactly 16 characters in the VPS `.env`. It is used only for the internal bot → Companion API.

For native fallback cookies:

1. Create a `.secrets` directory beside `docker-compose.yml`.
2. Put `youtube-cookies.txt` inside it.
3. Set `YTDLP_COOKIES_FILE=/run/secrets/youtube-cookies.txt`.
4. Keep the cookie file out of Git.

yt-dlp requires Mozilla/Netscape cookie format for a manual cookie file. Its current FAQ also recommends refreshing the browser session and notes that cookies are sensitive credentials. Use a dedicated account rather than a primary account when account cookies are necessary.

If a proxy is required, set `YTDLP_PROXY_URL`. The same value is passed to both native yt-dlp and YouTube Companion so the two paths use the same egress identity. Do not use per-request rotating proxies for a persistent YouTube session.

## Local / VPS deployment

1. Copy `.env.example` to `.env`.
2. Set `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and a 16-character `YOUTUBE_COMPANION_SECRET_KEY`.
3. Run:

```bash
docker compose up -d --build
docker compose ps
```

The bot service uses `app.local_runner`, removes any webhook, and polls the Local Telegram Bot API.

For the 2000 MB target, do not replace `TELEGRAM_API_BASE_URL=http://telegram-bot-api:8081` with the cloud Bot API URL.

## Verification

A successful `/health` or `200 OK` webhook response is not a YouTube success signal.

For a real production gate, verify all of the following on the deployed Compose project:

- `youtube-companion` is healthy.
- Its player endpoint resolves a public YouTube video.
- The bot downloads the highest source-supported resolution.
- FFprobe validates the resulting MP4.
- A file over 2000 MB causes only the documented resolution fallback.
- A file within the limit reaches `telegram-bot-api` and is sent.
- Restarting the Compose project preserves the Companion cache volume and does not require rebuilding for ordinary session refreshes.

## Security

Real values for `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `WEBHOOK_SECRET`, `YOUTUBE_COMPANION_SECRET_KEY`, and YouTube cookies must stay out of Git history.

The Local Telegram Bot API state, downloads, and Companion cache use named Docker volumes so service restarts do not depend on bind-mounted runtime state.
