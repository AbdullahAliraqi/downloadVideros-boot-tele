from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from .config import settings


class TelegramFileTooLargeError(RuntimeError):
    def __init__(self, file_path: Path, size_bytes: int, limit_bytes: int) -> None:
        self.file_path = Path(file_path)
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"Telegram upload limit exceeded: {self.file_path} "
            f"({size_bytes} > {limit_bytes})"
        )


def _require_token() -> str:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not configured")
    return settings.bot_token


def _method_url(method: str) -> str:
    token = _require_token()
    return f"{settings.telegram_api_base_url}/bot{token}/{method}"


async def telegram_call(
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(_method_url(method), json=payload)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict) or not data.get("ok"):
        description = data.get("description") if isinstance(data, dict) else None
        raise RuntimeError(
            f"Telegram API call failed for {method}: {description or data!r}"
        )
    return data


async def send_message(
    chat_id: int | str,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": str(chat_id),
        "text": text,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return await telegram_call("sendMessage", payload)


async def send_video(
    chat_id: int | str,
    file_path: Path,
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    limit_bytes = settings.telegram_max_upload_mb * 1024 * 1024
    size_bytes = file_path.stat().st_size
    if size_bytes > limit_bytes:
        raise TelegramFileTooLargeError(
            file_path,
            size_bytes,
            limit_bytes,
        )

    data: dict[str, str] = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption

    with file_path.open("rb") as video_file:
        files = {
            "video": (file_path.name, video_file, "video/mp4"),
        }
        timeout = httpx.Timeout(connect=30.0, read=None, write=None, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _method_url("sendVideo"),
                data=data,
                files=files,
            )
            response.raise_for_status()
            result = response.json()

    if not isinstance(result, dict) or not result.get("ok"):
        description = result.get("description") if isinstance(result, dict) else None
        raise RuntimeError(
            f"Telegram sendVideo failed: {description or result!r}"
        )
    return result
