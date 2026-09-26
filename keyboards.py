from typing import Dict, List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def subscription_keyboard(channels: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in channels:
        title = ch.get("title") or "Kanal"
        url = ch.get("url")
        if url:
            builder.row(InlineKeyboardButton(text=f"📢 {title}", url=url))
    builder.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub"))
    return builder.as_markup()
