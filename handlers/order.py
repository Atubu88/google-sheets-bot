"""Order flow handlers using aiogram 3 with media edits for every step."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    InputMediaPhoto,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.buy import cancel_order_callback, get_selected_product
from services.crm_client import LPCRMClient
from services.customer_service import CustomerService
from services.product_service import ProductService

router = Router()
logger = logging.getLogger(__name__)

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


class OrderState(StatesGroup):
    """States for guiding the user through the order process."""

    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_city_branch = State()
    waiting_for_confirmation = State()


async def update_step(message_or_callback, state: FSMContext, photo: str, text: str, keyboard) -> None:
    """Safely update the order message media for the current step."""

    data = await state.get_data()
    message_id = data.get("message_id")
    if message_id is None:
        logger.warning("No message_id in state; cannot update step")
        return

    if isinstance(message_or_callback, CallbackQuery):
        chat_id = message_or_callback.message.chat.id if message_or_callback.message else None
        bot = message_or_callback.message.bot if message_or_callback.message else None
    else:
        chat_id = message_or_callback.chat.id
        bot = message_or_callback.bot

    if chat_id is None or bot is None:
        logger.warning("Unable to resolve chat or bot for update_step")
        return

    photo_path = IMAGES_DIR / photo if photo else None

    if photo_path and photo_path.exists():
        media = InputMediaPhoto(media=FSInputFile(photo_path), caption=text, parse_mode="HTML")
        try:
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=keyboard,
            )
            return
        except Exception:
            logger.exception("Failed to edit message media for step %s", photo)

    # Fallback: send text-only update when photo is unavailable
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to edit message caption for step %s", photo)


def _name_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    return keyboard.as_markup()


def _phone_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📱 Отправить контакт", callback_data="order:contact")
    keyboard.button(text="✏️ Ввести вручную", callback_data="order:manual_phone")
    keyboard.button(text="◀️ Назад", callback_data="order:back:name")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _city_branch_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="◀️ Назад", callback_data="order:back:phone")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _confirmation_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Подтвердить", callback_data="order:submit")
    keyboard.button(text="◀️ Назад", callback_data="order:back:city_branch")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


@router.callback_query(F.data == "confirm_order")
async def confirm_order_callback(
    callback_query: CallbackQuery, state: FSMContext, customer_service: CustomerService
) -> None:
    if callback_query.message is None:
        return

    chat_id = callback_query.message.chat.id
    product = get_selected_product(chat_id, callback_query.message.message_id)
    if product is None:
        await callback_query.answer("Товар не найден", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        message_id=callback_query.message.message_id,
        product_id=product.id,
        product_name=product.name,
        product_price=product.price,
    )

    customer = None
    if callback_query.from_user:
        customer = await customer_service.get_customer(callback_query.from_user.id)

    await state.set_state(OrderState.waiting_for_name)

    greeting = (
        f"✨ Вы выбрали: <b>{product.name}</b>\n\n"
        "👤 Введите имя получателя."
    )
    if customer:
        saved_name = customer.get("name")
        saved_phone = customer.get("phone")
        saved_city_branch = customer.get("city") or customer.get("post_office")
        if saved_name or saved_phone or saved_city_branch:
            saved_parts = []
            if saved_name:
                saved_parts.append(f"👤 Имя: {saved_name}")
            if saved_phone:
                saved_parts.append(f"📱 Телефон: {saved_phone}")
            if saved_city_branch:
                saved_parts.append(f"📦 Доставка: {saved_city_branch}")
            if saved_parts:
                greeting += "\n\n" + "\n".join(saved_parts)

    await update_step(
        callback_query,
        state,
        photo="step_name.jpg",
        text=greeting,
        keyboard=_name_keyboard(),
    )
    await callback_query.answer()


@router.message(OrderState.waiting_for_name, F.text)
async def name_handler(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("Пожалуйста, введите Фамилию и Имя для оформления доставки.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await state.update_data(name=name)
    await state.set_state(OrderState.waiting_for_phone)

    data = await state.get_data()
    await update_step(
        message,
        state,
        photo="step_phone.jpg",
        text=(
            f"Вы выбрали: <b>{data.get('product_name', '')}</b>.\n\n"
            "📞 Укажите номер телефона для связи."
        ),
        keyboard=_phone_keyboard(),
    )


@router.callback_query(F.data == "order:contact")
async def request_contact_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    if callback_query.message is None:
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    sent = await callback_query.message.answer(
        "Нажмите кнопку, чтобы отправить контакт, или введите номер вручную.",
        reply_markup=keyboard,
    )

    await state.update_data(contact_prompt_id=sent.message_id)
    await callback_query.answer()


@router.callback_query(F.data == "order:manual_phone")
async def manual_phone_callback(callback_query: CallbackQuery) -> None:
    if callback_query.message is None:
        return
    await callback_query.answer("Введите номер сообщением", show_alert=False)


@router.message(OrderState.waiting_for_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    phone = message.contact.phone_number
    await state.update_data(phone=phone)

    try:
        await message.delete()
    except Exception:
        pass

    prompt_id = data.get("contact_prompt_id")
    if prompt_id:
        try:
            await message.bot.delete_message(message.chat.id, prompt_id)
        except Exception:
            pass

    await state.set_state(OrderState.waiting_for_city_branch)
    await update_step(
        message,
        state,
        photo="step_city_branch.jpg",
        text="Введите город и отделение одним сообщением",
        keyboard=_city_branch_keyboard(),
    )


@router.message(OrderState.waiting_for_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()
    if not phone:
        await message.answer("Пожалуйста, отправьте номер телефона.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await state.update_data(phone=phone)
    await state.set_state(OrderState.waiting_for_city_branch)
    await update_step(
        message,
        state,
        photo="step_city_branch.jpg",
        text="Введите город и отделение одним сообщением",
        keyboard=_city_branch_keyboard(),
    )


@router.message(OrderState.waiting_for_city_branch, F.text)
async def city_branch_handler(message: Message, state: FSMContext) -> None:
    city_branch = message.text.strip()
    if not city_branch:
        await message.answer("Введите город и отделение одним сообщением.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await state.update_data(city_branch=city_branch)
    await state.set_state(OrderState.waiting_for_confirmation)
    data = await state.get_data()

    summary = (
        "<b>📝 Проверьте данные заказа:</b>\n\n"
        f"📦 Товар: <b>{data.get('product_name', '')}</b>\n"
        f"💰 Цена: {data.get('product_price', '')}\n"
        f"👤 Имя: {data.get('name', '')}\n"
        f"📱 Телефон: {data.get('phone', '')}\n"
        f"📦 Доставка: {city_branch}"
    )

    await update_step(
        message,
        state,
        photo="step_confirm.jpg",
        text=summary,
        keyboard=_confirmation_keyboard(),
    )


@router.callback_query(F.data == "order:back:name")
async def back_to_name_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_name)
    data = await state.get_data()

    await update_step(
        callback_query,
        state,
        photo="step_name.jpg",
        text=(
            f"Вы выбрали: <b>{data.get('product_name', '')}</b>.\n\n"
            "👤 Введите имя получателя."
        ),
        keyboard=_name_keyboard(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:back:phone")
async def back_to_phone_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_phone)
    data = await state.get_data()

    await update_step(
        callback_query,
        state,
        photo="step_phone.jpg",
        text=(
            f"Вы выбрали: <b>{data.get('product_name', '')}</b>.\n\n"
            "📞 Укажите номер телефона для связи."
        ),
        keyboard=_phone_keyboard(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:back:city_branch")
async def back_to_city_branch_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_city_branch)

    await update_step(
        callback_query,
        state,
        photo="step_city_branch.jpg",
        text="Введите город и отделение одним сообщением",
        keyboard=_city_branch_keyboard(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:submit")
async def submit_order_callback(
    callback_query: CallbackQuery,
    state: FSMContext,
    customer_service: CustomerService,
    crm_client: LPCRMClient,
) -> None:
    data = await state.get_data()
    user = callback_query.from_user

    product_id = data.get("product_id", "")
    product_price = data.get("product_price", "")
    name = data.get("name", "")
    phone = data.get("phone", "")
    city_branch = data.get("city_branch", "")

    if user:
        await customer_service.save_or_update(
            telegram_id=user.id,
            name=name,
            phone=phone,
            city=city_branch,
            post_office=city_branch,
        )

        crm_order_id = f"{product_id}-{user.id}"
        try:
            await crm_client.send_order(
                order_id=crm_order_id,
                country="UA",
                site="telegram-bot",
                buyer_name=name or user.full_name or user.first_name or user.username or "Telegram User",
                phone=phone,
                comment=f"Order from Telegram bot\nDelivery: {city_branch}",
                product_id=product_id,
                price=product_price,
            )
        except Exception:
            logger.exception("Failed to send order %s to LP-CRM", crm_order_id)

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback_query.message.answer(
        "✅ Заказ оформлен! Мы свяжемся с вами для подтверждения."
    )

    await state.clear()
    await callback_query.answer()


@router.callback_query(StateFilter(OrderState), F.data == "cancel_order")
async def cancel_from_order_callback(
    callback_query: CallbackQuery,
    state: FSMContext,
    product_service: ProductService,
) -> None:
    await state.clear()
    await cancel_order_callback(callback_query, product_service)
