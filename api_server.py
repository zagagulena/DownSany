"""
HTTP-API для приложения «Видеообои» (Android).

Приложение отправляет ссылку на TikTok / Instagram, бот скачивает видео
тем же кодом, что и в Telegram, и отдаёт сам файл.

    POST /api/download
    Authorization: Bearer <API_TOKEN>
    {"url": "https://www.tiktok.com/..."}

    200 -> видеофайл (video/mp4)
    4xx/5xx -> {"error": "текст для пользователя"}

    GET /health -> "ok"

Сервер запускается вместе с ботом, только если задан API_TOKEN.
Порт берётся из PORT (Railway выставляет его сам).
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import shutil

from aiohttp import web

import config
from downloader import detect_platform, download_video, is_tiktok_photo_post

log = logging.getLogger("api")

# одновременно скачиваем не больше двух видео, чтобы не перегружать сервер
_semaphore = asyncio.Semaphore(2)


def _error(status: int, text: str) -> web.Response:
    return web.json_response({"error": text}, status=status)


def _authorized(request: web.Request) -> bool:
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    return bool(config.API_TOKEN) and hmac.compare_digest(token, config.API_TOKEN)


async def handle_download(request: web.Request) -> web.StreamResponse:
    if not _authorized(request):
        return _error(401, "Нет доступа: неверный ключ API")

    try:
        data = await request.json()
    except Exception:
        return _error(400, "Неверный запрос")
    url = str(data.get("url", "")).strip()

    platform = detect_platform(url)
    if platform is None:
        return _error(400, "Нужна ссылка на TikTok или Instagram")
    if platform == "tiktok" and is_tiktok_photo_post(url):
        return _error(422, "Это фото-пост — видео в нём нет")

    async with _semaphore:
        try:
            result = await download_video(url)
        except Exception as e:
            log.exception("api download error")
            return _error(502, f"Не получилось скачать: {e}")

    path = result.path
    job_dir = os.path.dirname(path)
    try:
        size = os.path.getsize(path)
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "video/mp4",
                "Content-Disposition": 'attachment; filename="video.mp4"',
            },
        )
        resp.content_length = size
        await resp.prepare(request)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                await resp.write(chunk)
        await resp.write_eof()
        return resp
    finally:
        # файл больше не нужен — чистим за собой
        shutil.rmtree(job_dir, ignore_errors=True)


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_api_server() -> web.AppRunner | None:
    if not config.API_TOKEN:
        log.info("API_TOKEN не задан — HTTP-API для приложения выключен")
        return None

    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_post("/api/download", handle_download)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.API_PORT)
    await site.start()
    log.info("HTTP-API запущен на порту %s", config.API_PORT)
    return runner
