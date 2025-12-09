"""Order flow handlers for collecting delivery details."""
from __future__ import annotations

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
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.buy import _product_cards, cancel_order_callback
from services.order_service import OrderService
from services.product_service import ProductService


router = Router()


class OrderState(StatesGroup):
    """States for guiding the user through order creation."""

    waiting_for_phone = State()
    waiting_for_city = State()
    waiting_for_branch = State()
    waiting_for_confirmation = State()


def _find_product(chat_id: int, message_id: int):
    for card in _product_cards.get(chat_id, []):
        if card.message_id == message_id:
            return card.product
    return None


def _phone_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📱 Отправить контакт", callback_data="order:contact")
    keyboard.button(text="✏️ Ввести вручную", callback_data="order:manual_phone")
    keyboard.button(text="◀️ Назад", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _city_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="◀️ Назад", callback_data="order:back:phone")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _branch_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="◀️ Назад", callback_data="order:back:city")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def _confirmation_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Подтвердить", callback_data="order:submit")
    keyboard.button(text="◀️ Назад", callback_data="order:back:branch")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


async def _prompt_phone(callback_query: CallbackQuery, product_name: str) -> None:
    await callback_query.message.bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption=(
            f"Вы выбрали: <b>{product_name}</b>.\n\n"
            "📞 Укажите номер телефона для связи."
        ),
        reply_markup=_phone_keyboard(),
    )


async def _prompt_branch(message: Message, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_branch)
    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=(await state.get_data())["message_id"],
        text="📦 Укажите отделение или адрес для доставки.",
        reply_markup=_branch_keyboard(),
    )


async def _show_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(OrderState.waiting_for_confirmation)

    summary = (
        "<b>Проверьте данные заказа:</b>\n\n"
        f"Товар: {data['product_name']}\n"
        f"Цена: {data['product_price']}\n"
        f"Телефон: {data['phone']}\n"
        f"Город: {data['city']}\n"
        f"Отделение: {data['branch']}"
    )

    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["message_id"],
        text=summary,
        reply_markup=_confirmation_keyboard(),
    )


@router.callback_query(F.data == "confirm_order")
async def confirm_order_callback(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    if callback_query.message is None:
        return

    chat_id = callback_query.message.chat.id
    product = _find_product(chat_id, callback_query.message.message_id)
    if product is None:
        await callback_query.answer("Товар не найден", show_alert=True)
        return

    await state.set_state(OrderState.waiting_for_phone)
    await state.update_data(
        message_id=callback_query.message.message_id,
        product_id=product.id,
        product_name=product.name,
        product_price=product.price,
    )

    await _prompt_phone(callback_query, product.name)
    await callback_query.answer()


@router.callback_query(F.data == "order:contact")
async def request_contact_callback(callback_query: CallbackQuery) -> None:
    if callback_query.message is None:
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback_query.message.answer(
        "Нажмите кнопку, чтобы отправить контакт, или введите номер вручную.",
        reply_markup=keyboard,
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:manual_phone")
async def manual_phone_callback(callback_query: CallbackQuery) -> None:
    if callback_query.message is None:
        return

    await callback_query.answer("Введите номер сообщением", show_alert=False)


@router.message(OrderState.waiting_for_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext) -> None:
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await message.answer("Принял номер. Продолжим!", reply_markup=ReplyKeyboardRemove())

    await state.update_data(city=None, branch=None)
    await _prompt_city_from_message(message, state)


@router.message(OrderState.waiting_for_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()
    if not phone:
        await message.answer("Пожалуйста, отправьте номер телефона.")
        return

    await state.update_data(phone=phone, city=None, branch=None)
    await _prompt_city_from_message(message, state)


async def _prompt_city_from_message(message: Message, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_city)
    data = await state.get_data()
    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["message_id"],
        text="🏙️ Введите город доставки.",
        reply_markup=_city_keyboard(),
    )


@router.callback_query(F.data == "order:back:phone")
async def back_to_phone_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_phone)
    data = await state.get_data()
    await callback_query.message.bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=data.get("message_id", callback_query.message.message_id),
        caption=(
            f"Вы выбрали: <b>{data.get('product_name', '')}</b>.\n\n"
            "📞 Укажите номер телефона для связи."
        ),
        reply_markup=_phone_keyboard(),
    )
    await callback_query.answer()


@router.message(OrderState.waiting_for_city, F.text)
async def city_handler(message: Message, state: FSMContext) -> None:
    city = message.text.strip()
    if not city:
        await message.answer("Введите город текстом.")
        return

    await state.update_data(city=city, branch=None)
    await _prompt_branch(message, state)


@router.callback_query(F.data == "order:back:city")
async def back_to_city_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_city)
    await callback_query.message.bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=(await state.get_data())["message_id"],
        text="🏙️ Введите город доставки.",
        reply_markup=_city_keyboard(),
    )
    await callback_query.answer()


@router.message(OrderState.waiting_for_branch, F.text)
async def branch_handler(message: Message, state: FSMContext) -> None:
    branch = message.text.strip()
    if not branch:
        await message.answer("Введите отделение или адрес.")
        return

    await state.update_data(branch=branch)
    await _show_confirmation(message, state)


@router.callback_query(F.data == "order:back:branch")
async def back_to_branch_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderState.waiting_for_branch)
    await callback_query.message.bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=(await state.get_data())["message_id"],
        text="📦 Укажите отделение или адрес для доставки.",
        reply_markup=_branch_keyboard(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "order:submit")
async def submit_order_callback(
    callback_query: CallbackQuery,
    state: FSMContext,
    order_service: OrderService,
    product_service: ProductService,
) -> None:
    data = await state.get_data()
    await order_service.append_order(
        user_id=callback_query.from_user.id if callback_query.from_user else None,
        chat_id=callback_query.message.chat.id if callback_query.message else 0,
        product_id=data.get("product_id", ""),
        product_name=data.get("product_name", ""),
        product_price=data.get("product_price", ""),
        phone=data.get("phone", ""),
        city=data.get("city", ""),
        branch=data.get("branch", ""),
    )

    await callback_query.message.answer(
        "✅ Заказ оформлен! Мы свяжемся с вами для подтверждения."
    )
    await state.clear()
    await cancel_order_callback(callback_query, product_service)
    await callback_query.answer()


@router.callback_query(StateFilter(OrderState), F.data == "cancel_order")
async def cancel_from_order_callback(
    callback_query: CallbackQuery,
    state: FSMContext,
    product_service: ProductService,
) -> None:
    await state.clear()
    await cancel_order_callback(callback_query, product_service)
