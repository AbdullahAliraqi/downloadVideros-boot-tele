# Telegram Video Downloader Bot

A lightweight Telegram video downloader for YouTube, Facebook, Instagram, TikTok, X, and Reddit.

## Blitz.cloud target

The production target is a single Python container on blitz.cloud:

~~~text
Telegram
   ↓ HTTPS webhook
Blitz public HTTPS → Flask
   ↓
python-telegram-bot
   ↓ background worker
yt-dlp → FFmpeg / FFprobe
   ↓
Telegram Cloud Bot API
~~~

The image has no Telegram Local Bot API, TDLib, CMake build, Invidious Companion, Camoufox, Playwright, or bgutil service.

## Download policy

The bot:

1. Inspects source-supported resolutions.
2. Prefers 1080p, then 720p, then 480p.
3. Treats portrait 1080x1920 as 1080p.
4. Downloads the highest supported target first.
5. Measures the actual resulting file size with FFprobe.
6. Falls back to the next lower supported resolution only when the actual file exceeds the Telegram Cloud Bot API 50 MB upload limit.
7. Does not send the video when 480p still exceeds 50 MB.

FFmpeg is installed as a Debian package in the image and is used by yt-dlp when separate video and audio streams must be merged.

## YouTube authentication

The downloader can use an optional Netscape-format 'cookies.txt' file through 'YTDLP_COOKIES_FILE'.

The repository contains only a non-secret placeholder:

~~~text
cookies.txt
~~~

Never commit real browser cookies. A non-empty cookie file can be supplied through a mounted path or another deployment mechanism supported by the host.

## Webhook

The public Flask endpoint is:

~~~text
POST /webhook
GET  /
GET  /health
~~~

Set 'WEBHOOK_BASE_URL' to the public HTTPS address. On startup, the bot registers:

~~~text
<WEBHOOK_BASE_URL>/webhook
~~~

When 'WEBHOOK_SECRET' is configured, Telegram's 'X-Telegram-Bot-Api-Secret-Token' header is required.

The webhook returns immediately after the update is queued to the python-telegram-bot event loop. Video downloading is performed in a bounded background thread pool.

## Environment

Required:

- 'BOT_TOKEN'

Recommended for Blitz:

- 'WEBHOOK_BASE_URL=https://abdullahaliraqi.blitz.cloud'

Optional:

- 'WEBHOOK_SECRET'
- 'YTDLP_COOKIES_FILE'
- 'YTDLP_PROXY_URL'
- 'YOUTUBE_PROXY_URL'
- 'YOUTUBE_IPV6_BLOCK'

The repository defaults the Telegram upload limit to 50 MB.

## Local Docker

~~~bash
docker compose up -d --build
docker compose ps
~~~

The application listens on port 8000.

## Verification

The CI workflow checks:

- Python tests.
- Flask root and webhook behavior.
- Docker image build for linux/amd64.
- Presence of FFmpeg/FFprobe.
- Gunicorn WSGI import.
- Presence of the cookies placeholder.
- Docker Compose configuration.

A successful CI build proves the image is buildable. It does not prove that a particular live YouTube URL works from Blitz; that requires a real deployed test with the hosting egress and, when necessary, valid cookies.
