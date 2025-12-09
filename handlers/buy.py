"""Callback handlers for product purchasing flow."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.product_service import Product, ProductService

router = Router()


@dataclass(slots=True)
class StoredCard:
    product: Product
    message_id: int


@dataclass(slots=True)
class SelectedProduct:
    product: Product
    message_id: int


_product_cards: Dict[int, List[StoredCard]] = {}
_selected_products: Dict[int, SelectedProduct] = {}

_welcome_messages: Dict[int, int] = {}


def reset_product_cards(chat_id: int) -> None:
    """Clear stored cards for a chat before sending new ones."""

    _product_cards.pop(chat_id, None)


def clear_selected_product(chat_id: int) -> None:
    """Remove the remembered selected product for a chat."""

    _selected_products.pop(chat_id, None)


def remember_product_card(chat_id: int, product: Product, message_id: int) -> None:
    """Store mapping between chat and message for later edits."""

    cards = _product_cards.setdefault(chat_id, [])
    cards.append(StoredCard(product=product, message_id=message_id))


def remember_selected_product(chat_id: int, product: Product, message_id: int) -> None:
    """Persist the chosen product to keep the order flow in sync."""

    _selected_products[chat_id] = SelectedProduct(product=product, message_id=message_id)


def remember_welcome_message(chat_id: int, message_id: int):
    _welcome_messages[chat_id] = message_id


# NEW — delete welcome message
async def delete_welcome_message(chat_id: int, bot):
    msg_id = _welcome_messages.pop(chat_id, None)
    if msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass



def _build_product_caption(product: Product) -> str:
    return (
        f"<b>{product.name}</b>\n"
        f"{product.description}\n\n"
        f"Цена: {product.price}"
    )


def _build_buy_keyboard(product: Product):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Купить", callback_data=f"buy:{product.id}")
    return keyboard.as_markup()


def _build_confirmation_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🛒 Оформить заказ", callback_data="confirm_order")
    keyboard.button(text="❌ Отмена", callback_data="cancel_order")
    keyboard.adjust(1)
    return keyboard.as_markup()


def get_selected_product(chat_id: int, message_id: int) -> Product | None:
    """Return the selected product for a chat if the message still matches."""

    selection = _selected_products.get(chat_id)
    if selection and selection.message_id == message_id:
        return selection.product
    return None


@router.callback_query(F.data.startswith("buy:"))
async def buy_product_callback(
    callback_query: CallbackQuery, product_service: ProductService
) -> None:
    """Handle product selection and show confirmation screen."""

    if callback_query.message is None:
        return

    chat_id = callback_query.message.chat.id
    product_id = callback_query.data.split(":", maxsplit=1)[1]
    await delete_welcome_message(chat_id, callback_query.message.bot)
    cards = _product_cards.get(chat_id, [])

    product: Product | None = None
    for card in cards:
        if card.product.id == product_id:
            product = card.product
            break

    if product is None:
        products = await product_service.get_products(limit=5)
        for item in products:
            if item.id == product_id:
                product = item
                break

    if product is None:
        await callback_query.answer("Товар не найден", show_alert=True)
        return

    for card in cards:
        try:
            await callback_query.message.bot.delete_message(
                chat_id=chat_id, message_id=card.message_id
            )
        except Exception:
            # Ignore messages that were already removed or cannot be deleted.
            pass

    reset_product_cards(chat_id)
    clear_selected_product(chat_id)

    confirmation_text = f"🛒 Вы выбрали: <b>{product.name}</b>\nЦена: {product.price}"

    confirmation_message = await callback_query.message.bot.send_message(
        chat_id=chat_id,
        text=confirmation_text,
        reply_markup=_build_confirmation_keyboard(),
        parse_mode="HTML",
    )

    remember_selected_product(chat_id, product, confirmation_message.message_id)

    await callback_query.answer()


@router.callback_query(F.data == "cancel_order")
async def cancel_order_callback(
    callback_query: CallbackQuery, product_service: ProductService
) -> None:
    """Return the user to the product list after cancelling."""

    if callback_query.message is None:
        return

    chat_id = callback_query.message.chat.id

    clear_selected_product(chat_id)

    try:
        await callback_query.message.bot.delete_message(
            chat_id=chat_id, message_id=callback_query.message.message_id
        )
    except Exception:
        pass

    reset_product_cards(chat_id)

    products = await product_service.get_products(limit=5)

    for product in products:
        sent_message = await callback_query.message.bot.send_photo(
            chat_id=chat_id,
            photo=product.photo_url,
            caption=_build_product_caption(product),
            parse_mode="HTML",
            reply_markup=_build_buy_keyboard(product),
        )
        remember_product_card(chat_id, product, sent_message.message_id)

    await callback_query.answer()
