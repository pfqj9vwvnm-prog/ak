from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message

import database as db
from config import ADMIN_IDS

router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in ADMIN_IDS


# Все хендлеры в этом роутере доступны только администраторам (разработчикам).
router.message.filter(IsAdmin())


def _parse_command_from_caption(caption: str) -> tuple[str, str]:
    """Возвращает (команда без / и без @botname, аргументы) из подписи к фото."""
    parts = caption.strip().split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


async def _process_addcode(message: Message, args: str) -> None:
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "⚠️ Неверный формат.\n"
            "Нужно: код (3 цифры) и название фильма в подписи к фото.\n"
            "Пример подписи: /addcode 123 Мстители"
        )
        return

    code, movie_name = parts[0], parts[1].strip()
    if not (code.isdigit() and len(code) == 3):
        await message.answer("⚠️ Код должен состоять ровно из 3 цифр.")
        return

    photo_file_id = message.photo[-1].file_id
    is_new = await db.upsert_code(code, movie_name, photo_file_id)
    action = "добавлен" if is_new else "обновлён"
    await message.answer(f"✅ Код {code} {action}: «{movie_name}»")


@router.message(F.photo)
async def handle_admin_photo(message: Message) -> None:
    caption = message.caption or ""
    if not caption:
        return  # Фото без подписи от админа — не команда, игнорируем

    cmd, args = _parse_command_from_caption(caption)
    if cmd == "addcode":
        await _process_addcode(message, args)
    # Прочие подписи к фото не распознаём — молча игнорируем


@router.message(Command("addcode"))
async def cmd_addcode_no_photo(message: Message) -> None:
    await message.answer(
        "⚠️ Отправьте фото с подписью в формате:\n"
        "/addcode <3 цифры> <Название фильма>\n\n"
        "Пример подписи к фото: /addcode 123 Мстители"
    )


@router.message(Command("delcode"))
async def cmd_delcode(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    if not (args.isdigit() and len(args) == 3):
        await message.answer("Использование: /delcode <3 цифры>\nПример: /delcode 123")
        return

    deleted = await db.delete_code(args)
    if deleted:
        await message.answer(f"🗑 Код {args} удалён.")
    else:
        await message.answer(f"⚠️ Код {args} не найден.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    codes_count = await db.count_codes()
    channels_count = await db.count_channels()
    users_count = await db.count_users()
    stats = await db.search_stats()
    top = await db.top_codes(5)

    if top:
        top_lines = "\n".join(
            f"  {i + 1}. {c['code']} — «{c['movie_name']}» ({c['hits']} поисков)"
            for i, c in enumerate(top)
        )
    else:
        top_lines = "  пока нет данных"

    text = (
        "📊 Статистика бота\n\n"
        f"🎞 Кодов в базе: {codes_count}\n"
        f"📢 Каналов для подписки: {channels_count}\n"
        f"👥 Пользователей: {users_count}\n"
        f"🔍 Поисков всего: {stats['total']} "
        f"(найдено: {stats['found']}, не найдено: {stats['not_found']})\n\n"
        f"🏆 Топ кодов:\n{top_lines}"
    )
    await message.answer(text)


@router.message(Command("addch"))
async def cmd_addch(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").strip().split()
    if not args:
        await message.answer(
            "Использование:\n"
            "/addch @username — для публичного канала\n"
            "/addch -1001234567890 https://t.me/+invite — для приватного канала "
            "(бот должен быть админом канала)"
        )
        return

    chat_ref = args[0]
    manual_url = args[1] if len(args) > 1 else None

    try:
        chat = await bot.get_chat(chat_ref)
    except TelegramBadRequest:
        await message.answer(
            "⚠️ Не удалось найти канал. Убедитесь, что бот добавлен в канал как администратор."
        )
        return

    url = manual_url or (f"https://t.me/{chat.username}" if chat.username else None)
    if not url:
        await message.answer(
            "⚠️ Канал приватный — укажите ссылку-приглашение вторым аргументом:\n"
            "/addch -1001234567890 https://t.me/+invite"
        )
        return

    title = chat.title or chat_ref
    await db.add_channel(str(chat.id), title, url)
    await message.answer(f"✅ Канал «{title}» добавлен.")


@router.message(Command("delch"))
async def cmd_delch(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").strip()
    if not args:
        await message.answer("Использование: /delch <@username или chat_id>")
        return

    chat_id = args
    try:
        chat = await bot.get_chat(args)
        chat_id = str(chat.id)
    except TelegramBadRequest:
        pass  # Используем то, что ввёл админ, как есть (например, уже сохранённый chat_id)

    deleted = await db.delete_channel(chat_id)
    if deleted:
        await message.answer("🗑 Канал удалён.")
    else:
        await message.answer("⚠️ Канал с таким ID не найден в списке.")


@router.message(Command("ch"))
async def cmd_ch(message: Message) -> None:
    channels = await db.list_channels()
    if not channels:
        await message.answer("Каналов пока нет.")
        return

    lines = [f"• {ch['title']} — {ch['chat_id']}\n  {ch['url']}" for ch in channels]
    await message.answer("📢 Каналы для подписки:\n\n" + "\n\n".join(lines))
