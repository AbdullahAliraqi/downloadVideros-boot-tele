from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from .config import settings
from .download_coordinator import VideoDownloadCoordinator
from .telegram_api import (
    TelegramFileTooLargeError,
    send_message,
    send_video,
    telegram_call,
)
from .url_validator import is_supported_url
from .video_service import format_duration, format_size

logger = logging.getLogger(__name__)
app = FastAPI(title="Telegram Video Downloader")
coordinator = VideoDownloadCoordinator()

START_MENU: dict[str, Any] = {
    "keyboard": [
        [{"text": "🏠 Start"}, {"text": "🎬 تنزيل فيديو"}],
        [{"text": "🌐 المنصات المدعومة"}, {"text": "ℹ️ طريقة الاستخدام"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

SUPPORTED_PLATFORMS_TEXT = (
    "🌐 المنصات المدعومة:\n"
    "• YouTube\n"
    "• Facebook\n"
    "• Instagram\n"
    "• TikTok\n"
    "• X\n"
    "• Reddit"
)

HELP_TEXT = (
    "ℹ️ طريقة الاستخدام:\n"
    "1. اضغط 🎬 تنزيل فيديو أو أرسل الرابط مباشرة.\n"
    "2. أرسل رابط الفيديو.\n"
    "3. أفحص 1080p ثم 720p ثم 480p حسب ما يوفره المصدر.\n"
    "4. أبدأ بأعلى جودة متاحة فعلياً.\n"
    "5. بعد التنزيل أفحص الحجم الحقيقي للملف.\n"
    "6. إذا تجاوز 2000 MB، أخفض الجودة تلقائياً إلى الجودة الأدنى المتاحة."
)

START_TEXT = (
    "👋 أهلاً بك في بوت تنزيل الفيديو.\n\n"
    "يدعم YouTube وFacebook وInstagram وTikTok وX وReddit.\n"
    "أرسل رابط الفيديو أو استخدم القائمة بالأسفل."
)

BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _background_task_done(task: asyncio.Task[None]) -> None:
    BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("Background video task failed")


def _spawn_background_task(coro: Any) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(_background_task_done)
    return task


async def send_start_menu(chat_id: int | str) -> None:
    await send_message(chat_id, START_TEXT, reply_markup=START_MENU)


async def configure_telegram_for_web() -> None:
    if not settings.bot_token:
        logger.warning("BOT_TOKEN is not configured; Telegram startup configuration skipped")
        return

    await telegram_call(
        "setMyCommands",
        {
            "commands": [
                {
                    "command": "start",
                    "description": "بدء البوت",
                },
            ]
        },
    )
    logger.info("Bot commands configured")

    if settings.webhook_base_url:
        webhook_url = settings.webhook_base_url.rstrip("/") + "/webhook"
        payload: dict[str, Any] = {
            "url": webhook_url,
            "allowed_updates": ["message"],
            "drop_pending_updates": False,
        }
        if settings.webhook_secret:
            payload["secret_token"] = settings.webhook_secret

        await telegram_call("setWebhook", payload)
        logger.info("Telegram webhook configured: %s", webhook_url)


@app.on_event("startup")
async def startup() -> None:
    try:
        await configure_telegram_for_web()
    except Exception:
        logger.exception("Telegram startup configuration failed")


async def process_download_and_send(
    chat_id: int | str,
    url: str,
    job_id: str,
) -> None:
    job_dir = Path(settings.download_root) / job_id
    try:
        await send_message(chat_id, "⬇️ بدأت عملية التنزيل والمعالجة...")
        outcome = await asyncio.to_thread(
            coordinator.download,
            url,
            job_id=job_id,
        )
        result = outcome.result

        available = ", ".join(
            f"{height}p" for height in outcome.available_heights
        )
        await send_message(
            chat_id,
            f"🔎 الجودات المتاحة للمصدر: {available}",
        )

        if outcome.fallback_count:
            attempted = " → ".join(
                f"{height}p" for height in outcome.attempted_heights
            )
            await send_message(
                chat_id,
                "ℹ️ تم خفض الجودة تلقائياً بسبب تجاوز 2000 MB: "
                f"{attempted}\n"
                f"📦 الحجم النهائي: {format_size(result.actual_size)}",
            )

        caption = (
            f"🎬 {result.file_path.stem}\n"
            f"🎞 الجودة: {result.target_height}p\n"
            f"⏱ المدة: {format_duration(result.probe.duration_seconds)}\n"
            f"📦 الحجم: {format_size(result.actual_size)}"
        )
        await send_video(chat_id, result.file_path, caption=caption)
        await send_message(chat_id, "✅ تم إرسال الفيديو بنجاح.")

    except TelegramFileTooLargeError as exc:
        logger.warning(
            "Telegram upload limit exceeded: file=%s size_bytes=%d "
            "limit_bytes=%d local_mode=%s",
            exc.file_path,
            exc.size_bytes,
            exc.limit_bytes,
            settings.telegram_local_mode,
        )
        limit_mb = settings.telegram_max_upload_mb
        await send_message(
            chat_id,
            f"❌ الفيديو ما زال يتجاوز {limit_mb} MB حتى بعد الوصول إلى أقل جودة مدعومة.",
        )
    except Exception as exc:
        logger.exception(
            "Video processing failed: chat_id=%s url=%s job_id=%s",
            chat_id,
            url,
            job_id,
        )
        await send_message(
            chat_id,
            "❌ فشلت عملية تنزيل أو معالجة الفيديو. راجع سجل الخادم لمعرفة السبب.",
        )
        await send_message(
            chat_id,
            f"🔧 DEBUG: {type(exc).__name__}: {exc}",
        )
    finally:
        if job_dir.exists():
            await asyncio.to_thread(
                shutil.rmtree,
                job_dir,
                ignore_errors=True,
            )


async def handle_update(update: dict[str, object]) -> None:
    message = update.get("message") or {}
    if not isinstance(message, dict):
        return

    chat = message.get("chat") or {}
    if not isinstance(chat, dict):
        return

    text = str(message.get("text") or "").strip()
    chat_id = chat.get("id")

    if not chat_id or not text:
        return

    if text in {"/start", "🏠 Start"}:
        await send_start_menu(chat_id)
        return

    if text == "🌐 المنصات المدعومة":
        await send_message(
            chat_id,
            SUPPORTED_PLATFORMS_TEXT,
            reply_markup=START_MENU,
        )
        return

    if text == "ℹ️ طريقة الاستخدام":
        await send_message(
            chat_id,
            HELP_TEXT,
            reply_markup=START_MENU,
        )
        return

    if text == "🎬 تنزيل فيديو":
        await send_message(
            chat_id,
            "🎬 أرسل رابط الفيديو الآن.",
            reply_markup=START_MENU,
        )
        return

    if not is_supported_url(text):
        await send_message(
            chat_id,
            "❌ أرسل رابطاً من YouTube أو Facebook أو Instagram أو TikTok أو X أو Reddit.",
            reply_markup=START_MENU,
        )
        return

    logger.info(
        "Accepted video URL: chat_id=%s url=%s",
        chat_id,
        text,
    )
    await send_message(
        chat_id,
        "🔎 أفحص الجودات المتاحة قبل بدء التنزيل...",
    )
    job_id = uuid.uuid4().hex
    _spawn_background_task(
        process_download_and_send(chat_id, text, job_id)
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "telegram-video-downloader", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/telegram-diagnostic")
async def telegram_diagnostic() -> dict[str, Any]:
    """Temporary deployment diagnostic; never returns credentials."""
    try:
        me = await telegram_call("getMe", {})
        webhook = await telegram_call("getWebhookInfo", {})
        me_result = me.get("result") or {}
        webhook_result = webhook.get("result") or {}
        return {
            "telegram_ok": bool(me.get("ok")),
            "bot_id": me_result.get("id"),
            "bot_username": me_result.get("username"),
            "webhook_url": webhook_result.get("url") or "",
            "pending_updates": webhook_result.get("pending_update_count", 0),
            "last_error_message": webhook_result.get("last_error_message"),
            "last_error_date": webhook_result.get("last_error_date"),
        }
    except Exception as exc:
        logger.exception("Telegram diagnostic failed")
        return {
            "telegram_ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if (
        settings.webhook_secret
        and x_telegram_bot_api_secret_token != settings.webhook_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    update = await request.json()
    if not isinstance(update, dict):
        return {"ok": True}

    _spawn_background_task(handle_update(update))
    return {"ok": True}
