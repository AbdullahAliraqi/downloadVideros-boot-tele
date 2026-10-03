from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass
class Settings:
    bot_token: str
    telegram_max_upload_mb: int
    ytdlp_proxy_url: str
    youtube_proxy_url: str
    youtube_ipv6_block: str
    ytdlp_cookies_file: str
    ffmpeg_path: str
    ffprobe_path: str
    download_root: str
    webhook_base_url: str
    webhook_secret: str
    telegram_runtime_autostart: bool
    host: str
    port: int


settings = Settings(
    bot_token=os.getenv("BOT_TOKEN", "").strip(),
    telegram_max_upload_mb=_int_env("TELEGRAM_MAX_UPLOAD_MB", 50),
    ytdlp_proxy_url=os.getenv("YTDLP_PROXY_URL", "").strip(),
    youtube_proxy_url=os.getenv("YOUTUBE_PROXY_URL", "").strip(),
    youtube_ipv6_block=os.getenv("YOUTUBE_IPV6_BLOCK", "").strip(),
    ytdlp_cookies_file=os.getenv("YTDLP_COOKIES_FILE", "/app/cookies.txt").strip(),
    ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg",
    ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe").strip() or "ffprobe",
    download_root=os.getenv("DOWNLOAD_ROOT", "/data/downloads").strip(),
    webhook_base_url=os.getenv("WEBHOOK_BASE_URL", "").strip(),
    webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
    telegram_runtime_autostart=_bool_env("TELEGRAM_RUNTIME_AUTOSTART", True),
    host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
    port=_int_env("PORT", 8000),
)


def valid_cookiefile(path: str) -> str | None:
    """Return a cookie file only when it is a readable Mozilla/Netscape jar."""
    from http.cookiejar import MozillaCookieJar
    from pathlib import Path

    cookie_path = Path(path)
    if not cookie_path.is_file() or cookie_path.stat().st_size == 0:
        return None

    try:
        jar = MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Ignoring invalid yt-dlp cookie file: %s", cookie_path
        )
        return None

    return str(cookie_path)
