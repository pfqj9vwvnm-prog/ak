import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID администраторов (разработчиков) бота — через запятую в переменной ADMIN_IDS
# Пример: ADMIN_IDS=123456789,987654321
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()}

# Путь к файлу базы данных SQLite. На Railway для сохранности данных
# между деплоями указывайте путь внутри подключённого Volume, например /data/bot.db
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Сообщение, когда в базе ещё нет ни одного добавленного кода
NO_ADS_MESSAGE = (
    "Assalomu aleykum, hozircha reklama beruvchilar yoq, "
    "agarda sizda kanal yoki botni reklama qilish kerak bolsa, admin @lixuauto"
)
