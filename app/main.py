from __future__ import annotations

import atexit
import asyncio
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import settings
from .download_coordinator import DownloadOutcome, VideoDownloadCoordinator
from .url_validator import is_supported_url
from .video_service import format_duration, format_size

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
coordinator = VideoDownloadCoordinator()
DOWNLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="download")

START_MENU = [
    ["🏠 Start", "🎬 تنزيل فيديو"],
    ["🌐 المنصات المدعومة", "ℹ️ طريقة الاستخدام"],
]

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
    f"6. إذا تجاوز {settings.telegram_max_upload_mb} MB، أخفض الجودة تلقائياً إلى الجودة الأدنى المتاحة."
)

START_TEXT = (
    "👋 أهلاً بك في بوت تنزيل الفيديو.\n\n"
    "يدعم YouTube وFacebook وInstagram وTikTok وX وReddit.\n"
    "أرسل رابط الفيديو أو استخدم القائمة بالأسفل."
)


class TelegramRuntime:
    def __init__(self) -> None:
        self.application: Application[Any, Any, Any, Any, Any, Any] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.start_error: Exception | None = None

    def start(self) -> None:
        if not settings.bot_token:
            logger.warning("BOT_TOKEN is not configured; Telegram runtime is disabled")
            return
        if self.thread and self.thread.is_alive():
            return

        self.thread = threading.Thread(
            target=self._run,
            name="telegram-runtime",
            daemon=True,
        )
        self.thread.start()

    def _build_application(self) -> Application[Any, Any, Any, Any, Any, Any]:
        application = Application.builder().token(settings.bot_token).build()
        application.add_handler(CommandHandler("start", start_handler))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
        )
        return application

    async def _bootstrap(self) -> None:
        assert self.application is not None
        await self.application.initialize()
        await self.application.start()

        if settings.webhook_base_url:
            webhook_url = (
                settings.webhook_base_url.rstrip("/") + "/webhook"
            )
            kwargs: dict[str, Any] = {
                "url": webhook_url,
                "allowed_updates": ["message"],
                "drop_pending_updates": False,
            }
            if settings.webhook_secret:
                kwargs["secret_token"] = settings.webhook_secret
            await self.application.bot.set_webhook(**kwargs)
            logger.info("Telegram webhook configured: %s", webhook_url)
        else:
            logger.warning(
                "WEBHOOK_BASE_URL is not configured; set it to the public Blitz HTTPS URL"
            )

        self.ready.set()
        logger.info("Telegram webhook runtime ready")

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.application = self._build_application()

        try:
            loop.run_until_complete(self._bootstrap())
        except Exception as exc:
            self.start_error = exc
            logger.exception("Telegram runtime startup failed")
            self.ready.set()

        try:
            loop.run_forever()
        finally:
            if self.application is not None:
                try:
                    loop.run_until_complete(self.application.stop())
                except Exception:
                    logger.exception("Telegram application stop failed")
                try:
                    loop.run_until_complete(self.application.shutdown())
                except Exception:
                    logger.exception("Telegram application shutdown failed")
            loop.close()

    def submit_update(self, payload: dict[str, Any]) -> None:
        if not self.ready.wait(timeout=5):
            raise RuntimeError("Telegram runtime is not ready")
        if self.start_error is not None:
            raise RuntimeError("Telegram runtime failed during startup") from self.start_error
        if self.loop is None or self.application is None:
            raise RuntimeError("Telegram runtime is unavailable")

        update = Update.de_json(payload, self.application.bot)
        if update is None:
            raise ValueError("Telegram sent an invalid update")
        asyncio.run_coroutine_threadsafe(
            self.application.process_update(update),
            self.loop,
        )

    def stop(self) -> None:
        if self.loop is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


runtime = TelegramRuntime()


def _submit_download(
    chat_id: int,
    url: str,
    job_id: str,
) -> None:
    try:
        outcome = coordinator.download(url, job_id=job_id)
        if runtime.loop is None or runtime.application is None:
            raise RuntimeError("Telegram runtime is unavailable for result delivery")
        asyncio.run_coroutine_threadsafe(
            _send_download_result(chat_id, outcome),
            runtime.loop,
        )
    except Exception as exc:
        logger.exception(
            "Video processing failed: chat_id=%s url=%s job_id=%s",
            chat_id,
            url,
            job_id,
        )
        if runtime.loop is not None and runtime.application is not None:
            asyncio.run_coroutine_threadsafe(
                _send_failure_message(chat_id, exc),
                runtime.loop,
            )


async def _send_failure_message(chat_id: int, exc: Exception) -> None:
    if runtime.application is None:
        return
    await runtime.application.bot.send_message(
        chat_id=chat_id,
        text=(
            "❌ فشلت عملية تنزيل أو معالجة الفيديو. "
            "راجع سجل الخادم لمعرفة السبب.\n"
            f"🔧 DEBUG: {type(exc).__name__}: {exc}"
        ),
    )


async def _send_download_result(
    chat_id: int,
    outcome: DownloadOutcome,
) -> None:
    if runtime.application is None:
        return

    bot = runtime.application.bot
    result = outcome.result
    limit_bytes = settings.telegram_max_upload_mb * 1024 * 1024

    available = ", ".join(f"{height}p" for height in outcome.available_heights)
    await bot.send_message(
        chat_id=chat_id,
        text=f"🔎 الجودات المتاحة للمصدر: {available}",
    )

    if result.actual_size > limit_bytes:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"❌ الفيديو ما زال يتجاوز {settings.telegram_max_upload_mb} MB "
                "بعد الوصول إلى أقل جودة مدعومة، لذلك لن يتم إرساله."
            ),
        )
        return

    if outcome.fallback_count:
        attempted = " → ".join(f"{height}p" for height in outcome.attempted_heights)
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ تم خفض الجودة تلقائياً بسبب تجاوز حد الرفع: "
                f"{attempted}\n"
                f"📦 الحجم النهائي: {format_size(result.actual_size)}"
            ),
        )

    caption = (
        f"🎬 {result.file_path.stem}\n"
        f"🎞 الجودة: {result.target_height}p\n"
        f"⏱ المدة: {format_duration(result.probe.duration_seconds)}\n"
        f"📦 الحجم: {format_size(result.actual_size)}"
    )
    with result.file_path.open("rb") as video_file:
        await bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption=caption,
        )
    await bot.send_message(chat_id=chat_id, text="✅ تم إرسال الفيديو بنجاح.")

    job_dir = Path(settings.download_root) / result.job_id
    if job_dir.exists():
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)


async def start_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    await update.effective_message.reply_text(
        START_TEXT,
        reply_markup={
            "keyboard": START_MENU,
            "resize_keyboard": True,
            "is_persistent": True,
        },
    )


async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or not message.text:
        return

    text = message.text.strip()

    if text == "🏠 Start":
        await start_handler(update, context)
        return

    if text == "🌐 المنصات المدعومة":
        await message.reply_text(
            SUPPORTED_PLATFORMS_TEXT,
            reply_markup={
                "keyboard": START_MENU,
                "resize_keyboard": True,
                "is_persistent": True,
            },
        )
        return

    if text == "ℹ️ طريقة الاستخدام":
        await message.reply_text(
            HELP_TEXT,
            reply_markup={
                "keyboard": START_MENU,
                "resize_keyboard": True,
                "is_persistent": True,
            },
        )
        return

    if text == "🎬 تنزيل فيديو":
        await message.reply_text(
            "🎬 أرسل رابط الفيديو الآن.",
            reply_markup={
                "keyboard": START_MENU,
                "resize_keyboard": True,
                "is_persistent": True,
            },
        )
        return

    if not is_supported_url(text):
        await message.reply_text(
            "❌ أرسل رابطاً من YouTube أو Facebook أو Instagram أو TikTok أو X أو Reddit.",
            reply_markup={
                "keyboard": START_MENU,
                "resize_keyboard": True,
                "is_persistent": True,
            },
        )
        return

    logger.info(
        "Accepted video URL: chat_id=%s url=%s",
        chat.id,
        text,
    )
    await message.reply_text("🔎 أفحص الجودات المتاحة قبل بدء التنزيل...")
    job_id = uuid.uuid4().hex
    DOWNLOAD_EXECUTOR.submit(_submit_download, chat.id, text, job_id)


@app.get("/")
def root() -> tuple[str, int]:
    return "Bot Service is Active", 200


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


@app.post("/webhook")
def webhook() -> tuple[str, int]:
    if (
        settings.webhook_secret
        and request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        != settings.webhook_secret
    ):
        return "Forbidden", 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return "Invalid Telegram update", 400

    try:
        runtime.submit_update(payload)
    except Exception:
        logger.exception("Failed to queue Telegram update")
        return "Telegram runtime unavailable", 503

    return "OK", 200


if settings.telegram_runtime_autostart:
    runtime.start()

atexit.register(runtime.stop)
