from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

from config import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY,
                movie_name TEXT NOT NULL,
                photo_file_id TEXT NOT NULL,
                added_at TEXT NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                chat_id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                added_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                found INTEGER NOT NULL,
                searched_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


# ---------- Коды ----------

async def upsert_code(code: str, movie_name: str, photo_file_id: str) -> bool:
    """Добавляет код или обновляет существующий. Возвращает True, если код новый."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM codes WHERE code = ?", (code,))
        exists = (await cursor.fetchone()) is not None
        if exists:
            await db.execute(
                "UPDATE codes SET movie_name = ?, photo_file_id = ? WHERE code = ?",
                (movie_name, photo_file_id, code),
            )
        else:
            await db.execute(
                "INSERT INTO codes (code, movie_name, photo_file_id, added_at, hits) "
                "VALUES (?, ?, ?, ?, 0)",
                (code, movie_name, photo_file_id, _now()),
            )
        await db.commit()
        return not exists


async def delete_code(code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM codes WHERE code = ?", (code,))
        await db.commit()
        return cursor.rowcount > 0


async def get_code(code: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM codes WHERE code = ?", (code,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def count_codes() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM codes")
        (count,) = await cursor.fetchone()
        return count


async def increment_hits(code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE codes SET hits = hits + 1 WHERE code = ?", (code,))
        await db.commit()


async def top_codes(limit: int = 5) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT code, movie_name, hits FROM codes ORDER BY hits DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ---------- Каналы ----------

async def add_channel(chat_id: str, title: str, url: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO channels (chat_id, title, url, added_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, title, url, _now()),
        )
        await db.commit()


async def delete_channel(chat_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM channels WHERE chat_id = ?", (chat_id,))
        await db.commit()
        return cursor.rowcount > 0


async def list_channels() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM channels ORDER BY added_at")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def count_channels() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM channels")
        (count,) = await cursor.fetchone()
        return count


# ---------- Пользователи и поиск ----------

async def touch_user(user_id: int) -> None:
    now = _now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, first_seen, last_seen) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (user_id, now, now),
        )
        await db.commit()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        (count,) = await cursor.fetchone()
        return count


async def log_search(user_id: int, code: str, found: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO searches (user_id, code, found, searched_at) VALUES (?, ?, ?, ?)",
            (user_id, code, int(found), _now()),
        )
        await db.commit()


async def search_stats() -> Dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*), SUM(found) FROM searches")
        total, found = await cursor.fetchone()
        total = total or 0
        found = found or 0
        return {"total": total, "found": found, "not_found": total - found}
