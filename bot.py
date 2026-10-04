# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════╗
║            🎬  KODLI KINO BOT  🎬            ║
║   Python 3.10+  |  aiogram 3.x  |  SQLite     ║
╚══════════════════════════════════════════════╝

RAILWAY:
    Variables bo‘limiga qo‘shing:
        BOT_TOKEN = @BotFather bergan token
        ADMIN_ID  = sizning Telegram ID raqamingiz
    Service'ga Volume ulang (Mount path: /data) — shunda SQLite baza
    redeploy'dan keyin ham saqlanadi.

REPLIT / LOKAL:
    pip install -U aiogram, so‘ng python bot.py

Bot ichida kichik veb-server ham bor (Railway healthcheck / Replit uchun).
"""

import asyncio
import html
import logging
import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta

from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    ErrorEvent,
    KeyboardButton,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ════════════════════════════════════════════════════════════
# ⚙️  SOZLAMALAR  (token va admin ID shu yerda)
# ════════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "BU_YERGA_BOT_TOKENINI_YOZING")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

ADMIN_IDS = {ADMIN_ID}            # Bir nechta admin kerak bo‘lsa: {111, 222}

# Railway: Volume ulansa, Railway RAILWAY_VOLUME_MOUNT_PATH ni o‘zi beradi (masalan /data).
# Shu papkada baza saqlanadi va redeploy'da O‘CHMAYDI. Volume bo‘lmasa — joriy papka.
DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "kino_bot.db")   # SQLite baza fayli
LOG_FILE = os.path.join(DATA_DIR, "bot.log")      # Log fayli

REFERRAL_BONUS = 50               # Do‘st taklif qilgani uchun beriladigan ball
DAILY_BONUS = {"user": 10, "vip": 25, "premium": 50, "admin": 100}
VIP_PRICE = 300                   # VIP (7 kun) narxi — ball bilan
PREMIUM_PRICE = 800               # PREMIUM (7 kun) narxi — ball bilan
STATUS_DAYS = 7                   # Ballga olinadigan status muddati (kun)
LIST_LIMIT = 10                   # Ro‘yxatlarda ko‘rsatiladigan kinolar soni

# Spam himoya: ikki xabar orasidagi minimal vaqt (soniya)
THROTTLE = {"user": 1.0, "vip": 0.6, "premium": 0.3}
# Kino yuborishdan oldingi kutish (soniya). PREMIUM — kutmaydi (tezkor)
SEND_DELAY = {"user": 2.0, "vip": 1.0, "premium": 0.0, "admin": 0.0}

CATEGORIES = [
    "Jangari", "Komediya", "Drama", "Qo‘rqinchli", "Fantastika",
    "Multfilm", "Melodrama", "Tarixiy", "Boshqa",
]

# ════════════════════════════════════════════════════════════
# 🏷  MATNLAR VA TUGMALAR
# ════════════════════════════════════════════════════════════
BTN_SEARCH = "🔍 Qidiruv"
BTN_CATS = "🗂 Kategoriyalar"
BTN_NEW = "🆕 So‘nggi kinolar"
BTN_TOP = "🔥 Mashhur kinolar"
BTN_PROFILE = "👤 Profilim"
BTN_STATUS = "👑 Status"
BTN_BONUS = "🎁 Kunlik bonus"
BTN_REF = "👥 Referal"
BTN_HELP = "ℹ️ Yordam"
BTN_ADMIN = "🛠 Admin panel"
BTN_SKIP = "⏭ Keyinroq"

BTN_ADD_MOVIE = "➕ Kino qo‘shish"
BTN_DEL_MOVIE = "🗑 Kino o‘chirish"
BTN_MOVIE_LIST = "📋 Kinolar ro‘yxati"
BTN_USERS = "👥 Foydalanuvchilar"
BTN_STATS = "📊 Statistika"
BTN_BROADCAST = "📣 Broadcast"
BTN_GIVE_STATUS = "👑 Status berish"
BTN_GIVE_BONUS = "💰 Bonus berish"
BTN_CHANNELS = "📡 Kanallar"
BTN_AD = "📢 Reklama matni"
BTN_BACK = "🔙 Asosiy menyu"
BTN_CANCEL = "❌ Bekor qilish"

STATUS_LEVEL = {"user": 0, "vip": 1, "premium": 2, "admin": 3}
STATUS_TITLE = {
    "user": "👤 Oddiy foydalanuvchi",
    "vip": "💎 VIP",
    "premium": "👑 PREMIUM",
    "admin": "🛡 Admin",
}
ACCESS_TITLE = {"all": "🌍 Hamma uchun", "vip": "💎 Faqat VIP", "premium": "👑 Faqat PREMIUM"}
ACCESS_ICON = {"all": "🎬", "vip": "💎", "premium": "👑"}

CODE_RE = re.compile(r"^[a-z0-9_-]{1,20}$")
DT_FMT = "%Y-%m-%d %H:%M:%S"
BOT_USERNAME = ""  # main() ichida to‘ldiriladi

# ════════════════════════════════════════════════════════════
# 📝 LOG YOZISH
# ════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("kino_bot")

# ════════════════════════════════════════════════════════════
# 🗄  SQLITE BAZA
# ════════════════════════════════════════════════════════════
db = sqlite3.connect(DB_NAME, check_same_thread=False)
db.row_factory = sqlite3.Row


def db_run(sql, params=()):
    """So‘rovni bajaradi va o‘zgarishlarni saqlaydi."""
    cur = db.execute(sql, params)
    db.commit()
    return cur


def db_one(sql, params=()):
    """Bitta qatorni qaytaradi (yoki None)."""
    return db.execute(sql, params).fetchone()


def db_all(sql, params=()):
    """Barcha qatorlarni qaytaradi."""
    return db.execute(sql, params).fetchall()


def db_val(sql, params=(), default=0):
    """Bitta qiymatni qaytaradi (masalan COUNT)."""
    row = db.execute(sql, params).fetchone()
    return row[0] if row and row[0] is not None else default


def init_db():
    """Jadvallarni yaratadi."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            full_name    TEXT,
            username     TEXT,
            phone        TEXT,
            registered   INTEGER DEFAULT 0,
            status       TEXT DEFAULT 'user',
            status_until TEXT,
            balance      INTEGER DEFAULT 0,
            referrer_id  INTEGER,
            last_bonus   TEXT,
            active       INTEGER DEFAULT 1,
            joined_at    TEXT,
            last_seen    TEXT
        );
        CREATE TABLE IF NOT EXISTS movies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT UNIQUE,
            title       TEXT,
            description TEXT,
            file_id     TEXT,
            file_type   TEXT,
            category    TEXT,
            access      TEXT DEFAULT 'all',
            views       INTEGER DEFAULT 0,
            added_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS channels (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE,
            title   TEXT,
            url     TEXT
        );
        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER,
            code    TEXT,
            score   INTEGER,
            PRIMARY KEY (user_id, code)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    db.commit()


def now_str():
    return datetime.now().strftime(DT_FMT)


def get_setting(key, default=""):
    row = db_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    db_run(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ════════════════════════════════════════════════════════════
# 👤 FOYDALANUVCHI FUNKSIYALARI
# ════════════════════════════════════════════════════════════
def register_user(tg_user, referrer_id=None):
    """
    Foydalanuvchini bazaga qo‘shadi.
    Qaytaradi: (yangimi, to‘g‘ri_referrer_id)
    """
    row = db_one("SELECT user_id FROM users WHERE user_id=?", (tg_user.id,))
    name = tg_user.full_name or "Foydalanuvchi"
    if row:
        db_run(
            "UPDATE users SET full_name=?, username=?, active=1, last_seen=? WHERE user_id=?",
            (name, tg_user.username, now_str(), tg_user.id),
        )
        return False, None

    # Referal tekshiruvi: o‘zini o‘zi taklif qila olmaydi va taklif qiluvchi bazada bo‘lishi kerak
    if referrer_id == tg_user.id or not db_one("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)):
        referrer_id = None

    db_run(
        "INSERT INTO users(user_id, full_name, username, referrer_id, joined_at, last_seen) "
        "VALUES(?,?,?,?,?,?)",
        (tg_user.id, name, tg_user.username, referrer_id, now_str(), now_str()),
    )
    if referrer_id:
        db_run("UPDATE users SET balance = balance + ? WHERE user_id=?", (REFERRAL_BONUS, referrer_id))
    return True, referrer_id


def get_user(user_id):
    return db_one("SELECT * FROM users WHERE user_id=?", (user_id,))


def get_status(user_id):
    """Foydalanuvchi statusini qaytaradi (muddati tugagan bo‘lsa — oddiyga qaytaradi)."""
    if user_id in ADMIN_IDS:
        return "admin"
    row = db_one("SELECT status, status_until FROM users WHERE user_id=?", (user_id,))
    if not row:
        return "user"
    status = row["status"] or "user"
    if status != "user" and row["status_until"]:
        try:
            if datetime.strptime(row["status_until"], DT_FMT) < datetime.now():
                db_run("UPDATE users SET status='user', status_until=NULL WHERE user_id=?", (user_id,))
                return "user"
        except ValueError:
            pass
    return status


def grant_status(user_id, status, days=0, extend=False):
    """
    Status berish / olib tashlash.
    days=0 bo‘lsa — cheksiz. extend=True bo‘lsa — mavjud muddatga qo‘shiladi.
    """
    if status == "user":
        db_run("UPDATE users SET status='user', status_until=NULL WHERE user_id=?", (user_id,))
        return
    if days <= 0:
        db_run("UPDATE users SET status=?, status_until=NULL WHERE user_id=?", (status, user_id))
        return
    base = datetime.now()
    row = get_user(user_id)
    if extend and row and row["status"] == status and row["status_until"]:
        try:
            cur_until = datetime.strptime(row["status_until"], DT_FMT)
            if cur_until > base:
                base = cur_until
        except ValueError:
            pass
    until = (base + timedelta(days=days)).strftime(DT_FMT)
    db_run("UPDATE users SET status=?, status_until=? WHERE user_id=?", (status, until, user_id))


# ════════════════════════════════════════════════════════════
# 🎞  KINO FUNKSIYALARI
# ════════════════════════════════════════════════════════════
def get_movie(code):
    return db_one("SELECT * FROM movies WHERE code=?", (code,))


def get_rating(code):
    """(o‘rtacha reyting, ovozlar soni)"""
    row = db_one("SELECT AVG(score) a, COUNT(*) c FROM ratings WHERE code=?", (code,))
    return (row["a"] or 0.0), row["c"]


def search_movies(text):
    """Nomi bo‘yicha qidiradi (katta-kichik harf farqsiz)."""
    text = text.lower().strip()
    rows = db_all("SELECT code, title, access FROM movies ORDER BY id DESC")
    return [r for r in rows if text in r["title"].lower()][:20]


def movie_caption(m):
    """Kino ostidagi chiroyli matn: nomi, tavsifi, reyting va h.k."""
    avg, cnt = get_rating(m["code"])
    desc = html.escape((m["description"] or "")[:500])
    badge = {"all": "", "vip": "💎 <b>VIP kino</b>\n", "premium": "👑 <b>PREMIUM kino</b>\n"}[m["access"]]
    return (
        f"{badge}🎬 <b>{html.escape(m['title'])}</b>\n\n"
        f"📝 {desc}\n\n"
        f"🗂 Kategoriya: <b>{html.escape(m['category'] or 'Boshqa')}</b>\n"
        f"🔑 Kod: <code>{m['code']}</code>\n"
        f"⭐ Reyting: <b>{avg:.1f}</b> ({cnt} ta ovoz)\n"
        f"👁 Ko‘rishlar: <b>{m['views']}</b>\n\n"
        f"🍿 Yoqimli tomosha!"
    )


# ════════════════════════════════════════════════════════════
# ⌨️  KLAVIATURALAR
# ════════════════════════════════════════════════════════════
def main_menu(user_id):
    """Asosiy Reply keyboard."""
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_CATS))
    kb.row(KeyboardButton(text=BTN_NEW), KeyboardButton(text=BTN_TOP))
    kb.row(KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_STATUS))
    kb.row(KeyboardButton(text=BTN_BONUS), KeyboardButton(text=BTN_REF))
    kb.row(KeyboardButton(text=BTN_HELP))
    if user_id in ADMIN_IDS:
        kb.row(KeyboardButton(text=BTN_ADMIN))
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="🔑 Kino kodini yozing...")


def quick_menu():
    """Inline tezkor menyu."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Qidiruv", callback_data="menu:search")
    kb.button(text="🗂 Kategoriyalar", callback_data="menu:cats")
    kb.button(text="🆕 Yangi kinolar", callback_data="menu:new")
    kb.button(text="🔥 Mashhur", callback_data="menu:top")
    kb.button(text="🎁 Kunlik bonus", callback_data="menu:bonus")
    kb.button(text="👑 Status", callback_data="menu:status")
    kb.adjust(2)
    return kb.as_markup()


def admin_menu():
    """Admin panel tugmalari."""
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=BTN_ADD_MOVIE), KeyboardButton(text=BTN_DEL_MOVIE))
    kb.row(KeyboardButton(text=BTN_MOVIE_LIST), KeyboardButton(text=BTN_USERS))
    kb.row(KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_BROADCAST))
    kb.row(KeyboardButton(text=BTN_GIVE_STATUS), KeyboardButton(text=BTN_GIVE_BONUS))
    kb.row(KeyboardButton(text=BTN_CHANNELS), KeyboardButton(text=BTN_AD))
    kb.row(KeyboardButton(text=BTN_BACK))
    return kb.as_markup(resize_keyboard=True)


def cancel_menu():
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=BTN_CANCEL))
    return kb.as_markup(resize_keyboard=True)


def contact_menu():
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📱 Raqamni yuborish", request_contact=True))
    kb.row(KeyboardButton(text=BTN_SKIP))
    return kb.as_markup(resize_keyboard=True)


def movies_kb(rows):
    """Kinolar ro‘yxati uchun inline tugmalar."""
    kb = InlineKeyboardBuilder()
    for r in rows:
        title = r["title"] if len(r["title"]) <= 32 else r["title"][:29] + "..."
        kb.button(text=f"{ACCESS_ICON[r['access']]} {title} • {r['code']}", callback_data=f"movie:{r['code']}")
    kb.adjust(1)
    return kb.as_markup()


def rating_kb(code):
    kb = InlineKeyboardBuilder()
    for n in range(1, 6):
        kb.button(text=f"{n}⭐", callback_data=f"rate:{code}:{n}")
    kb.adjust(5)
    return kb.as_markup()


def sub_kb(channels):
    """Majburiy obuna tugmalari + ✅ Tekshirish."""
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.button(text=f"📢 {ch['title']}", url=ch["url"])
    kb.button(text="✅ Tekshirish", callback_data="check_sub")
    kb.adjust(1)
    return kb.as_markup()


# ════════════════════════════════════════════════════════════
# 🔒 MAJBURIY OBUNA
# ════════════════════════════════════════════════════════════
def get_channels():
    return db_all("SELECT * FROM channels ORDER BY id")


async def get_unsubscribed(bot: Bot, user_id):
    """Foydalanuvchi obuna bo‘lmagan kanallar ro‘yxati."""
    if user_id in ADMIN_IDS:
        return []
    missing = []
    for ch in get_channels():
        chat_id = ch["chat_id"]
        try:
            chat_id = int(chat_id)
        except ValueError:
            pass
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
            elif member.status == "restricted" and not getattr(member, "is_member", True):
                missing.append(ch)
        except Exception as e:
            # Bot kanalda admin bo‘lmasa yoki kanal topilmasa — foydalanuvchini to‘smaymiz
            log.warning("Obuna tekshirib bo‘lmadi (%s): %s", ch["chat_id"], e)
    return missing


SUB_TEXT = (
    "🔒 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling!</b>\n\n"
    "Obuna bo‘lgach, <b>✅ Tekshirish</b> tugmasini bosing 👇"
)

# ════════════════════════════════════════════════════════════
# 🧩 HOLATLAR (FSM)
# ════════════════════════════════════════════════════════════
class Reg(StatesGroup):
    phone = State()


class AddMovie(StatesGroup):
    code = State()
    title = State()
    description = State()
    category = State()
    access = State()
    file = State()


class DelMovie(StatesGroup):
    code = State()


class Broadcast(StatesGroup):
    content = State()


class GiveStatus(StatesGroup):
    user_id = State()
    status = State()
    days = State()


class GiveBonus(StatesGroup):
    user_id = State()
    amount = State()


class AddChannel(StatesGroup):
    chat = State()
    link = State()


class SetAd(StatesGroup):
    text = State()


# ════════════════════════════════════════════════════════════
# 🛡  MIDDLEWARE'LAR
# ════════════════════════════════════════════════════════════
class UserMiddleware(BaseMiddleware):
    """Har bir foydalanuvchini bazada borligini ta‘minlaydi (/start dan tashqari)."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        is_start = isinstance(event, Message) and (event.text or "").startswith("/start")
        if user and not is_start:
            try:
                register_user(user)
            except Exception as e:
                log.error("Foydalanuvchini saqlashda xato: %s", e)
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """Spam himoya: juda tez yozgan foydalanuvchi xabari e‘tiborsiz qoldiriladi."""

    def __init__(self):
        self.last = {}
        self.warned = {}

    async def __call__(self, handler, event, data):
        user = event.from_user
        if user is None or user.id in ADMIN_IDS:
            return await handler(event, data)
        limit = THROTTLE.get(get_status(user.id), 1.0)
        now = time.monotonic()
        if now - self.last.get(user.id, 0) < limit:
            if now - self.warned.get(user.id, 0) > 3:
                self.warned[user.id] = now
                try:
                    await event.answer("⏳ Iltimos, sekinroq! Spam uchun cheklov bor.")
                except Exception:
                    pass
            return None
        self.last[user.id] = now
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """Obuna bo‘lmaganlarni to‘xtatib, kanallarga obuna bo‘lishni so‘raydi."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id in ADMIN_IDS:
            return await handler(event, data)
        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)  # /start o‘zi tekshiradi
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)
        if not get_channels():
            return await handler(event, data)

        missing = await get_unsubscribed(data["bot"], user.id)
        if not missing:
            return await handler(event, data)

        bot: Bot = data["bot"]
        await bot.send_message(user.id, SUB_TEXT, reply_markup=sub_kb(missing))
        if isinstance(event, CallbackQuery):
            await event.answer()
        return None


# ════════════════════════════════════════════════════════════
# 🎬 KINO YUBORISH
# ════════════════════════════════════════════════════════════
NOT_FOUND_TEXT = (
    "❌ <b>Kino topilmadi!</b>\n\n"
    "Kod noto‘g‘ri yoki bunday kino bazada yo‘q.\n"
    "Kodni tekshirib qayta yuboring yoki 🔍 Qidiruv orqali nom bilan izlang."
)


async def send_movie(bot: Bot, chat_id: int, user_id: int, code: str) -> bool:
    """Kodga biriktirilgan kinoni yuboradi. Muvaffaqiyatli bo‘lsa True qaytaradi."""
    movie = get_movie(code)
    if not movie:
        await bot.send_message(chat_id, NOT_FOUND_TEXT)
        return False

    status = get_status(user_id)
    level = STATUS_LEVEL[status]

    # VIP / PREMIUM uchun maxsus kinolar
    need = movie["access"]
    if need != "all" and level < STATUS_LEVEL[need]:
        kb = InlineKeyboardBuilder()
        kb.button(text="👑 Status olish", callback_data="menu:status")
        await bot.send_message(
            chat_id,
            f"🔐 <b>Bu kino yopiq!</b>\n\nUni faqat {ACCESS_TITLE[need]} foydalanuvchilar ko‘ra oladi.\n"
            f"Statusingiz: {STATUS_TITLE[status]}",
            reply_markup=kb.as_markup(),
        )
        return False

    # PREMIUM — tezkor, qolganlar qisqa kutadi
    wait_msg = None
    delay = SEND_DELAY.get(status, 2.0)
    if delay > 0:
        wait_msg = await bot.send_message(chat_id, "⏳ Kino tayyorlanmoqda...")
        await asyncio.sleep(delay)

    ok = True
    try:
        caption = movie_caption(movie)
        if movie["file_type"] == "video":
            await bot.send_video(chat_id, movie["file_id"], caption=caption, reply_markup=rating_kb(code))
        else:
            await bot.send_document(chat_id, movie["file_id"], caption=caption, reply_markup=rating_kb(code))
    except Exception as e:
        ok = False
        log.error("Kino yuborishda xato (%s): %s", code, e)
        await bot.send_message(chat_id, "⚠️ Kinoni yuborishda xatolik yuz berdi. Keyinroq urinib ko‘ring.")
    finally:
        if wait_msg:
            try:
                await wait_msg.delete()
            except Exception:
                pass

    if ok:
        db_run("UPDATE movies SET views = views + 1 WHERE code=?", (code,))
        # Reklama faqat oddiy foydalanuvchilarga (VIP va undan yuqori — reklamasiz)
        if level == 0:
            ad = get_setting("ad_text")
            if ad:
                await bot.send_message(chat_id, f"📢 <b>Reklama</b>\n\n{ad}")
    return ok


async def process_query(bot: Bot, message: Message):
    """Matn kod bo‘lsa — kinoni, aks holda nom bo‘yicha qidiruv natijasini yuboradi."""
    text = (message.text or "").strip()
    code = text.lower()
    if CODE_RE.match(code) and get_movie(code):
        await send_movie(bot, message.chat.id, message.from_user.id, code)
        return
    results = search_movies(text)
    if results:
        await message.answer(
            f"🔎 <b>Qidiruv natijasi:</b> {len(results)} ta kino topildi 👇",
            reply_markup=movies_kb(results),
        )
    else:
        await message.answer(NOT_FOUND_TEXT)


# ════════════════════════════════════════════════════════════
# 📃 RO‘YXATLAR VA PROFIL FUNKSIYALARI
# ════════════════════════════════════════════════════════════
async def show_new(bot: Bot, chat_id: int):
    """So‘nggi qo‘shilgan kinolar."""
    rows = db_all("SELECT code, title, access FROM movies ORDER BY id DESC LIMIT ?", (LIST_LIMIT,))
    if not rows:
        await bot.send_message(chat_id, "📭 Hozircha kinolar qo‘shilmagan.")
        return
    await bot.send_message(chat_id, "🆕 <b>So‘nggi qo‘shilgan kinolar:</b>", reply_markup=movies_kb(rows))


async def show_top(bot: Bot, chat_id: int):
    """Eng mashhur kinolar (ko‘rishlar soni bo‘yicha)."""
    rows = db_all("SELECT code, title, access FROM movies ORDER BY views DESC, id DESC LIMIT ?", (LIST_LIMIT,))
    if not rows:
        await bot.send_message(chat_id, "📭 Hozircha kinolar qo‘shilmagan.")
        return
    await bot.send_message(chat_id, "🔥 <b>Eng mashhur kinolar:</b>", reply_markup=movies_kb(rows))


async def show_categories(bot: Bot, chat_id: int):
    """Kategoriyalar ro‘yxati (kinolar soni bilan)."""
    counts = {r["category"]: r["c"] for r in db_all("SELECT category, COUNT(*) c FROM movies GROUP BY category")}
    kb = InlineKeyboardBuilder()
    for idx, name in enumerate(CATEGORIES):
        if counts.get(name):
            kb.button(text=f"🎭 {name} ({counts[name]})", callback_data=f"cat:{idx}")
    kb.adjust(2)
    if not counts:
        await bot.send_message(chat_id, "📭 Hozircha kinolar qo‘shilmagan.")
        return
    await bot.send_message(chat_id, "🗂 <b>Kategoriyani tanlang:</b>", reply_markup=kb.as_markup())


async def show_profile(bot: Bot, chat_id: int, user_id: int):
    row = get_user(user_id)
    if not row:
        return
    status = get_status(user_id)
    until = "cheksiz ♾"
    if status in ("vip", "premium") and row["status_until"]:
        until = row["status_until"]
    refs = db_val("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
    phone = row["phone"] or "kiritilmagan"
    await bot.send_message(
        chat_id,
        "👤 <b>PROFILINGIZ</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📛 Ism: <b>{html.escape(row['full_name'] or '')}</b>\n"
        f"📱 Telefon: <b>{html.escape(phone)}</b>\n"
        f"👑 Status: <b>{STATUS_TITLE[status]}</b>\n"
        f"⏳ Muddati: <b>{until}</b>\n"
        f"💰 Ball: <b>{row['balance']}</b>\n"
        f"👥 Takliflar: <b>{refs}</b> ta\n"
        f"📅 Qo‘shilgan sana: <b>{(row['joined_at'] or '')[:10]}</b>",
    )


async def show_status(bot: Bot, chat_id: int, user_id: int):
    row = get_user(user_id)
    status = get_status(user_id)
    balance = row["balance"] if row else 0
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💎 VIP — {VIP_PRICE} ball", callback_data="buy:vip")
    kb.button(text=f"👑 PREMIUM — {PREMIUM_PRICE} ball", callback_data="buy:premium")
    kb.adjust(1)
    await bot.send_message(
        chat_id,
        f"👑 <b>STATUS TIZIMI</b>\n\n"
        f"Sizning statusingiz: <b>{STATUS_TITLE[status]}</b>\n"
        f"💰 Ballaringiz: <b>{balance}</b>\n\n"
        "👤 <b>Oddiy</b> — kod orqali kino olish\n"
        "💎 <b>VIP</b> — reklamasiz + VIP kinolar\n"
        "👑 <b>PREMIUM</b> — reklamasiz + ⚡️ tezkor kino + PREMIUM kinolar\n\n"
        f"🎁 Ball to‘plab, {STATUS_DAYS} kunlik status olishingiz mumkin "
        "(kunlik bonus va do‘st taklif qilish orqali).",
        reply_markup=kb.as_markup(),
    )


async def do_daily_bonus(bot: Bot, chat_id: int, user_id: int):
    row = get_user(user_id)
    today = date.today().isoformat()
    if row["last_bonus"] == today:
        await bot.send_message(chat_id, "⏳ Siz bugungi bonusni olib bo‘lgansiz.\nErtaga qaytib keling! 🌙")
        return
    status = get_status(user_id)
    amount = DAILY_BONUS.get(status, 10)
    db_run(
        "UPDATE users SET balance = balance + ?, last_bonus=? WHERE user_id=?",
        (amount, today, user_id),
    )
    total = db_val("SELECT balance FROM users WHERE user_id=?", (user_id,))
    await bot.send_message(
        chat_id,
        f"🎁 <b>Kunlik bonus!</b>\n\n+{amount} ball qo‘shildi ✅\n💰 Jami ballaringiz: <b>{total}</b>",
    )


async def show_referral(bot: Bot, chat_id: int, user_id: int):
    refs = db_val("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    await bot.send_message(
        chat_id,
        "👥 <b>REFERAL TIZIMI</b>\n\n"
        f"Do‘stlaringizni taklif qiling va har biri uchun <b>+{REFERRAL_BONUS} ball</b> oling! 💰\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
        f"👥 Taklif qilganlaringiz: <b>{refs}</b> ta",
    )


HELP_TEXT = (
    "ℹ️ <b>YORDAM</b>\n\n"
    "🔑 Kino kodini yuboring (masalan: <code>101</code>) — bot kinoni topib beradi.\n"
    "🔍 Nomi bo‘yicha qidirish uchun kino nomining bir qismini yozing.\n\n"
    "📌 <b>Buyruqlar:</b>\n"
    "/start — botni ishga tushirish\n"
    "/profile — profilingiz\n"
    "/bonus — kunlik bonus\n"
    "/help — yordam\n\n"
    "⭐ Kinoni ko‘rgach, uni baholashni unutmang!"
)

SEARCH_TEXT = (
    "🔍 <b>Qidiruv</b>\n\n"
    "Kino <b>kodini</b> yoki <b>nomini</b> yozib yuboring.\n"
    "Masalan: <code>101</code> yoki <i>Temir odam</i>"
)


async def send_welcome(bot: Bot, chat_id: int, tg_user):
    """Xush kelibsiz xabari + asosiy menyu."""
    status = get_status(tg_user.id)
    row = get_user(tg_user.id)
    await bot.send_message(
        chat_id,
        f"🎬 <b>KODLI KINO BOT</b>ga xush kelibsiz, <b>{html.escape(tg_user.full_name)}</b>! 🍿\n\n"
        "🔑 Kino kodini yuboring — men uni darhol topib beraman.\n"
        "Masalan: <code>101</code>\n\n"
        f"👑 Statusingiz: <b>{STATUS_TITLE[status]}</b>\n"
        f"💰 Ballaringiz: <b>{row['balance'] if row else 0}</b>",
        reply_markup=main_menu(tg_user.id),
    )
    await bot.send_message(chat_id, "⚡️ <b>Tezkor menyu</b> 👇", reply_markup=quick_menu())


async def after_subscription(bot: Bot, chat_id: int, tg_user, state: FSMContext):
    """Obuna tasdiqlangach: ro‘yxatdan o‘tmagan bo‘lsa — telefon so‘raydi, aks holda salomlashadi."""
    row = get_user(tg_user.id)
    if row and not row["registered"] and tg_user.id not in ADMIN_IDS:
        await state.set_state(Reg.phone)
        await bot.send_message(
            chat_id,
            "📝 <b>Ro‘yxatdan o‘tish</b>\n\n"
            "Telefon raqamingizni yuboring (ixtiyoriy). Bu bot xavfsizligi va yangiliklar uchun kerak 👇",
            reply_markup=contact_menu(),
        )
    else:
        await send_welcome(bot, chat_id, tg_user)


# ════════════════════════════════════════════════════════════
# 👥 FOYDALANUVCHI HANDLERLARI
# ════════════════════════════════════════════════════════════
user_router = Router()


@user_router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, bot: Bot):
    """/start — ro‘yxatga olish, referal, majburiy obuna tekshiruvi."""
    await state.clear()
    ref = None
    if command.args and command.args.startswith("ref_"):
        try:
            ref = int(command.args[4:])
        except ValueError:
            ref = None

    is_new, valid_ref = register_user(message.from_user, ref)
    if is_new and valid_ref:
        try:
            await bot.send_message(
                valid_ref,
                f"🎉 <b>{html.escape(message.from_user.full_name)}</b> sizning havolangiz orqali qo‘shildi!\n"
                f"💰 +{REFERRAL_BONUS} ball hisobingizga qo‘shildi.",
            )
        except Exception:
            pass

    missing = await get_unsubscribed(bot, message.from_user.id)
    if missing:
        await message.answer(SUB_TEXT, reply_markup=sub_kb(missing))
        return
    await after_subscription(bot, message.chat.id, message.from_user, state)


@user_router.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery, bot: Bot, state: FSMContext):
    """✅ Tekshirish tugmasi."""
    missing = await get_unsubscribed(bot, call.from_user.id)
    if missing:
        await call.answer("❌ Siz hali barcha kanallarga obuna bo‘lmadingiz!", show_alert=True)
        return
    await call.answer("✅ Rahmat! Obuna tasdiqlandi.")
    try:
        await call.message.delete()
    except Exception:
        pass
    register_user(call.from_user)
    await after_subscription(bot, call.from_user.id, call.from_user, state)


# ---------- Ro‘yxatdan o‘tish ----------
@user_router.message(Reg.phone, F.contact)
async def reg_contact(message: Message, state: FSMContext, bot: Bot):
    if message.contact.user_id != message.from_user.id:
        await message.answer("⚠️ Iltimos, faqat o‘zingizning raqamingizni yuboring.")
        return
    db_run(
        "UPDATE users SET phone=?, registered=1 WHERE user_id=?",
        (message.contact.phone_number, message.from_user.id),
    )
    await state.clear()
    await message.answer("✅ <b>Ro‘yxatdan muvaffaqiyatli o‘tdingiz!</b>", reply_markup=ReplyKeyboardRemove())
    await send_welcome(bot, message.chat.id, message.from_user)


@user_router.message(Reg.phone, F.text == BTN_SKIP)
async def reg_skip(message: Message, state: FSMContext, bot: Bot):
    db_run("UPDATE users SET registered=1 WHERE user_id=?", (message.from_user.id,))
    await state.clear()
    await message.answer("✅ Mayli, keyinroq ham kiritishingiz mumkin.", reply_markup=ReplyKeyboardRemove())
    await send_welcome(bot, message.chat.id, message.from_user)


@user_router.message(Reg.phone)
async def reg_other(message: Message):
    await message.answer("📱 Iltimos, tugma orqali raqamingizni yuboring yoki <b>«⏭ Keyinroq»</b> ni bosing.")


# ---------- Buyruqlar ----------
@user_router.message(Command("help"))
@user_router.message(F.text == BTN_HELP)
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@user_router.message(Command("profile"))
@user_router.message(F.text == BTN_PROFILE)
async def cmd_profile(message: Message, bot: Bot):
    await show_profile(bot, message.chat.id, message.from_user.id)


@user_router.message(Command("bonus"))
@user_router.message(F.text == BTN_BONUS)
async def cmd_bonus(message: Message, bot: Bot):
    await do_daily_bonus(bot, message.chat.id, message.from_user.id)


# ---------- Reply tugmalar ----------
@user_router.message(F.text == BTN_SEARCH)
async def btn_search(message: Message):
    await message.answer(SEARCH_TEXT)


@user_router.message(F.text == BTN_CATS)
async def btn_cats(message: Message, bot: Bot):
    await show_categories(bot, message.chat.id)


@user_router.message(F.text == BTN_NEW)
async def btn_new(message: Message, bot: Bot):
    await show_new(bot, message.chat.id)


@user_router.message(F.text == BTN_TOP)
async def btn_top(message: Message, bot: Bot):
    await show_top(bot, message.chat.id)


@user_router.message(F.text == BTN_STATUS)
async def btn_status(message: Message, bot: Bot):
    await show_status(bot, message.chat.id, message.from_user.id)


@user_router.message(F.text == BTN_REF)
async def btn_ref(message: Message, bot: Bot):
    await show_referral(bot, message.chat.id, message.from_user.id)


# ---------- Inline tugmalar ----------
@user_router.callback_query(F.data.startswith("menu:"))
async def cb_menu(call: CallbackQuery, bot: Bot):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    await call.answer()
    if action == "search":
        await bot.send_message(uid, SEARCH_TEXT)
    elif action == "cats":
        await show_categories(bot, uid)
    elif action == "new":
        await show_new(bot, uid)
    elif action == "top":
        await show_top(bot, uid)
    elif action == "bonus":
        await do_daily_bonus(bot, uid, uid)
    elif action == "status":
        await show_status(bot, uid, uid)


@user_router.callback_query(F.data.startswith("movie:"))
async def cb_movie(call: CallbackQuery, bot: Bot):
    code = call.data.split(":", 1)[1]
    await call.answer()
    await send_movie(bot, call.from_user.id, call.from_user.id, code)


@user_router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery, bot: Bot):
    await call.answer()
    try:
        name = CATEGORIES[int(call.data.split(":", 1)[1])]
    except (ValueError, IndexError):
        return
    rows = db_all(
        "SELECT code, title, access FROM movies WHERE category=? ORDER BY views DESC, id DESC LIMIT 20",
        (name,),
    )
    if not rows:
        await bot.send_message(call.from_user.id, "📭 Bu kategoriyada kino yo‘q.")
        return
    await bot.send_message(call.from_user.id, f"🎭 <b>{name}</b> kategoriyasi:", reply_markup=movies_kb(rows))


@user_router.callback_query(F.data.startswith("rate:"))
async def cb_rate(call: CallbackQuery, bot: Bot):
    """Kinoni baholash (1–5)."""
    try:
        _, code, score = call.data.split(":")
        score = int(score)
    except ValueError:
        await call.answer()
        return
    movie = get_movie(code)
    if not movie or not 1 <= score <= 5:
        await call.answer("❌ Xatolik", show_alert=True)
        return
    db_run(
        "INSERT INTO ratings(user_id, code, score) VALUES(?,?,?) "
        "ON CONFLICT(user_id, code) DO UPDATE SET score=excluded.score",
        (call.from_user.id, code, score),
    )
    avg, cnt = get_rating(code)
    await call.answer(f"⭐ Rahmat! Siz {score} baho berdingiz.\nO‘rtacha: {avg:.1f} ({cnt} ovoz)", show_alert=True)
    try:
        await bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=movie_caption(get_movie(code)),
            reply_markup=rating_kb(code),
        )
    except Exception:
        pass


@user_router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot):
    """Ball evaziga VIP / PREMIUM olish."""
    target = call.data.split(":", 1)[1]
    if target not in ("vip", "premium"):
        await call.answer()
        return
    uid = call.from_user.id
    status = get_status(uid)
    if status == "admin":
        await call.answer("🛡 Siz adminsiz — statusga ehtiyoj yo‘q.", show_alert=True)
        return
    if STATUS_LEVEL[status] > STATUS_LEVEL[target]:
        await call.answer("ℹ️ Sizda allaqachon yuqoriroq status bor.", show_alert=True)
        return
    price = VIP_PRICE if target == "vip" else PREMIUM_PRICE
    cur = db_run(
        "UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?",
        (price, uid, price),
    )
    if cur.rowcount == 0:
        have = db_val("SELECT balance FROM users WHERE user_id=?", (uid,))
        await call.answer(f"❌ Ball yetarli emas!\nKerak: {price}, sizda: {have}", show_alert=True)
        return
    grant_status(uid, target, STATUS_DAYS, extend=True)
    await call.answer("✅ Status faollashtirildi!", show_alert=True)
    await bot.send_message(
        uid,
        f"🎉 <b>Tabriklaymiz!</b>\n{STATUS_TITLE[target]} statusi {STATUS_DAYS} kunga faollashtirildi.",
    )


# ---------- Noma‘lum buyruq va matnli so‘rovlar ----------
@user_router.message(StateFilter(None), F.text.startswith("/"))
async def unknown_command(message: Message):
    await message.answer("❓ Noma‘lum buyruq. Yordam uchun /help ni bosing.")


@user_router.message(StateFilter(None), F.text)
async def text_query(message: Message, bot: Bot):
    """Oddiy matn: kino kodi yoki qidiruv so‘rovi."""
    await process_query(bot, message)


# ════════════════════════════════════════════════════════════
# 🛠  ADMIN PANEL
# ════════════════════════════════════════════════════════════
admin_router = Router()
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


@admin_router.message(Command("admin"))
@admin_router.message(F.text == BTN_ADMIN)
async def adm_open(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 <b>ADMIN PANEL</b>\n\nKerakli bo‘limni tanlang 👇", reply_markup=admin_menu())


@admin_router.message(Command("cancel"))
@admin_router.message(F.text == BTN_CANCEL)
async def adm_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=admin_menu())


@admin_router.message(F.text == BTN_BACK)
async def adm_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Asosiy menyu", reply_markup=main_menu(message.from_user.id))


# ---------- ➕ Kino qo‘shish ----------
@admin_router.message(F.text == BTN_ADD_MOVIE)
async def adm_add_movie(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddMovie.code)
    await message.answer(
        "🔑 <b>Kino kodini yuboring</b>\n(lotin harf, raqam, - yoki _ ; masalan: <code>101</code>)",
        reply_markup=cancel_menu(),
    )


@admin_router.message(AddMovie.code, F.text)
async def adm_movie_code(message: Message, state: FSMContext):
    code = message.text.strip().lower()
    if not CODE_RE.match(code):
        await message.answer("⚠️ Kod noto‘g‘ri. Faqat lotin harf, raqam, - va _ (1–20 belgi).")
        return
    if get_movie(code):
        await message.answer("⚠️ Bu kod band! Boshqa kod yuboring.")
        return
    await state.update_data(code=code)
    await state.set_state(AddMovie.title)
    await message.answer("🎬 <b>Kino nomini yuboring:</b>")


@admin_router.message(AddMovie.title, F.text)
async def adm_movie_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:100])
    await state.set_state(AddMovie.description)
    await message.answer("📝 <b>Kino tavsifini yuboring</b> (bo‘sh qoldirish uchun <code>-</code>):")


@admin_router.message(AddMovie.description, F.text)
async def adm_movie_desc(message: Message, state: FSMContext):
    desc = "" if message.text.strip() == "-" else message.text.strip()[:500]
    await state.update_data(description=desc)
    await state.set_state(AddMovie.category)
    kb = InlineKeyboardBuilder()
    for idx, name in enumerate(CATEGORIES):
        kb.button(text=name, callback_data=f"addcat:{idx}")
    kb.adjust(2)
    await message.answer("🗂 <b>Kategoriyani tanlang:</b>", reply_markup=kb.as_markup())


@admin_router.callback_query(AddMovie.category, F.data.startswith("addcat:"))
async def adm_movie_cat(call: CallbackQuery, state: FSMContext):
    try:
        name = CATEGORIES[int(call.data.split(":", 1)[1])]
    except (ValueError, IndexError):
        await call.answer()
        return
    await state.update_data(category=name)
    await state.set_state(AddMovie.access)
    kb = InlineKeyboardBuilder()
    for key, title in ACCESS_TITLE.items():
        kb.button(text=title, callback_data=f"addacc:{key}")
    kb.adjust(1)
    await call.answer()
    await call.message.answer("🔐 <b>Kimlar ko‘ra oladi?</b>", reply_markup=kb.as_markup())


@admin_router.callback_query(AddMovie.access, F.data.startswith("addacc:"))
async def adm_movie_access(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    if key not in ACCESS_TITLE:
        await call.answer()
        return
    await state.update_data(access=key)
    await state.set_state(AddMovie.file)
    await call.answer()
    await call.message.answer("📤 <b>Endi kinoning videosini yoki faylini yuboring:</b>")


@admin_router.message(AddMovie.file, F.video | F.document)
async def adm_movie_file(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.video:
        file_id, ftype = message.video.file_id, "video"
    else:
        file_id, ftype = message.document.file_id, "document"
    try:
        db_run(
            "INSERT INTO movies(code, title, description, file_id, file_type, category, access, added_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (data["code"], data["title"], data["description"], file_id, ftype,
             data["category"], data["access"], now_str()),
        )
    except sqlite3.IntegrityError:
        await state.clear()
        await message.answer("⚠️ Bu kod allaqachon mavjud!", reply_markup=admin_menu())
        return
    await state.clear()
    log.info("Yangi kino qo‘shildi: %s", data["code"])
    await message.answer(
        "✅ <b>Kino muvaffaqiyatli qo‘shildi!</b>\n\n"
        f"🔑 Kod: <code>{data['code']}</code>\n"
        f"🎬 Nomi: <b>{html.escape(data['title'])}</b>\n"
        f"🗂 Kategoriya: {data['category']}\n"
        f"🔐 Kirish: {ACCESS_TITLE[data['access']]}",
        reply_markup=admin_menu(),
    )


@admin_router.message(AddMovie.file)
async def adm_movie_file_wrong(message: Message):
    await message.answer("⚠️ Iltimos, <b>video</b> yoki <b>fayl</b> yuboring.")


# ---------- 🗑 Kino o‘chirish ----------
@admin_router.message(F.text == BTN_DEL_MOVIE)
async def adm_del_movie(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DelMovie.code)
    await message.answer("🗑 <b>O‘chiriladigan kino kodini yuboring:</b>", reply_markup=cancel_menu())


@admin_router.message(DelMovie.code, F.text)
async def adm_del_movie_code(message: Message, state: FSMContext):
    code = message.text.strip().lower()
    movie = get_movie(code)
    if not movie:
        await message.answer("❌ Bunday kodli kino topilmadi. Qayta yuboring yoki bekor qiling.")
        return
    db_run("DELETE FROM movies WHERE code=?", (code,))
    db_run("DELETE FROM ratings WHERE code=?", (code,))
    await state.clear()
    log.info("Kino o‘chirildi: %s", code)
    await message.answer(
        f"✅ <b>{html.escape(movie['title'])}</b> (kod: <code>{code}</code>) o‘chirildi.",
        reply_markup=admin_menu(),
    )


# ---------- 📋 Kinolar ro‘yxati ----------
@admin_router.message(F.text == BTN_MOVIE_LIST)
async def adm_movie_list(message: Message, state: FSMContext):
    await state.clear()
    rows = db_all("SELECT code, title, access, views FROM movies ORDER BY id DESC LIMIT 60")
    if not rows:
        await message.answer("📭 Kinolar yo‘q.")
        return
    lines = [
        f"{ACCESS_ICON[r['access']]} <code>{r['code']}</code> — {html.escape(r['title'])} (👁 {r['views']})"
        for r in rows
    ]
    total = db_val("SELECT COUNT(*) FROM movies")
    await message.answer(f"📋 <b>Kinolar ({total} ta, oxirgi 60 tasi):</b>\n\n" + "\n".join(lines))


# ---------- 👥 Foydalanuvchilar / 📊 Statistika ----------
@admin_router.message(F.text == BTN_USERS)
async def adm_users(message: Message, state: FSMContext):
    await state.clear()
    total = db_val("SELECT COUNT(*) FROM users")
    active = db_val("SELECT COUNT(*) FROM users WHERE active=1")
    today = db_val("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (date.today().isoformat() + "%",))
    await message.answer(
        "👥 <b>FOYDALANUVCHILAR</b>\n\n"
        f"📊 Jami: <b>{total}</b>\n"
        f"✅ Faol: <b>{active}</b>\n"
        f"🆕 Bugun qo‘shilgan: <b>{today}</b>"
    )


@admin_router.message(F.text == BTN_STATS)
async def adm_stats(message: Message, state: FSMContext):
    await state.clear()
    users = db_val("SELECT COUNT(*) FROM users")
    vip = db_val("SELECT COUNT(*) FROM users WHERE status='vip'")
    premium = db_val("SELECT COUNT(*) FROM users WHERE status='premium'")
    movies = db_val("SELECT COUNT(*) FROM movies")
    views = db_val("SELECT SUM(views) FROM movies")
    votes = db_val("SELECT COUNT(*) FROM ratings")
    refs = db_val("SELECT COUNT(*) FROM users WHERE referrer_id IS NOT NULL")
    chans = db_val("SELECT COUNT(*) FROM channels")
    top = db_all("SELECT code, title, views FROM movies ORDER BY views DESC LIMIT 5")
    top_text = "\n".join(
        f"{i}. <code>{r['code']}</code> — {html.escape(r['title'])} ({r['views']} 👁)"
        for i, r in enumerate(top, 1)
    ) or "—"
    await message.answer(
        "📊 <b>STATISTIKA</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"💎 VIP: <b>{vip}</b>  |  👑 PREMIUM: <b>{premium}</b>\n"
        f"🎬 Kinolar: <b>{movies}</b>\n"
        f"👁 Jami ko‘rishlar: <b>{views}</b>\n"
        f"⭐ Baholar: <b>{votes}</b>\n"
        f"🤝 Referallar: <b>{refs}</b>\n"
        f"📡 Majburiy kanallar: <b>{chans}</b>\n\n"
        f"🔥 <b>TOP-5 kinolar:</b>\n{top_text}"
    )


# ---------- 📣 Broadcast ----------
@admin_router.message(F.text == BTN_BROADCAST)
async def adm_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Broadcast.content)
    await message.answer(
        "📣 <b>Hammaga yuboriladigan xabarni yuboring</b>\n(matn, rasm, video — istalgani).",
        reply_markup=cancel_menu(),
    )


@admin_router.message(Broadcast.content)
async def adm_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    users = db_all("SELECT user_id FROM users WHERE active=1")
    progress = await message.answer(f"📣 Yuborish boshlandi... (0/{len(users)})", reply_markup=admin_menu())
    ok = fail = 0
    for i, u in enumerate(users, 1):
        uid = u["user_id"]
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.copy_message(uid, message.chat.id, message.message_id)
                ok += 1
            except Exception:
                fail += 1
        except TelegramForbiddenError:
            db_run("UPDATE users SET active=0 WHERE user_id=?", (uid,))
            fail += 1
        except Exception as e:
            log.warning("Broadcast xato (%s): %s", uid, e)
            fail += 1
        if i % 50 == 0:
            try:
                await progress.edit_text(f"📣 Yuborilmoqda... ({i}/{len(users)})")
            except Exception:
                pass
        await asyncio.sleep(0.05)
    log.info("Broadcast tugadi: ok=%s fail=%s", ok, fail)
    await message.answer(f"✅ <b>Broadcast tugadi!</b>\n\n📬 Yetkazildi: <b>{ok}</b>\n🚫 Yetmadi: <b>{fail}</b>")


# ---------- 👑 Status berish / olish ----------
@admin_router.message(F.text == BTN_GIVE_STATUS)
async def adm_status(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(GiveStatus.user_id)
    await message.answer("🆔 <b>Foydalanuvchi ID raqamini yuboring:</b>", reply_markup=cancel_menu())


@admin_router.message(GiveStatus.user_id, F.text)
async def adm_status_uid(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit() or not get_user(int(raw)):
        await message.answer("❌ Bunday foydalanuvchi bazada topilmadi. ID ni tekshiring.")
        return
    await state.update_data(uid=int(raw))
    await state.set_state(GiveStatus.status)
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 VIP berish", callback_data="gs:vip")
    kb.button(text="👑 PREMIUM berish", callback_data="gs:premium")
    kb.button(text="🚫 Statusni olib tashlash", callback_data="gs:user")
    kb.adjust(1)
    await message.answer("👑 <b>Qaysi statusni berasiz?</b>", reply_markup=kb.as_markup())


@admin_router.callback_query(GiveStatus.status, F.data.startswith("gs:"))
async def adm_status_pick(call: CallbackQuery, state: FSMContext, bot: Bot):
    status = call.data.split(":", 1)[1]
    if status not in ("vip", "premium", "user"):
        await call.answer()
        return
    await call.answer()
    data = await state.get_data()
    if status == "user":
        grant_status(data["uid"], "user")
        await state.clear()
        await call.message.answer("✅ Status olib tashlandi.", reply_markup=admin_menu())
        try:
            await bot.send_message(data["uid"], "ℹ️ Statusingiz oddiy holatga qaytarildi.")
        except Exception:
            pass
        return
    await state.update_data(status=status)
    await state.set_state(GiveStatus.days)
    await call.message.answer("📅 <b>Necha kunga?</b>\n(Cheksiz uchun <code>0</code> yuboring)")


@admin_router.message(GiveStatus.days, F.text)
async def adm_status_days(message: Message, state: FSMContext, bot: Bot):
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring (0 — cheksiz).")
        return
    days = int(raw)
    data = await state.get_data()
    grant_status(data["uid"], data["status"], days)
    await state.clear()
    period = f"{days} kunga" if days else "cheksiz muddatga"
    log.info("Status berildi: %s -> %s (%s)", data["uid"], data["status"], period)
    await message.answer(
        f"✅ {STATUS_TITLE[data['status']]} statusi <code>{data['uid']}</code> ga {period} berildi.",
        reply_markup=admin_menu(),
    )
    try:
        await bot.send_message(
            data["uid"], f"🎉 Sizga {STATUS_TITLE[data['status']]} statusi {period} berildi!"
        )
    except Exception:
        pass


# ---------- 💰 Bonus berish ----------
@admin_router.message(F.text == BTN_GIVE_BONUS)
async def adm_bonus(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(GiveBonus.user_id)
    await message.answer("🆔 <b>Foydalanuvchi ID raqamini yuboring:</b>", reply_markup=cancel_menu())


@admin_router.message(GiveBonus.user_id, F.text)
async def adm_bonus_uid(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw.isdigit() or not get_user(int(raw)):
        await message.answer("❌ Bunday foydalanuvchi bazada topilmadi. ID ni tekshiring.")
        return
    await state.update_data(uid=int(raw))
    await state.set_state(GiveBonus.amount)
    await message.answer("💰 <b>Necha ball berasiz?</b> (ayirish uchun manfiy son, masalan <code>-50</code>)")


@admin_router.message(GiveBonus.amount, F.text)
async def adm_bonus_amount(message: Message, state: FSMContext, bot: Bot):
    raw = message.text.strip()
    try:
        amount = int(raw)
    except ValueError:
        await message.answer("⚠️ Butun son yuboring.")
        return
    data = await state.get_data()
    db_run("UPDATE users SET balance = MAX(balance + ?, 0) WHERE user_id=?", (amount, data["uid"]))
    await state.clear()
    await message.answer(f"✅ <code>{data['uid']}</code> ga {amount:+d} ball qo‘shildi.", reply_markup=admin_menu())
    if amount > 0:
        try:
            await bot.send_message(data["uid"], f"🎁 Admin sizga <b>+{amount} ball</b> sovg‘a qildi!")
        except Exception:
            pass


# ---------- 📡 Kanal sozlash ----------
async def show_channels_admin(bot: Bot, chat_id: int):
    channels = get_channels()
    kb = InlineKeyboardBuilder()
    text = "📡 <b>MAJBURIY OBUNA KANALLARI</b>\n\n"
    if channels:
        for ch in channels:
            text += f"• {html.escape(ch['title'])} — <code>{ch['chat_id']}</code>\n"
            kb.button(text=f"🗑 {ch['title']}", callback_data=f"delch:{ch['id']}")
    else:
        text += "Hozircha kanal qo‘shilmagan.\n"
    kb.button(text="➕ Kanal qo‘shish", callback_data="addch")
    kb.adjust(1)
    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


@admin_router.message(F.text == BTN_CHANNELS)
async def adm_channels(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await show_channels_admin(bot, message.chat.id)


@admin_router.callback_query(F.data == "addch")
async def adm_add_channel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AddChannel.chat)
    await call.message.answer(
        "📡 <b>Kanal @username yoki ID sini yuboring</b>\n"
        "(masalan: <code>@kanal_nomi</code> yoki <code>-1001234567890</code>)\n\n"
        "⚠️ Avval botni kanalga <b>admin</b> qilib qo‘shing!",
        reply_markup=cancel_menu(),
    )


@admin_router.message(AddChannel.chat, F.text)
async def adm_channel_chat(message: Message, state: FSMContext, bot: Bot):
    raw = message.text.strip()
    if raw.lstrip("-").isdigit():
        chat_ref = int(raw)
    else:
        chat_ref = raw if raw.startswith("@") else "@" + raw
    try:
        chat = await bot.get_chat(chat_ref)
    except Exception:
        await message.answer("❌ Kanal topilmadi. Username/ID ni tekshirib, qayta yuboring.")
        return
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
        is_admin = me.status in ("administrator", "creator")
    except Exception:
        is_admin = False
    if not is_admin:
        await message.answer("❌ Bot bu kanalda admin emas. Avval botni admin qiling, so‘ng qayta yuboring.")
        return
    if chat.username:
        db_run(
            "INSERT INTO channels(chat_id, title, url) VALUES(?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, url=excluded.url",
            (str(chat.id), chat.title, f"https://t.me/{chat.username}"),
        )
        await state.clear()
        await message.answer(f"✅ Kanal qo‘shildi: <b>{html.escape(chat.title)}</b>", reply_markup=admin_menu())
        return
    # Yopiq kanal — taklif havolasi kerak
    await state.update_data(chat_id=str(chat.id), title=chat.title)
    await state.set_state(AddChannel.link)
    await message.answer("🔗 Bu yopiq kanal. <b>Taklif havolasini</b> yuboring (https://t.me/+...):")


@admin_router.message(AddChannel.link, F.text)
async def adm_channel_link(message: Message, state: FSMContext):
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer("⚠️ Havola <code>https://t.me/</code> bilan boshlanishi kerak.")
        return
    data = await state.get_data()
    db_run(
        "INSERT INTO channels(chat_id, title, url) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, url=excluded.url",
        (data["chat_id"], data["title"], link),
    )
    await state.clear()
    await message.answer(f"✅ Kanal qo‘shildi: <b>{html.escape(data['title'])}</b>", reply_markup=admin_menu())


@admin_router.callback_query(F.data.startswith("delch:"))
async def adm_del_channel(call: CallbackQuery, bot: Bot):
    try:
        ch_id = int(call.data.split(":", 1)[1])
    except ValueError:
        await call.answer()
        return
    db_run("DELETE FROM channels WHERE id=?", (ch_id,))
    await call.answer("🗑 Kanal o‘chirildi", show_alert=False)
    try:
        await call.message.delete()
    except Exception:
        pass
    await show_channels_admin(bot, call.from_user.id)


# ---------- 📢 Reklama matni ----------
@admin_router.message(F.text == BTN_AD)
async def adm_ad(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SetAd.text)
    current = get_setting("ad_text") or "— (o‘rnatilmagan)"
    await message.answer(
        "📢 <b>Reklama matni</b>\n\n"
        "Bu matn faqat <b>oddiy</b> foydalanuvchilarga kino yuborilgach chiqadi "
        "(VIP va PREMIUM — reklamasiz).\n\n"
        f"Joriy matn:\n{current}\n\n"
        "Yangi matnni yuboring yoki o‘chirish uchun <code>-</code> yuboring:",
        reply_markup=cancel_menu(),
    )


@admin_router.message(SetAd.text, F.text)
async def adm_ad_save(message: Message, state: FSMContext):
    text = message.text.strip()
    set_setting("ad_text", "" if text == "-" else text)
    await state.clear()
    await message.answer("✅ Reklama matni saqlandi." if text != "-" else "✅ Reklama o‘chirildi.", reply_markup=admin_menu())


# ════════════════════════════════════════════════════════════
# 🚨 XATOLIKLARNI USHLASH
# ════════════════════════════════════════════════════════════
async def on_error(event: ErrorEvent):
    log.exception("Kutilmagan xato: %s", event.exception)
    return True


# ════════════════════════════════════════════════════════════
# 🌐 KICHIK VEB-SERVER (Replit uchun)
# ════════════════════════════════════════════════════════════
async def start_web_server():
    async def handle(_request):
        return web.Response(text="🎬 Kodli Kino Bot ishlayapti!")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    log.info("Veb-server ishga tushdi")


# ════════════════════════════════════════════════════════════
# 🚀 ASOSIY FUNKSIYA
# ════════════════════════════════════════════════════════════
async def main():
    global BOT_USERNAME

    if BOT_TOKEN.startswith("BU_YERGA"):
        raise SystemExit("❗ BOT_TOKEN ni kiriting (kodning boshida yoki Replit Secrets'da).")

    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware'lar (tartib muhim)
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    dp.message.outer_middleware(ThrottleMiddleware())
    dp.message.outer_middleware(SubscriptionMiddleware())
    dp.callback_query.outer_middleware(SubscriptionMiddleware())

    dp.errors.register(on_error)
    dp.include_router(admin_router)  # admin handlerlari birinchi
    dp.include_router(user_router)

    me = await bot.get_me()
    BOT_USERNAME = me.username
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="🚀 Botni ishga tushirish"),
            BotCommand(command="profile", description="👤 Profilim"),
            BotCommand(command="bonus", description="🎁 Kunlik bonus"),
            BotCommand(command="help", description="ℹ️ Yordam"),
        ]
    )

    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("🎬 Bot ishga tushdi: @%s", BOT_USERNAME)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to‘xtatildi")
