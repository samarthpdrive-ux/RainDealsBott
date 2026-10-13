"""Dedicated Telegram bot for generating one-time manager login codes.

Run as its own worker with ADMIN_VERIFY_BOT_TOKEN configured.
"""

import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.filters.command import CommandObject

import config
from database import engine
from models.manager_auth import ManagerAuthSession, ManagerLoginChallenge
from services.manager_auth import approve_login_challenge, create_challenge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("admin_verify_bot")
dp = Dispatcher()


async def health(request: web.Request) -> web.Response:
    return web.Response(text="Admin verification bot is running")


async def start_http_server() -> web.AppRunner:
    """Expose a health endpoint and bind Render's required web-service port."""
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("HTTP health server listening on port %s", port)
    return runner


async def _ensure_schema() -> None:
    await asyncio.to_thread(ManagerLoginChallenge.__table__.create, bind=engine, checkfirst=True)
    await asyncio.to_thread(ManagerAuthSession.__table__.create, bind=engine, checkfirst=True)


@dp.message(CommandStart())
async def start(message: Message, command: CommandObject) -> None:
    if command.args:
        if message.chat.type != "private":
            await message.answer("Open the manager verification link in a private chat with this bot.")
            return
        user = message.from_user
        if not user or user.id not in config.ADMIN_IDS:
            await message.answer("This Telegram account is not an authorized manager admin.")
            return
        approved = await asyncio.to_thread(
            approve_login_challenge, command.args, user.id, config.ADMIN_IDS
        )
        if approved:
            await message.answer("Login verified. Return to the manager website; it will finish signing you in.")
        else:
            await message.answer("This login request has expired or was already used. Start again from the manager website.")
        return
    await message.answer("Use /generate for a fallback one-time code, or start verification from the manager website.")


@dp.message(Command("generate"))
@dp.message(Command("admin_verify"))
async def generate_code(message: Message) -> None:
    if message.chat.type != "private":
        await message.answer("For privacy, open this bot in a private chat and send /generate.")
        return
    if not message.from_user or message.from_user.id not in config.ADMIN_IDS:
        await message.answer("This Telegram account is not an authorized manager admin.")
        return
    code, _expires = await asyncio.to_thread(create_challenge, message.from_user.id)
    await message.answer(
        "Your one-time manager login code (valid for five minutes):\n\n"
        f"<code>{code}</code>\n\n"
        "Enter it on the manager website. It can be used once; generate another code if it expires.",
        parse_mode="HTML",
    )


async def main() -> None:
    # Read the Render worker's secret directly so the worker also works with
    # older deployed config.py versions that do not expose this attribute.
    bot_token = os.getenv("ADMIN_VERIFY_BOT_TOKEN", "").strip()
    if not bot_token:
        bot_token = str(getattr(config, "ADMIN_VERIFY_BOT_TOKEN", "") or "").strip()
    if not bot_token:
        raise RuntimeError("Set ADMIN_VERIFY_BOT_TOKEN for the dedicated manager verification bot.")
    runner = await start_http_server()
    bot = Bot(token=bot_token)
    try:
        await _ensure_schema()
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
