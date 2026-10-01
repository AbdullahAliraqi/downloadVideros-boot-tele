# Telegram Video Downloader

Supports public video URLs from YouTube, Facebook, Instagram, TikTok, X, and Reddit.

Quality policy:
1. Prefer 1080p.
2. Otherwise use 720p.
3. Otherwise use 480p.
4. Download the highest supported target.
5. Check the actual output size.
6. If it exceeds 2000 MB, retry at the next lower supported target.
7. If 480p still exceeds 2000 MB, report that it cannot fit.

Portrait videos use the shorter video dimension for quality detection, so 1080x1920 is treated as 1080p.

Local deployment uses the Local Telegram Bot API and Docker named volumes. This avoids storing Telegram Bot API binlog state on the Windows bind-mounted filesystem.

Create .env from .env.example, set Telegram credentials, then run:
docker compose --env-file .env build bot
docker compose --env-file .env up -d

Do not commit .env or real Telegram credentials.

Render configuration is included for regular Bot API/webhook deployment; that path uses the regular Telegram Bot API upload ceiling rather than the local 2000 MB target.
