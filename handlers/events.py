"""Event handlers for membership updates."""
from __future__ import annotations

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from services.user_service import UserService

router = Router()


@router.chat_member()
async def handle_chat_member_update(
    event: ChatMemberUpdated,
    user_service: UserService,
) -> None:
    """Handle user subscription changes."""

    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status

    if new_status == old_status:
        return

    user_id = event.new_chat_member.user.id

    if new_status == ChatMemberStatus.KICKED:
        await user_service.update_status(user_id, is_active=False)
        return

    if new_status == ChatMemberStatus.MEMBER:
        await user_service.update_status(user_id, is_active=True)
