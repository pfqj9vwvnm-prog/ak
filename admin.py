from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

import database as db
from config import ADMIN_IDS

router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in ADMIN_IDS


# Все хендлеры в этом роутере доступны только администраторам (разработчикам).
router.message.filter(IsAdmin())


class AddCodeStates(StatesGroup):
    waiting_code = State()
    waiting_name = State()
    waiting_photo = State()
    waiting_film = State()


@router.message(Command("addcode"))
async def cmd_addcode(message: Message, command: CommandObject, state: FSMContext) -> None:
    args = (command.args or "").strip()
    if args:
        parts = args.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) == 3:
            await state.update_data(code=parts[0], movie_name=parts[1].strip())
            await state.set_state(AddCodeStates.waiting_photo)
            await message.answer("Отправьте фото-обложку для карточки фильма:")
            return
        await message.answer("⚠️ Формат: /addcode 123 Название фильма — запускаю пошаговый ввод.")

    await state.set_state(AddCodeStates.waiting_code)
    await message.answer(
        "Добавление фильма.\nВведите код (3 цифры) (/cancel — отменить):"
    )


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Отменено.")


@router.message(AddCodeStates.waiting_code, F.text, ~F.text.startswith("/"))
async def addcode_get_code(message: Message, state: FSMContext) -> None:
    code = message.text.strip()
    if not (code.isdigit() and len(code) == 3):
        await message.answer("⚠️ Код должен состоять ровно из 3 цифр. Попробуйте снова:")
        return
    await state.update_data(code=code)
    await state.set_state(AddCodeStates.waiting_name)
    await message.answer("Введите название фильма:")


@router.message(AddCodeStates.waiting_name, F.text, ~F.text.startswith("/"))
async def addcode_get_name(message: Message, state: FSMContext) -> None:
    await state.update_data(movie_name=message.text.strip())
    await state.set_state(AddCodeStates.waiting_photo)
    await message.answer("Отправьте фото-обложку для карточки фильма:")


@router.message(AddCodeStates.waiting_photo, F.photo | F.document)
async def addcode_get_photo(message: Message, state: FSMContext) -> None:
    if message.photo:
        photo_file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        photo_file_id = message.document.file_id
    else:
        await message.answer(
            "⚠️ Нужно фото (можно отправить и как файл-изображение). Отправьте обложку:"
        )
        return

    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(AddCodeStates.waiting_film)
    await message.answer(
        "Отправьте видео (сам фильм) — оно будет отправляться по кнопке «🍿 KO'RISH 🎬»:"
    )


@router.message(AddCodeStates.waiting_photo, ~(F.text & F.text.startswith("/")))
async def addcode_get_photo_invalid(message: Message) -> None:
    await message.answer("⚠️ Нужно именно фото. Отправьте фото-обложку для карточки:")


@router.message(AddCodeStates.waiting_film, F.video | F.document)
async def addcode_get_film(message: Message, state: FSMContext) -> None:
    if message.video:
        film_file_id = message.video.file_id
        film_type = "video"
    else:
        film_file_id = message.document.file_id
        film_type = "document"

    data = await state.get_data()
    await state.clear()

    is_new = await db.upsert_code(
        code=data["code"],
        movie_name=data["movie_name"],
        photo_file_id=data["photo_file_id"],
        film_file_id=film_file_id,
        film_type=film_type,
    )
    action = "добавлен" if is_new else "обновлён"
    await message.answer(f"✅ Код {data['code']} {action}: «{data['movie_name']}»")


@router.message(AddCodeStates.waiting_film, ~(F.text & F.text.startswith("/")))
async def addcode_get_film_invalid(message: Message) -> None:
    await message.answer("⚠️ Нужно видео или файл с фильмом. Отправьте его:")


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
