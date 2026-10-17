import os
from dotenv import load_dotenv

# явный путь к .env рядом со скриптом — чтобы токен находился
# независимо от того, из какой папки запущен python
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=_ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

_allowed = os.getenv("ALLOWED_USERS", "").strip()
ALLOWED_USERS = {int(x) for x in _allowed.split(",") if x.strip()} if _allowed else set()

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))

# Путь к файлу с cookies (формат Netscape, cookies.txt), нужен для постов
# Instagram/приватных видео, которые требуют авторизации. Необязателен.
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip() or None

# Путь к файлу сохранённой сессии TikTok (создаётся tiktok_login.py) —
# нужен, чтобы скачивать фото-посты (слайд-шоу) от имени залогиненного
# аккаунта. Необязателен — без него фото-посты скачать не получится.
TIKTOK_STATE_FILE = os.getenv("TIKTOK_STATE_FILE", "tiktok_state.json").strip() or None
if TIKTOK_STATE_FILE and not os.path.isabs(TIKTOK_STATE_FILE):
    TIKTOK_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), TIKTOK_STATE_FILE)
if TIKTOK_STATE_FILE and not os.path.exists(TIKTOK_STATE_FILE):
    TIKTOK_STATE_FILE = None

# HTTP-API для приложения «Видеообои». Пустой API_TOKEN — API выключен.
API_TOKEN = os.getenv("API_TOKEN", "").strip()
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
