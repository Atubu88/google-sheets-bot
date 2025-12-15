"""Order flow handlers with media-based step updates (aiogram 3)."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    FSInputFile,
    InputMediaPhoto,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.buy import build_product_caption, cancel_order_callback, get_selected_product
from services.product_service import ProductService
from services.customer_service import CustomerService
from services.crm_client import LPCRMClient
from services.settings_service import SettingsService


router = Router()
logger = logging.getLogger(__name__)

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


# ===================== STATES =====================

class OrderState(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_city_branch = State()
    waiting_for_confirmation = State()


# ===================== KEYBOARDS =====================

def name_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="order:back:product")
    kb.button(text="❌ Отмена", callback_data="cancel_order")
    kb.adjust(1)
    return kb.as_markup()


def confirm_existing_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить заказ", callback_data="order:confirm_existing")
    kb.button(text="✏️ Изменить данные", callback_data="order:edit_existing")
    kb.button(text="❌ Отмена", callback_data="cancel_order")
    kb.adjust(1)
    return kb.as_markup()

async def go_to_city_branch_step(
    source: Message,
    state: FSMContext,
):
    await state.set_state(OrderState.waiting_for_city_branch)

    await update_step(
        source,
        state,
        "step_city_branch.jpg",
        (
            "📦 Введите город и номер отделения одним сообщением.\n\n"
            "Пример:\n"
            "Киев, отделение №7"
        ),
        city_branch_kb(),
    )



def phone_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Отправить контакт", callback_data="order:contact")
    kb.button(text="✏️ Ввести вручную", callback_data="order:manual_phone")
    kb.button(text="◀️ Назад", callback_data="order:back:name")
    kb.button(text="❌ Отмена", callback_data="cancel_order")
    kb.adjust(1)
    return kb.as_markup()


def city_branch_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="order:back:phone")
    kb.button(text="❌ Отмена", callback_data="cancel_order")
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="order:submit")
    kb.button(text="◀️ Назад", callback_data="order:back:city_branch")
    kb.button(text="❌ Отмена", callback_data="cancel_order")
    kb.adjust(1)
    return kb.as_markup()


# ===================== CORE UPDATE =====================

async def update_step(
    source: CallbackQuery | Message,
    state: FSMContext,
    image_name: str,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """Safely update message media for order steps."""

    if not text:
        text = " "

    data = await state.get_data()
    message_id = data.get("message_id")
    if not message_id:
        logger.warning("update_step: no message_id")
        return

    if isinstance(source, CallbackQuery):
        chat_id = source.message.chat.id
        bot = source.message.bot
    else:
        chat_id = source.chat.id
        bot = source.bot

    image_path = IMAGES_DIR / image_name

    try:
        if image_path.exists():
            media = InputMediaPhoto(
                media=FSInputFile(image_path),
                caption=text,
                parse_mode="HTML",
            )
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=keyboard,
            )
        else:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
    except Exception:
        logger.exception("Failed to update step %s", image_name)


async def notify_orders_group(
    bot,
    settings_service: SettingsService,
    *,
    name: str,
    phone: str,
    product_name: str,
    product_price: str,
    delivery: str,
) -> None:
    """Send order summary to configured group if available."""

    orders_group_id = await settings_service.get("orders_group_id")
    if not orders_group_id:
        return

    summary = (
        "🆕 Новый заказ\n"
        f"👤 Клиент: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"📦 Товар: {product_name}\n"
        f"💰 Цена: {product_price}\n"
        f"🏙️ Город/Отделение: {delivery}"
    )

    try:
        await bot.send_message(chat_id=int(orders_group_id), text=summary)
    except Exception:
        logger.exception("Failed to send order summary to group %s", orders_group_id)


# ===================== FLOW START =====================

@router.callback_query(F.data == "confirm_order")
async def confirm_order_callback(
    callback: CallbackQuery,
    state: FSMContext,
    customer_service: CustomerService,
):
    chat_id = callback.message.chat.id
    product = get_selected_product(chat_id, callback.message.message_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        message_id=callback.message.message_id,
        product_id=product.id,
        product_name=product.name,
        product_price=product.price,
    )

    customer = await customer_service.get_customer(callback.from_user.id)

    # ✅ ВТОРОЙ КОНТАКТ
    if customer:
        city = (customer.get("city") or "").strip()
        post_office = (customer.get("post_office") or "").strip()

        # 🧼 защита от дублей старых данных
        if post_office and post_office == city:
            post_office = ""

        delivery = ", ".join(filter(None, [city, post_office]))

        text = (
            f"✨ Вы выбрали: <b>{product.name}</b>\n\n"
            "Мы нашли ваши данные:\n"
            f"👤 Имя: {customer.get('name')}\n"
            f"📱 Телефон: {customer.get('phone')}\n"
            f"📦 Доставка: {delivery}\n\n"
            "Использовать эти данные?"
        )

        await update_step(
            callback,
            state,
            "step_confirm.jpg",
            text,
            confirm_existing_kb(),
        )
        await callback.answer()
        return

    # 🆕 ПЕРВЫЙ КОНТАКТ
    await state.set_state(OrderState.waiting_for_name)
    await update_step(
        callback,
        state,
        "step_name.jpg",
        f"✨ Вы выбрали: <b>{product.name}</b>\n\n👤 Укажите имя и фамилию получателя посылки",
        name_kb(),
    )
    await callback.answer()



# ===================== NAME =====================

@router.message(OrderState.waiting_for_name, F.text)
async def name_handler(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        return

    await message.delete()
    await state.update_data(name=name)
    await state.set_state(OrderState.waiting_for_phone)

    data = await state.get_data()
    await update_step(
        message,
        state,
        "step_phone.jpg",
        f"Вы выбрали: <b>{data['product_name']}</b>\n\n📞 Укажите номер телефона.",
        phone_kb(),
    )


# ===================== PHONE =====================

@router.callback_query(F.data == "order:contact")
async def phone_contact_request(callback: CallbackQuery, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    sent = await callback.message.answer("Отправьте контакт:", reply_markup=kb)
    await state.update_data(contact_prompt_id=sent.message_id)
    await callback.answer()


@router.message(OrderState.waiting_for_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext):
    await message.delete()
    data = await state.get_data()

    if data.get("contact_prompt_id"):
        try:
            await message.bot.delete_message(message.chat.id, data["contact_prompt_id"])
        except Exception:
            pass

    await state.update_data(phone=message.contact.phone_number)

    await go_to_city_branch_step(message, state)


@router.message(OrderState.waiting_for_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext):
    await message.delete()
    await state.update_data(phone=message.text.strip())

    await go_to_city_branch_step(message, state)


# ===================== CITY =====================

@router.message(OrderState.waiting_for_city_branch, F.text)
async def city_branch_handler(message: Message, state: FSMContext):
    await message.delete()
    await state.update_data(city_branch=message.text.strip())
    await state.set_state(OrderState.waiting_for_confirmation)

    d = await state.get_data()
    summary = (
        "<b>📝 Проверьте данные заказа:</b>\n\n"
        f"📦 Товар: <b>{d['product_name']}</b>\n"
        f"💰 Цена: {d['product_price']}\n"
        f"👤 Имя: {d['name']}\n"
        f"📱 Телефон: {d['phone']}\n"
        f"📦 Доставка: {d['city_branch']}"
    )

    await update_step(message, state, "step_confirm.jpg", summary, confirm_kb())


# ===================== BACK =====================

@router.callback_query(F.data == "order:back:name")
async def back_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_for_name)
    d = await state.get_data()
    await update_step(
        cb,
        state,
        "step_name.jpg",
        "👤 Укажите имя и фамилию получателя посылки",
        name_kb(),
    )
    await cb.answer()


@router.callback_query(F.data == "order:back:phone")
async def back_phone(cb: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_for_phone)
    await update_step(cb, state, "step_phone.jpg", "📞 Укажите номер телефона.", phone_kb())
    await cb.answer()


@router.callback_query(F.data == "order:back:city_branch")
async def back_city(cb: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_for_city_branch)
    await update_step(cb, state, "step_city_branch.jpg", "Введите город и отделение.", city_branch_kb())
    await cb.answer()


# ===================== SUBMIT =====================
@router.callback_query(F.data == "order:submit")
async def submit_order(
    callback: CallbackQuery,
    state: FSMContext,
    customer_service: CustomerService,
    crm_client: LPCRMClient,
    settings_service: SettingsService,
):
    data = await state.get_data()
    user = callback.from_user

    raw_delivery = data.get("city_branch", "").strip()

    # ✅ корректно разделяем
    if "," in raw_delivery:
        city, post_office = map(str.strip, raw_delivery.split(",", 1))
    else:
        city = raw_delivery
        post_office = ""

    # ---- сохраняем в БД уже ЧИСТО ----
    await customer_service.save_or_update(
        telegram_id=user.id,
        name=data["name"],
        phone=data["phone"],
        city=city,
        post_office=post_office,
    )

    # ---- красиво формируем для CRM ----
    delivery_parts = []
    if city:
        delivery_parts.append(city)
    if post_office:
        delivery_parts.append(post_office)

    delivery_text = ", ".join(delivery_parts)

    try:
        await crm_client.send_order(
            order_id=f"{data['product_id']}-{user.id}",
            country="UA",
            site="telegram-bot",
            buyer_name=data["name"],
            phone=data["phone"],
            comment=f"Delivery: {delivery_text}",
            product_id=data["product_id"],
            price=data["product_price"],
        )
    except Exception:
        logger.exception("CRM error")

    await notify_orders_group(
        callback.message.bot,
        settings_service,
        name=data["name"],
        phone=data["phone"],
        product_name=data["product_name"],
        product_price=str(data["product_price"]),
        delivery=delivery_text or "-",
    )

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ Заказ оформлен!")
    await state.clear()
    await callback.answer()



# ===================== CANCEL =====================

@router.callback_query(StateFilter(OrderState), F.data == "cancel_order")
async def cancel_order(
    callback: CallbackQuery,
    state: FSMContext,
    product_service: ProductService,
):
    await state.clear()
    await cancel_order_callback(callback, product_service)

@router.callback_query(F.data == "order:back:product")
async def back_to_product_card(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not callback.message:
        return

    data = await state.get_data()
    chat_id = callback.message.chat.id
    message_id = data.get("message_id", callback.message.message_id)

    product = get_selected_product(chat_id, message_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.clear()

    caption = build_product_caption(product)

    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Оформить заказ", callback_data="confirm_order")
    kb.button(text="❌ Отмена", callback_data="cancel_order")
    kb.adjust(1)

    try:
        await callback.message.bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=InputMediaPhoto(
                media=product.photo_url,
                caption=caption,
                parse_mode="HTML",
            ),
            reply_markup=kb.as_markup(),
        )
    except Exception:
        # fallback если фото не меняется
        await callback.message.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )

    await callback.answer()

@router.callback_query(F.data == "order:confirm_existing")
async def confirm_existing_order(
    callback: CallbackQuery,
    state: FSMContext,
    customer_service: CustomerService,
    crm_client: LPCRMClient,
    settings_service: SettingsService,
):
    data = await state.get_data()
    customer = await customer_service.get_customer(callback.from_user.id)

    if not customer:
        await callback.answer("Данные не найдены", show_alert=True)
        return

    delivery_parts = []
    city = (customer.get("city") or "").strip()
    post_office = (customer.get("post_office") or "").strip()

    if city:
        delivery_parts.append(city)
    if post_office:
        delivery_parts.append(post_office)

    delivery_text = ", ".join(delivery_parts)

    await crm_client.send_order(
        order_id=f"{data['product_id']}-{callback.from_user.id}",
        country="UA",
        site="telegram-bot",
        buyer_name=customer["name"],
        phone=customer["phone"],
        comment=f"Delivery: {delivery_text}",
        product_id=data["product_id"],
        price=data["product_price"],
    )

    await notify_orders_group(
        callback.message.bot,
        settings_service,
        name=customer["name"],
        phone=customer["phone"],
        product_name=data["product_name"],
        product_price=str(data["product_price"]),
        delivery=delivery_text or "-",
    )

    await callback.message.edit_reply_markup(None)
    await callback.message.answer("✅ Заказ оформлен!")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "order:edit_existing")
async def edit_existing_data(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.set_state(OrderState.waiting_for_name)
    await update_step(
        callback,
        state,
        "step_name.jpg",
        "👤 Укажите имя и фамилию получателя посылки",
        name_kb(),
    )
    await callback.answer()
