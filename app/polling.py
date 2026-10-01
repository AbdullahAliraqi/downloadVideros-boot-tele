from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .telegram_api import telegram_call

logger = logging.getLogger(__name__)


class TelegramPollingRunner:
    def __init__(
        self,
        handler: Callable[[dict[str, object]], Awaitable[None]],
        *,
        poll_timeout: int = 30,
        retry_delay: float = 2.0,
    ) -> None:
        self._handler = handler
        self._poll_timeout = poll_timeout
        self._retry_delay = retry_delay
        self._offset: int | None = None

    async def run(self) -> None:
        logger.info("Telegram long polling started")

        while True:
            payload: dict[str, Any] = {
                "timeout": self._poll_timeout,
                "limit": 100,
                "allowed_updates": ["message"],
            }
            if self._offset is not None:
                payload["offset"] = self._offset

            try:
                response = await telegram_call("getUpdates", payload)
                updates = response.get("result") or []
                if not isinstance(updates, list):
                    logger.warning("Telegram returned invalid updates payload")
                    continue

                for update in updates:
                    if not isinstance(update, dict):
                        continue

                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._offset = update_id + 1

                    try:
                        await self._handler(update)
                    except Exception:
                        logger.exception(
                            "Telegram update handler failed: update_id=%s",
                            update_id,
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram polling iteration failed")
                await asyncio.sleep(self._retry_delay)
