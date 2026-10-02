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


def _normalize_api_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if "://" in value:
        return value
    return f"http://{value}"


@dataclass
class Settings:
    bot_token: str
    telegram_api_id: str
    telegram_api_hash: str
    telegram_api_base_url: str
    telegram_local_mode: bool
    telegram_max_upload_mb: int
    ytdlp_proxy_url: str
    tunelio_api_key: str
    tunelio_api_base_url: str
    ffmpeg_path: str
    ffprobe_path: str
    download_root: str
    webhook_base_url: str
    webhook_secret: str
    host: str
    port: int


settings = Settings(
    bot_token=os.getenv("BOT_TOKEN", "").strip(),
    telegram_api_id=os.getenv("TELEGRAM_API_ID", "").strip(),
    telegram_api_hash=os.getenv("TELEGRAM_API_HASH", "").strip(),
    telegram_api_base_url=_normalize_api_base_url(
        os.getenv(
            "TELEGRAM_API_BASE_URL",
            "https://api.telegram.org",
        )
    ),
    telegram_local_mode=_bool_env("TELEGRAM_LOCAL_MODE", False),
    telegram_max_upload_mb=_int_env("TELEGRAM_MAX_UPLOAD_MB", 50),
    ytdlp_proxy_url=os.getenv("YTDLP_PROXY_URL", "").strip(),
    tunelio_api_key=os.getenv("TUNELIO_API_KEY", "").strip(),
    tunelio_api_base_url=_normalize_api_base_url(
        os.getenv("TUNELIO_API_BASE_URL", "https://tunelio.dev")
    ),
    ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg",
    ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe").strip() or "ffprobe",
    download_root=os.getenv(
        "DOWNLOAD_ROOT",
        "/tmp/telegram-video-downloads",
    ).strip(),
    webhook_base_url=os.getenv("WEBHOOK_BASE_URL", "").strip(),
    webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
    host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
    port=_int_env("PORT", 8000),
)
