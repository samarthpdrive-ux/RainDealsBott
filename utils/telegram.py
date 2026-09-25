"""
api/telegram.py

Reusable Telegram API helpers.

This module contains helper functions only.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)


# ============================================================
# SEND MESSAGE
# ============================================================

async def send_message(
    bot: Bot,
    chat_id: int | str,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    disable_web_page_preview: bool = True,
):
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to send Telegram message | chat_id=%s | error=%s",
            chat_id,
            exc,
        )
        return None

    except Exception:
        logger.exception(
            "Unexpected error sending Telegram message | chat_id=%s",
            chat_id,
        )
        return None


# ============================================================
# EDIT MESSAGE
# ============================================================

async def edit_message(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
):
    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to edit Telegram message | "
            "chat_id=%s | message_id=%s | error=%s",
            chat_id,
            message_id,
            exc,
        )
        return None

    except Exception:
        logger.exception(
            "Unexpected error editing Telegram message | "
            "chat_id=%s | message_id=%s",
            chat_id,
            message_id,
        )
        return None


# ============================================================
# DELETE MESSAGE
# ============================================================

async def delete_message(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
) -> bool:
    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
        return True

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to delete Telegram message | "
            "chat_id=%s | message_id=%s | error=%s",
            chat_id,
            message_id,
            exc,
        )
        return False

    except Exception:
        logger.exception(
            "Unexpected error deleting Telegram message | "
            "chat_id=%s | message_id=%s",
            chat_id,
            message_id,
        )
        return False


# ============================================================
# GET BOT INFORMATION
# ============================================================

async def get_bot_info(bot: Bot):
    try:
        return await bot.get_me()

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to get bot information | error=%s",
            exc,
        )
        return None

    except Exception:
        logger.exception(
            "Unexpected error getting bot information"
        )
        return None


# ============================================================
# GET CHAT MEMBER
# ============================================================

async def get_chat_member(
    bot: Bot,
    chat_id: int | str,
    user_id: int,
):
    try:
        return await bot.get_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to get chat member | "
            "chat_id=%s | user_id=%s | error=%s",
            chat_id,
            user_id,
            exc,
        )
        return None

    except Exception:
        logger.exception(
            "Unexpected error getting chat member | "
            "chat_id=%s | user_id=%s",
            chat_id,
            user_id,
        )
        return None


# ============================================================
# CHECK USER MEMBERSHIP
# ============================================================

async def is_chat_member(
    bot: Bot,
    chat_id: int | str,
    user_id: int,
) -> bool:
    member = await get_chat_member(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
    )

    if member is None:
        return False

    return member.status in {
        "creator",
        "administrator",
        "member",
        "restricted",
    }


# ============================================================
# SEND PHOTO
# ============================================================

async def send_photo(
    bot: Bot,
    chat_id: int | str,
    photo: str,
    *,
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
):
    try:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
        )

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to send photo | chat_id=%s | error=%s",
            chat_id,
            exc,
        )
        return None

    except Exception:
        logger.exception(
            "Unexpected error sending photo | chat_id=%s",
            chat_id,
        )
        return None


# ============================================================
# ANSWER CALLBACK QUERY
# ============================================================

async def answer_callback(
    callback_query,
    *,
    text: Optional[str] = None,
    show_alert: bool = False,
) -> bool:
    try:
        await callback_query.answer(
            text=text,
            show_alert=show_alert,
        )
        return True

    except TelegramAPIError as exc:
        logger.warning(
            "Failed to answer callback query | error=%s",
            exc,
        )
        return False

    except Exception:
        logger.exception(
            "Unexpected error answering callback query"
        )
        return False
