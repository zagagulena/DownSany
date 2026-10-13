"""
Разовый скрипт: открывает настоящее (видимое) окно браузера, ты логинишься
в TikTok вручную (вводишь логин/пароль, проходишь капчу/смс-код — всё как
обычно), а скрипт сохраняет получившуюся сессию (cookies + localStorage) в
файл tiktok_state.json. Дальше бот подхватывает этот файл для headless-браузера
и не логинится заново при каждом скачивании.

Запуск:
    python tiktok_login.py

Пересохранять сессию нужно будет, если TikTok когда-нибудь попросит
перелогиниться (разлогинит старую сессию) — тогда просто запусти этот
скрипт ещё раз.
"""

import asyncio
from playwright.async_api import async_playwright

STATE_PATH = "tiktok_state.json"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.tiktok.com/login")

        print("Залогинься в открывшемся окне браузера (логин/пароль, капча, смс-код — всё как обычно).")
        input("Когда полностью залогинишься и увидишь свою ленту TikTok — нажми Enter здесь: ")

        await context.storage_state(path=STATE_PATH)
        print(f"Готово. Сессия сохранена в {STATE_PATH}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
