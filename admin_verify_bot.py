"""Dedicated Telegram bot for generating one-time manager login codes.

Run as its own worker with ADMIN_VERIFY_BOT_TOKEN configured.
"""

import asyncio
import logging
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
    if not config.ADMIN_VERIFY_BOT_TOKEN:
        raise RuntimeError("Set ADMIN_VERIFY_BOT_TOKEN for the dedicated manager verification bot.")
    await _ensure_schema()
    bot = Bot(token=config.ADMIN_VERIFY_BOT_TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
