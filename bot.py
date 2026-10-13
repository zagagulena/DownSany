import asyncio
import html
import logging
import os
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, ChatMemberUpdatedFilter, IS_MEMBER
from aiogram.types import (
    Message,
    FSInputFile,
    ChatMemberUpdated,
    InputMediaPhoto,
    InputMediaAudio,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from downloader import (
    detect_platform,
    download_video,
    is_tiktok_photo_post,
    download_tiktok_photo_post,
)

URL_RE = re.compile(r"https?://\S+")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

router = Router()


def allowed(user_id: int) -> bool:
    return not config.ALLOWED_USERS or user_id in config.ALLOWED_USERS


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Пришли ссылку на видео с <b>TikTok</b> или <b>Instagram</b> "
        "— я его скачаю без вотермарки, в максимальном качестве."
    )


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER))
async def on_added_to_chat(event: ChatMemberUpdated):
    # бота добавили в группу/канал — коротко представимся
    if event.chat.type in ("group", "supergroup"):
        try:
            await event.bot.send_message(
                event.chat.id,
                "Привет! Кидайте сюда ссылки на TikTok или Instagram — "
                "я скачаю видео и пришлю его прямо в этот чат.\n\n"
                "Чтобы я видел ссылки в обычных сообщениях (а не только команды), "
                "у меня должен быть выключен Privacy Mode — это настраивается "
                "у @BotFather: /mybots → выбрать бота → Bot Settings → Group Privacy → Turn off.",
            )
        except Exception:
            pass


@router.message(F.text.regexp(r"https?://\S+"))
async def handle_link(message: Message):
    user_id = message.from_user.id if message.from_user else None
    if user_id is not None and not allowed(user_id):
        await message.reply("Извини, у тебя нет доступа к этому боту.")
        return

    match = URL_RE.search(message.text)
    if not match:
        return
    url = match.group(0)

    platform = detect_platform(url)
    if platform is None:
        # в группе на ссылки с других сайтов молчим, чтобы не спамить чат
        if message.chat.type == "private":
            await message.reply("Не вижу ссылку на TikTok или Instagram в этом сообщении.")
        return

    status = await message.reply("Скачиваю…")

    if platform == "tiktok" and is_tiktok_photo_post(url):
        try:
            result = await download_tiktok_photo_post(url)
            await send_photo_post(message, status, result)
        except Exception as e:
            log.exception("photo post download error")
            await status.edit_text(f"Не получилось скачать: {html.escape(str(e))}")
        return

    try:
        result = await download_video(url)
        await send_result(message, status, result.path, result.title)
    except Exception as e:
        log.exception("download error")
        await status.edit_text(f"Не получилось скачать: {html.escape(str(e))}")


async def send_result(message: Message, status_message: Message, path: str, title: str):
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > config.MAX_FILE_SIZE_MB:
        await status_message.edit_text(
            f"Файл получился {size_mb:.0f} МБ — это больше лимита в "
            f"{config.MAX_FILE_SIZE_MB} МБ, который умеет отправлять бот."
        )
        os.remove(path)
        return

    file = FSInputFile(path)
    await message.reply_video(file, caption=title, supports_streaming=True)

    try:
        await status_message.delete()
    except Exception:
        pass

    # чистим за собой
    try:
        job_dir = os.path.dirname(path)
        for f in os.listdir(job_dir):
            os.remove(os.path.join(job_dir, f))
        os.rmdir(job_dir)
    except Exception:
        pass


async def send_photo_post(message: Message, status_message: Message, result):
    # Telegram-альбом — максимум 10 элементов
    media = [InputMediaPhoto(media=FSInputFile(p)) for p in result.image_paths[:10]]
    if media:
        media[0].caption = result.title
        await message.reply_media_group(media)

    if result.audio_path:
        try:
            await message.reply_audio(FSInputFile(result.audio_path))
        except Exception:
            pass

    try:
        await status_message.delete()
    except Exception:
        pass

    try:
        for f in os.listdir(result.job_dir):
            os.remove(os.path.join(result.job_dir, f))
        os.rmdir(result.job_dir)
    except Exception:
        pass


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit(
            f"BOT_TOKEN не найден. Проверь, что файл .env лежит здесь: "
            f"{config._ENV_PATH}\nи содержит строку вида BOT_TOKEN=твой_токен"
        )

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
