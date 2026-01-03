"""Callback handlers for product purchasing flow."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.product_service import Product, ProductService

router = Router()

# ===================== PATHS =====================

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"
BANNER_NAME = "step_order_confirm.jpg"


# ===================== DATA STRUCTURES =====================

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


# ===================== MEMORY HELPERS =====================

def reset_product_cards(chat_id: int) -> None:
    _product_cards.pop(chat_id, None)


def clear_selected_product(chat_id: int) -> None:
    _selected_products.pop(chat_id, None)


def remember_product_card(chat_id: int, product: Product, message_id: int) -> None:
    cards = _product_cards.setdefault(chat_id, [])
    cards.append(StoredCard(product=product, message_id=message_id))


def remember_selected_product(chat_id: int, product: Product, message_id: int) -> None:
    _selected_products[chat_id] = SelectedProduct(product=product, message_id=message_id)


def remember_welcome_message(chat_id: int, message_id: int):
    _welcome_messages[chat_id] = message_id


async def delete_welcome_message(chat_id: int, bot):
    msg_id = _welcome_messages.pop(chat_id, None)
    if msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass


# ===================== VIEW HELPERS =====================

def _build_description_link(description: str) -> str:
    description = description.strip()
    if not description:
        return ""
    return f'<a href="{description}">Детальніше</a>'


def format_price(price: str) -> str:
    return f"{price} грн"


def build_price_block(price: str, old_price: str | None) -> str:
    formatted_price = format_price(price)
    if old_price:
        formatted_old_price = format_price(old_price)
        return (
            f"<s>Ціна: {formatted_old_price}</s>\n"
            f"Ціна зі знижкою: <b>{formatted_price}</b>"
        )
    return f"Ціна: <b>{formatted_price}</b>"



def build_product_caption(product: Product) -> str:
    description_link = _build_description_link(product.description)
    short_desc = product.short_desc.strip()
    lines: list[str] = [f"<b>{product.name}</b>", ""]

    if short_desc:
        if description_link:
            lines.append(f"{short_desc} {description_link}")
        else:
            lines.append(short_desc)

    if not short_desc and description_link:
        lines.append(f"📖 {description_link}")

    if short_desc or description_link:
        lines.append("")

    lines.append(build_price_block(product.price, product.old_price))
    return "\n".join(lines)


def _build_buy_keyboard(product: Product):
    kb = InlineKeyboardBuilder()
    kb.button(text="Купити", callback_data=f"buy:{product.id}")
    return kb.as_markup()


def _build_confirmation_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Оформити замовлення", callback_data="confirm_order")
    kb.button(text="❌ Скасувати", callback_data="cancel_order")
    kb.adjust(1)
    return kb.as_markup()



def get_selected_product(chat_id: int, message_id: int) -> Product | None:
    selection = _selected_products.get(chat_id)
    if selection and selection.message_id == message_id:
        return selection.product
    return None


# ===================== CALLBACKS =====================
@router.callback_query(F.data.startswith("buy:"))
async def buy_product_callback(
    callback_query: CallbackQuery,
    product_service: ProductService,
) -> None:

    if callback_query.message is None:
        return

    chat_id = callback_query.message.chat.id
    product_id = callback_query.data.split(":", 1)[1]

    await delete_welcome_message(chat_id, callback_query.message.bot)

    # --- find product ---
    product: Product | None = None
    for card in _product_cards.get(chat_id, []):
        if card.product.id == product_id:
            product = card.product
            break

    if product is None:
        for item in await product_service.get_products():
            if item.id == product_id:
                product = item
                break

    if not product:
        await callback_query.answer("Товар не знайдено", show_alert=True)
        return

    # --- intro text ---
    await callback_query.message.bot.send_message(
        chat_id=chat_id,
        text=(
            "🎉 Чудовий вибір!\n"
            f"📦 <b>{product.name}</b>\n"
            "Готові оформити замовлення? ⬇️"
        ),
        parse_mode="HTML",
    )

    # --- banner or fallback ---
    banner_path = IMAGES_DIR / BANNER_NAME
    photo = FSInputFile(banner_path) if banner_path.exists() else product.photo_url

    caption = build_product_caption(product)

    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Оформити замовлення", callback_data="confirm_order")
    kb.button(text="❌ Скасувати", callback_data="cancel_order")
    kb.adjust(1)

    new_msg = await callback_query.message.bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        caption=caption,
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )

    remember_selected_product(chat_id, product, new_msg.message_id)
    await callback_query.answer()


@router.callback_query(F.data == "cancel_order")
async def cancel_order_callback(
    callback_query: CallbackQuery,
    product_service: ProductService,
) -> None:

    if callback_query.message is None:
        return

    chat_id = callback_query.message.chat.id
    clear_selected_product(chat_id)
    reset_product_cards(chat_id)

    try:
        await callback_query.message.bot.delete_message(
            chat_id=chat_id,
            message_id=callback_query.message.message_id,
        )
    except Exception:
        pass

    for product in await product_service.get_products():
        sent = await callback_query.message.bot.send_photo(
            chat_id=chat_id,
            photo=product.photo_url,
            caption=build_product_caption(product),
            parse_mode="HTML",
            reply_markup=_build_buy_keyboard(product),
        )
        remember_product_card(chat_id, product, sent.message_id)

    await callback_query.answer()