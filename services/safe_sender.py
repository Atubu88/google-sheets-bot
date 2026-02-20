"""Safe message sender that updates user status on TelegramForbiddenError."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import Message

from services.user_service import UserService


class SafeSender:
    """Centralized wrapper for bot sends with forbidden handling."""

    def __init__(self, bot: Bot, user_service: UserService) -> None:
        self._bot = bot
        self._user_service = user_service
        self._forbidden_chat_ids: set[int] = set()
        self._forbidden_lock = asyncio.Lock()

    @property
    def _logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    async def _handle_forbidden(self, chat_id: int | None) -> None:
        if chat_id is None:
            return
        async with self._forbidden_lock:
            self._forbidden_chat_ids.add(chat_id)

    async def flush_pending_forbidden_statuses(
        self,
        *,
        max_updates: int = 50,
        pause_seconds: float = 0.05,
    ) -> int:
        async with self._forbidden_lock:
            pending_chat_ids = list(self._forbidden_chat_ids)
            self._forbidden_chat_ids.clear()

        if not pending_chat_ids:
            return 0

        max_updates = max(1, max_updates)
        to_process = pending_chat_ids[:max_updates]
        leftovers = pending_chat_ids[max_updates:]

        updated = 0
        for chat_id in to_process:
            try:
                await asyncio.wait_for(self._user_service.update_status_by_chat_id(chat_id, False), timeout=5)
                updated += 1
            except TimeoutError:
                self._logger.warning(
                    "Timed out while updating status=left for forbidden chat_id=%s; will retry later",
                    chat_id,
                )
                leftovers.append(chat_id)
            except Exception:
                self._logger.warning(
                    "Failed to update status=left for forbidden chat_id=%s; will retry later",
                    chat_id,
                    exc_info=True,
                )
                leftovers.append(chat_id)

            if pause_seconds > 0:
                await asyncio.sleep(pause_seconds)

        if leftovers:
            async with self._forbidden_lock:
                self._forbidden_chat_ids.update(leftovers)

        self._logger.info(
            "Forbidden status flush done: requested=%s processed=%s updated=%s requeued=%s",
            len(pending_chat_ids),
            len(to_process),
            updated,
            len(leftovers),
        )
        return updated

    async def pending_forbidden_count(self) -> int:
        async with self._forbidden_lock:
            return len(self._forbidden_chat_ids)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        try:
            response = await self._bot.send_message(chat_id=chat_id, text=text, **kwargs)
            self._logger.debug("Message sent successfully chat_id=%s message_id=%s", chat_id, response.message_id)
            return response
        except TelegramForbiddenError:
            await self._handle_forbidden(chat_id)
            return None

    async def send_photo(
        self,
        chat_id: int,
        photo: Any,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        try:
            response = await self._bot.send_photo(chat_id=chat_id, photo=photo, **kwargs)
            self._logger.debug("Photo sent successfully chat_id=%s message_id=%s", chat_id, response.message_id)
            return response
        except TelegramForbiddenError:
            await self._handle_forbidden(chat_id)
            return None

    async def answer(
        self,
        message: Message,
        text: str,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        try:
            response = await message.answer(text, **kwargs)
            self._logger.debug("Answer sent successfully chat_id=%s message_id=%s", message.chat.id, response.message_id)
            return response
        except TelegramForbiddenError:
            await self._handle_forbidden(message.chat.id)
            return None

    async def answer_photo(
        self,
        message: Message,
        photo: Any,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        try:
            response = await message.answer_photo(photo=photo, **kwargs)
            self._logger.debug("Answer photo sent successfully chat_id=%s message_id=%s", message.chat.id, response.message_id)
            return response
        except TelegramForbiddenError:
            await self._handle_forbidden(message.chat.id)
            return None
