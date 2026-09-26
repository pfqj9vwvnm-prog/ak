from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

import database as db
from config import NO_ADS_MESSAGE
from keyboards import subscription_keyboard

router = Router(name="user")

ASK_CODE = "🎬 Kino kodini yuboring (3 xonali raqam), men sizga filmni topib beraman."
CODE_NOT_FOUND = "❌ Bunday kodga ega film topilmadi.\nKodni tekshirib, qaytadan yuboring."
NOT_A_CODE = "🔢 Iltimos, 3 xonali kodni yuboring (masalan: 123)."
SUB_REQUIRED_TEXT = (
    "Botdan foydalanish uchun quyidagi kanal(lar)ga a'zo bo'ling, "
    "so'ngra \"✅ Tekshirish\" tugmasini bosing:"
)
STILL_NOT_SUBSCRIBED = "❗️ Siz hali barcha kanallarga a'zo bo'lmadingiz."


async def get_unsubscribed_channels(bot: Bot, user_id: int) -> list:
    channels = await db.list_channels()
    unsubscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
            if member.status in ("left", "kicked"):
                unsubscribed.append(ch)
        except Exception:
            # Бот не состоит в канале / нет прав / канал недоступен —
            # пропускаем проверку по этому каналу, чтобы не блокировать пользователя.
            continue
    return unsubscribed


async def send_welcome_body(message: Message) -> None:
    if await db.count_codes() == 0:
        await message.answer(NO_ADS_MESSAGE)
    else:
        await message.answer(ASK_CODE)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    await db.touch_user(message.from_user.id)
    unsubscribed = await get_unsubscribed_channels(bot, message.from_user.id)
    if unsubscribed:
        await message.answer(SUB_REQUIRED_TEXT, reply_markup=subscription_keyboard(unsubscribed))
        return
    await send_welcome_body(message)


@router.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery, bot: Bot) -> None:
    unsubscribed = await get_unsubscribed_channels(bot, callback.from_user.id)
    if unsubscribed:
        await callback.answer(STILL_NOT_SUBSCRIBED, show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    await send_welcome_body(callback.message)


@router.message(F.text.regexp(r"^\d{3}$"))
async def handle_code(message: Message, bot: Bot) -> None:
    await db.touch_user(message.from_user.id)
    unsubscribed = await get_unsubscribed_channels(bot, message.from_user.id)
    if unsubscribed:
        await message.answer(SUB_REQUIRED_TEXT, reply_markup=subscription_keyboard(unsubscribed))
        return

    code = message.text.strip()
    entry = await db.get_code(code)
    await db.log_search(message.from_user.id, code, found=entry is not None)

    if not entry:
        await message.answer(CODE_NOT_FOUND)
        return

    await db.increment_hits(code)
    await message.answer_photo(entry["photo_file_id"], caption=f"🎬 {entry['movie_name']}")


@router.message(F.text & ~F.text.startswith("/"))
async def handle_other_text(message: Message) -> None:
    await message.answer(NOT_A_CODE)
