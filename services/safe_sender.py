"""Safe message sender that updates user status on TelegramForbiddenError."""
from __future__ import annotations

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

    async def _handle_forbidden(self, user_id: int | None) -> None:
        if user_id is None:
            return
        await self._user_service.update_status(user_id, False)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        try:
            return await self._bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except TelegramForbiddenError:
            await self._handle_forbidden(user_id)
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
            return await self._bot.send_photo(chat_id=chat_id, photo=photo, **kwargs)
        except TelegramForbiddenError:
            await self._handle_forbidden(user_id)
            return None

    async def answer(
        self,
        message: Message,
        text: str,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        resolved_user_id = user_id or (message.from_user.id if message.from_user else None)
        try:
            return await message.answer(text, **kwargs)
        except TelegramForbiddenError:
            await self._handle_forbidden(resolved_user_id)
            return None

    async def answer_photo(
        self,
        message: Message,
        photo: Any,
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ):
        resolved_user_id = user_id or (message.from_user.id if message.from_user else None)
        try:
            return await message.answer_photo(photo=photo, **kwargs)
        except TelegramForbiddenError:
            await self._handle_forbidden(resolved_user_id)
            return None
