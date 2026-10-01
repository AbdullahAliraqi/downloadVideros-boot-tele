from __future__ import annotations

import asyncio
import logging

from .main import handle_update
from .polling import TelegramPollingRunner
from .telegram_api import telegram_call

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def wait_for_api(attempts: int = 30, delay: float = 2.0) -> None:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            result = await telegram_call("getMe", {})
            logger.info("Telegram Bot API ready: %s", result.get("ok"))
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                logger.warning(
                    "Waiting for Telegram Bot API %d/%d: %s",
                    attempt,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay)
    raise RuntimeError("Telegram Bot API did not become ready") from last_error


async def configure_local_mode() -> None:
    # getUpdates and webhook mode are mutually exclusive.
    await telegram_call("deleteWebhook", {"drop_pending_updates": False})
    await telegram_call(
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "بدء البوت"},
            ]
        },
    )
    logger.info("Local polling Telegram configuration complete")


async def logged_handler(update: dict[str, object]) -> None:
    logger.info("UPDATE RECEIVED update_id=%s", update.get("update_id"))
    await handle_update(update)


async def main() -> None:
    await wait_for_api()
    await configure_local_mode()
    runner = TelegramPollingRunner(logged_handler)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
