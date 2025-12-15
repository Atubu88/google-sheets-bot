# services/after_order_promo.py
from pathlib import Path

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

# === НАСТРОЙКИ (просто и явно) ===
GROUP_URL = "https://t.me/your_group"   # ← сюда вставишь ссылку
IMAGE_NAME = "after_order_promo.jpg"

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


async def send_after_order_promo(bot, chat_id: int) -> None:
    """Send promo message with image and group link after order."""

    image_path = IMAGES_DIR / IMAGE_NAME

    caption = (
        "🎉 <b>Спасибо за заказ!</b>\n\n"
        "Присоединяйтесь к нашему Telegram-сообществу 👇\n"
        "— акции\n"
        "— новинки\n"
        "— розыгрыши"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👉 Перейти в группу",
                    url=GROUP_URL,
                )
            ]
        ]
    )

    if image_path.exists():
        await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(image_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        # fallback если фото вдруг пропало
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
