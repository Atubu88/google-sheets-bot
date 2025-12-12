"""Order flow handlers for collecting delivery details."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.buy import cancel_order_callback, get_selected_product
from services.product_service import ProductService
from services.crm_client import LPCRMClient
from services.customer_service import CustomerService


router = Router()
logger = logging.getLogger(__name__)


class OrderState(StatesGroup):
    """States for guiding the user through order creation."""

    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_city_branch = State()
    waiting_for_confirmation = State()


def _name_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _phone_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📱 Отправить контакт", callback_data="order:contact")
    keyboard.button(text="✏️ Ввести вручную", callback_data="order:manual_phone")
    keyboard.button(text="◀️ Назад", callback_data="order:back:name")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _city_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="◀️ Назад", callback_data="order:back:phone")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _confirmation_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Подтвердить", callback_data="order:submit")
    keyboard.button(text="◀️ Назад", callback_data="order:back:city")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _autofill_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Да", callback_data="order:auto_use")
    keyboard.button(text="Изменить", callback_data="order:auto_edit")
    keyboard.adjust(1)
    return keyboard.as_markup()


async def _prompt_name(callback_query: CallbackQuery, product_name: str) -> None:
    await callback_query.message.bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=(
            f"Вы выбрали: <b>{product_name}</b>.\n\n"
            "👤 Введите имя получателя."
        ),
        reply_markup=_name_keyboard(),
        parse_mode="HTML",
    )


async def _prompt_phone(message: Message, state: FSMContext, product_name: str) -> None:
    await state.set_state(OrderState.waiting_for_phone)
    data = await state.get_data()

    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["message_id"],
        text=(
            f"Вы выбрали: <b>{product_name}</b>.\n\n"
            "📞 Укажите номер телефона для связи."
        ),
        reply_markup=_phone_keyboard(),
        parse_mode="HTML",
    )


async def _show_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(OrderState.waiting_for_confirmation)

    summary = (
        "<b>📝 Проверьте данные заказа:</b>\n\n"
        f"📦 Товар: <b>{data['product_name']}</b>\n"
        f"💰 Цена: {data['product_price']}\n"
        f"👤 Имя: {data['name']}\n"
        f"📱 Телефон: {data['phone']}\n"
        f"📦 Доставка: {data['city_branch']}"
    )

    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["message_id"],
        text=summary,
        reply_markup=_confirmation_keyboard(),
        parse_mode="HTML",
    )


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
        name=None,
        phone=None,
        city_branch=None,
    )

    customer = None
    if callback_query.from_user:
        customer = await customer_service.get_customer(callback_query.from_user.id)

    if customer:
        delivery = customer.get("city") or ""
        post_office = customer.get("post_office") or ""
        if post_office and post_office != delivery:
            delivery = f"{delivery}, {post_office}" if delivery else post_office

        text = (
            f"✨ Вы выбрали: <b>{product.name}</b>\n\n"
            "🔎 Найдены ваши данные:\n"
            f"👤 Имя: {customer['name']}\n"
            f"📱 Телефон: {customer['phone']}\n"
            f"📦 Доставка: {delivery}\n\n"
            "Использовать эти данные?"
        )

        await callback_query.message.bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=text,
            reply_markup=_autofill_keyboard(),
            parse_mode="HTML",
        )
        await callback_query.answer()
        return

    await state.set_state(OrderState.waiting_for_name)
    await _prompt_name(callback_query, product.name)
    await callback_query.answer()

@router.callback_query(F.data == "order:auto_use")
async def auto_use_customer_callback(
    callback_query: CallbackQuery,
    state: FSMContext,
    customer_service: CustomerService,
    crm_client: LPCRMClient,
) -> None:
    if callback_query.message is None or callback_query.from_user is None:
        return

    data = await state.get_data()
    product_id = data.get("product_id")
    product_price = data.get("product_price")
    product_name = data.get("product_name")

    if not product_id:
        await callback_query.answer("Не удалось определить товар", show_alert=True)
        return

    # Получаем клиента из SQLite
    customer = await customer_service.get_customer(callback_query.from_user.id)

    # Клиента нет → запрашиваем данные вручную
    if not customer:
        await state.set_state(OrderState.waiting_for_name)
        await state.update_data(name=None, phone=None, city_branch=None)
        await _prompt_name(callback_query, product_name or "")
        await callback_query.answer("Заполните данные вручную", show_alert=True)
        return

    # ---------------------------
    # ✔ Безопасное извлечение данных клиента
    # ---------------------------
    raw_name = (customer.get("name") or "").strip()
    raw_phone = (customer.get("phone") or "").strip()

    safe_buyer_name = (
        raw_name
        or callback_query.from_user.full_name
        or callback_query.from_user.first_name
        or callback_query.from_user.username
        or "Telegram User"
    )

    safe_phone = raw_phone
    # ---------------------------

    crm_order_id = f"{product_id}-{callback_query.from_user.id}"

    delivery = customer.get("city") or ""
    post_office = customer.get("post_office") or ""
    if post_office and post_office != delivery:
        delivery = f"{delivery}, {post_office}" if delivery else post_office

    try:
        await crm_client.send_order(
            order_id=crm_order_id,
            country="UA",
            site="telegram-bot",
            buyer_name=safe_buyer_name,
            phone=safe_phone,
            comment=f"Order from Telegram bot\nDelivery: {delivery}",
            product_id=product_id,
            price=product_price,
        )
    except Exception:
        logger.exception("Failed to send order %s to LP-CRM", crm_order_id)

    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback_query.message.answer("Заказ оформлен")
    await state.clear()
    await callback_query.answer()




@router.callback_query(F.data == "order:auto_edit")
async def auto_edit_customer_callback(
    callback_query: CallbackQuery,
    state: FSMContext,
) -> None:
    if callback_query.message is None:
        return

    data = await state.get_data()
    product_name = data.get("product_name", "")

    await state.set_state(OrderState.waiting_for_name)
    await state.update_data(name=None, phone=None, city_branch=None)
    await _prompt_name(callback_query, product_name)
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

    await state.update_data(name=name, phone=None, city_branch=None)
    data = await state.get_data()

    await _prompt_phone(message, state, data.get("product_name", ""))


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

    # 🔥 ВАЖНО: сохраняем ID служебного сообщения
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

    # сохраняем номер
    phone = message.contact.phone_number
    await state.update_data(phone=phone)

    # 1 — удалить зелёную карточку контакта
    try:
        await message.delete()
    except:
        pass

    # 2 — удалить служебное сообщение "Нажмите кнопку..."
    prompt_id = data.get("contact_prompt_id")
    if prompt_id:
        try:
            await message.bot.delete_message(message.chat.id, prompt_id)
        except:
            pass

    await state.update_data(city_branch=None)

    # продолжить оформление
    await prompt_city_branch(message, state)


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
    await state.update_data(phone=phone, city_branch=None)
    await prompt_city_branch(message, state)


async def prompt_city_branch(message: Message, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_city_branch)
    data = await state.get_data()

    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["message_id"],
        text="Введите город и отделение одним сообщением",
        reply_markup=_city_keyboard(),
    )


@router.callback_query(F.data == "order:back:phone")
async def back_to_phone_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_phone)
    data = await state.get_data()

    await callback_query.message.bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=data.get("message_id", callback_query.message.message_id),
        text=(
            f"Вы выбрали: <b>{data.get('product_name', '')}</b>.\n\n"
            "📞 Укажите номер телефона для связи."
        ),
        reply_markup=_phone_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:back:name")
async def back_to_name_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_name)
    data = await state.get_data()

    await callback_query.message.bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=data.get("message_id", callback_query.message.message_id),
        text=(
            f"Вы выбрали: <b>{data.get('product_name', '')}</b>.\n\n"
            "👤 Введите имя получателя."
        ),
        reply_markup=_name_keyboard(),
        parse_mode="HTML",
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:back:city")
async def back_to_city_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_city_branch)

    await callback_query.message.bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=(await state.get_data())["message_id"],
        text="Введите город и отделение одним сообщением",
        reply_markup=_city_keyboard(),
    )
    await callback_query.answer()


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
    await _show_confirmation(message, state)


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

    if user:
        crm_order_id = f"{product_id}-{user.id}"
        try:
            await crm_client.send_order(
                order_id=crm_order_id,
                country="UA",
                site="telegram-bot",
                buyer_name=name or user.full_name or user.first_name or user.username or "Telegram User",
                phone=phone,
                comment="Order from Telegram bot",
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
