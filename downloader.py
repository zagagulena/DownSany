"""
Скачивание видео через yt-dlp.

TikTok и Instagram: yt-dlp берёт видео напрямую из API платформы,
поэтому результат уже без вотермарки и в максимальном доступном качестве —
никаких доп. настроек выбирать не нужно.

Фото-посты (слайд-шоу) TikTok yt-dlp скачивать не умеет вообще — у них
нет единого видеофайла. Для них используется отдельный путь через
Playwright с сохранённой сессией залогиненного аккаунта (см. tiktok_login.py
и config.TIKTOK_STATE_FILE) — анонимным запросам TikTok данные картинок
не отдаёт ни при каких условиях.
"""

from __future__ import annotations

import json
import os
import re
import uuid
import asyncio
from dataclasses import dataclass, field

import yt_dlp

from config import DOWNLOADS_DIR, COOKIES_FILE, TIKTOK_STATE_FILE

TIKTOK_RE = re.compile(r"(tiktok\.com)", re.I)
INSTAGRAM_RE = re.compile(r"(instagram\.com)", re.I)
TIKTOK_PHOTO_RE = re.compile(r"tiktok\.com/@[^/]+/photo/", re.I)

# Паттерны встроенного JSON с данными страницы, которые TikTok кладёт
# в разные script-теги в зависимости от версии фронтенда.
_EMBEDDED_JSON_PATTERNS = [
    re.compile(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        re.S,
    ),
    re.compile(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', re.S),
    re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S),
]


def detect_platform(url: str) -> str | None:
    if TIKTOK_RE.search(url):
        return "tiktok"
    if INSTAGRAM_RE.search(url):
        return "instagram"
    return None


def is_tiktok_photo_post(url: str) -> bool:
    return bool(TIKTOK_PHOTO_RE.search(url))


def _job_dir() -> str:
    d = os.path.join(DOWNLOADS_DIR, uuid.uuid4().hex)
    os.makedirs(d, exist_ok=True)
    return d


def _base_opts(job_dir: str) -> dict:
    return {
        "outtmpl": os.path.join(job_dir, "%(title).80s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        **({"cookiefile": COOKIES_FILE} if COOKIES_FILE else {}),
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        },
    }


@dataclass
class DownloadResult:
    path: str
    title: str


@dataclass
class PhotoPostResult:
    image_paths: list[str] = field(default_factory=list)
    audio_path: str | None = None
    title: str = "tiktok post"
    job_dir: str = ""


def _run_download(opts: dict, url: str) -> DownloadResult:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if "entries" in info:
            info = info["entries"][0]
        path = ydl.prepare_filename(info)
        if "requested_downloads" in info and info["requested_downloads"]:
            path = info["requested_downloads"][0].get("filepath", path)
        return DownloadResult(path=path, title=info.get("title", "video"))


async def download_video(url: str) -> DownloadResult:
    job_dir = _job_dir()
    opts = _base_opts(job_dir)
    return await asyncio.to_thread(_run_download, opts, url)


def _find_first(obj, key_name: str):
    """Рекурсивно ищет первое значение по ключу key_name в произвольно
    вложенном json (dict/list), не завязываясь на точный путь — TikTok
    периодически меняет структуру вокруг нужных данных."""
    if isinstance(obj, dict):
        if key_name in obj:
            return obj[key_name]
        for v in obj.values():
            found = _find_first(v, key_name)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first(item, key_name)
            if found is not None:
                return found
    return None


def _extract_item_data(html: str) -> dict | None:
    for pattern in _EMBEDDED_JSON_PATTERNS:
        m = pattern.search(html)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        item = _find_first(data, "imagePost")
        if item:
            # возвращаем узел, в котором нашёлся imagePost целиком -
            # ищем его родителя (itemInfo/itemStruct), поэтому проще
            # пройти снова и вернуть сам itemStruct/itemInfo
            item_struct = _find_first(data, "itemStruct") or _find_first(data, "itemInfo")
            if item_struct:
                return item_struct
            return {"imagePost": item}
    return None


async def _fetch_rendered_html(url: str) -> str:
    from playwright.async_api import async_playwright

    context_kwargs = {}
    if TIKTOK_STATE_FILE:
        context_kwargs["storage_state"] = TIKTOK_STATE_FILE

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            return html
        finally:
            await browser.close()


def _download_file(url: str, dest_path: str):
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest_path, "wb") as f:
        f.write(resp.read())


def _build_photo_result(item: dict, job_dir: str) -> PhotoPostResult:
    image_post = item.get("imagePost") or _find_first(item, "imagePost")
    if not image_post:
        raise RuntimeError("Нашёл данные страницы, но не нашёл в них картинок (imagePost пуст).")

    images = image_post.get("images") or []
    if not images:
        raise RuntimeError("Нашёл данные страницы, но не нашёл в них картинок (список images пуст).")

    title = item.get("desc") or "tiktok post"
    result = PhotoPostResult(title=title, job_dir=job_dir)

    for i, img in enumerate(images):
        url_list = (
            (img.get("imageURL") or {}).get("urlList")
            or (img.get("imageUrl") or {}).get("urlList")
            or []
        )
        if not url_list:
            continue
        dest = os.path.join(job_dir, f"photo_{i}.jpg")
        _download_file(url_list[0], dest)
        result.image_paths.append(dest)

    if not result.image_paths:
        raise RuntimeError("Нашёл список картинок, но не смог скачать ни одну (ссылки недоступны).")

    music = item.get("music") or {}
    play_url = ((music.get("playUrl") or {}) if isinstance(music.get("playUrl"), dict) else None)
    play_url_str = music.get("playUrl") if isinstance(music.get("playUrl"), str) else None
    if play_url_str:
        audio_dest = os.path.join(job_dir, "audio.mp3")
        try:
            _download_file(play_url_str, audio_dest)
            result.audio_path = audio_dest
        except Exception:
            pass

    return result


_SCRIPT_ID_RE = re.compile(r'<script[^>]+id="([^"]+)"', re.I)


def _dump_debug_info(html: str, job_dir: str) -> str:
    """Сохраняет диагностику, когда не удалось вытащить данные поста —
    чтобы можно было посмотреть, что реально вернул TikTok, не гоняя
    туда-сюда мегабайты сырого html.

    Главный сигнал — какие scope-ключи реально лежат внутри
    __UNIVERSAL_DATA_FOR_REHYDRATION__: если там нет "webapp.video-detail"
    (или аналога с item/image-данными), значит TikTok просто не отдал
    данные поста этому запросу, а не что страница сломана/заблокирована."""
    script_ids = _SCRIPT_ID_RE.findall(html)

    scope_keys = None
    m = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S
    )
    if m:
        try:
            data = json.loads(m.group(1))
            scope = data.get("__DEFAULT_SCOPE__", data)
            if isinstance(scope, dict):
                scope_keys = list(scope.keys())
        except json.JSONDecodeError:
            scope_keys = "<не распарсился как json>"

    debug = {
        "html_length": len(html),
        "script_ids_found": script_ids,
        "universal_data_scope_keys": scope_keys,
        "title_snippet": (
            m2.group(1) if (m2 := re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)) else None
        ),
    }
    debug_path = os.path.join(job_dir, "debug.json")
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug, f, ensure_ascii=False, indent=2)
    html_path = os.path.join(job_dir, "debug.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return debug_path


def _run_photo_post(html: str, job_dir: str) -> PhotoPostResult:
    item = _extract_item_data(html)
    if not item:
        debug_path = _dump_debug_info(html, job_dir)
        raise RuntimeError(
            "Не нашёл данные поста на странице вообще (TikTok отдал пустую/другую структуру). "
            f"Диагностика сохранена тут: {debug_path} (и debug.html рядом) — пришли этот файл."
        )
    return _build_photo_result(item, job_dir)


async def download_tiktok_photo_post(url: str) -> PhotoPostResult:
    if not TIKTOK_STATE_FILE:
        raise RuntimeError(
            "Для скачивания фото-постов TikTok нужен файл сессии tiktok_state.json "
            "(см. tiktok_login.py) — он не найден."
        )
    job_dir = _job_dir()
    html = await _fetch_rendered_html(url)
    return await asyncio.to_thread(_run_photo_post, html, job_dir)
