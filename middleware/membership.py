import logging
import asyncio
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject, Update

from config import ADMIN_IDS, CHANNEL_LINK, GROUP_LINK, BANNED_USER_CACHE_TTL, MEMBERSHIP_CACHE_TTL
from database import SessionLocal
from models.user import User

logger = logging.getLogger(__name__)


def _extract_username(link: str) -> str | None:
    """Extract @username from a public t.me link; skip private invites."""
    if not link:
        return None

    username = link.rstrip("/").split("/")[-1]
    if username.startswith("+"):
        logger.warning("Skipping private membership link: %s", link)
        return None

    return f"@{username.lstrip('@')}"


CHANNEL_USERNAME = _extract_username(CHANNEL_LINK)
GROUP_USERNAME = _extract_username(GROUP_LINK)


async def check_user_membership(bot, user_id: int) -> bool:
    """Return True only when the user belongs to every configured public chat."""
    now = time.monotonic()
    cached = _membership_cache.get(user_id)
    if cached and now - cached[1] < MEMBERSHIP_CACHE_TTL:
        return cached[0]

    chats = [chat for chat in (CHANNEL_USERNAME, GROUP_USERNAME) if chat]
    if not chats:
        logger.warning("No valid public membership chat configured; allowing access")
        return True

    async def check_chat(chat_username: str) -> bool:
        try:
            # Do both checks concurrently and fail quickly instead of making a
            # user wait for Telegram's full request timeout.
            member = await asyncio.wait_for(
                bot.get_chat_member(chat_id=chat_username, user_id=user_id), timeout=5
            )
            return member.status not in ("left", "kicked")
        except Exception:
            # A temporary Telegram/API configuration failure must not lock users out.
            logger.exception("Membership check failed for %s", chat_username)
            return True

    is_member = all(await asyncio.gather(*(check_chat(chat) for chat in chats)))
    if MEMBERSHIP_CACHE_TTL > 0:
        _membership_cache[user_id] = (is_member, now)
    return is_member


def get_join_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if CHANNEL_LINK and not CHANNEL_LINK.rstrip("/").split("/")[-1].startswith("+"):
        buttons.append([InlineKeyboardButton(text="📢 Join Channel", url=CHANNEL_LINK)])
    if GROUP_LINK and not GROUP_LINK.rstrip("/").split("/")[-1].startswith("+"):
        buttons.append([InlineKeyboardButton(text="👥 Join Group", url=GROUP_LINK)])
    buttons.append([InlineKeyboardButton(text="🔄 Try Again", callback_data="check_membership_retry")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_user_banned(telegram_id: int) -> bool:
    """Read the ban flag for a Telegram user. Admins are never restricted."""
    if telegram_id in ADMIN_IDS:
        return False

    db = SessionLocal()
    try:
        user = db.query(User.is_banned).filter(User.telegram_id == telegram_id).first()
        return bool(user and user[0])
    finally:
        db.close()


# Membership and ban status do not change on every update. Keeping these
# caches local is safe for responsiveness; ban cache duration is deliberately
# short so administration changes become effective quickly.
_membership_cache: dict[int, tuple[bool, float]] = {}
_banned_user_cache: dict[int, tuple[bool, float]] = {}


def _read_banned_user_cached(telegram_id: int) -> bool:
    now = time.monotonic()
    cached = _banned_user_cache.get(telegram_id)
    if cached and now - cached[1] < BANNED_USER_CACHE_TTL:
        return cached[0]

    banned = is_user_banned(telegram_id)
    if BANNED_USER_CACHE_TTL > 0:
        _banned_user_cache[telegram_id] = (banned, now)
    return banned


# These are the ONLY callback-data prefixes a banned user can use.
# Adjust them to match the callback_data in your customer handlers.
BANNED_READ_ONLY_CALLBACKS = (
    # Change these only if your customer handlers use different callback_data.
    "orders", "my_orders", "view_order_", "order_",
    "support", "tickets", "ticket_", "view_ticket_",
    "my_deposits", "deposit_history", "view_deposit_",
    "contact_info",
)

# Prevents repeated restricted-account messages when a banned user types.
_restricted_menu_shown: set[int] = set()


def get_restricted_keyboard() -> InlineKeyboardMarkup:
    """The only navigation a restricted account is allowed to see."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 My Orders", callback_data="orders_menu")],
        [InlineKeyboardButton(text="🎫 Support Tickets", callback_data="support_ticket")],
        [InlineKeyboardButton(text="📥 My Deposits", callback_data="my_deposits")],
    ])


RESTRICTED_TEXT = (
    "🚫 <b>Account Restricted</b>\n\n"
    "Your account cannot make purchases or deposits.\n"
    "You can still view your existing orders, support tickets, and deposits."
)


def _is_banned_read_only_callback(callback_data: str | None) -> bool:
    return bool(callback_data) and callback_data.startswith(BANNED_READ_ONLY_CALLBACKS)


class BannedUserMiddleware(BaseMiddleware):
    """Block banned accounts before handlers run.

    Banned users may only use callback buttons listed in
    BANNED_READ_ONLY_CALLBACKS. All messages are blocked, preventing
    purchases, deposits, and support-ticket replies by default.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Dispatcher-level middleware receives an Update wrapper. Router-level
        # middleware receives the Message/CallbackQuery itself.
        actual_event = event.event if isinstance(event, Update) else event
        from_user = getattr(actual_event, "from_user", None)
        # SQLAlchemy/PyMySQL is synchronous. Never run it directly on the
        # asyncio event loop, otherwise one slow TiDB request freezes every
        # command and callback for all users.
        if not from_user or not await asyncio.to_thread(_read_banned_user_cached, from_user.id):
            return await handler(event, data)

        if isinstance(actual_event, CallbackQuery) and _is_banned_read_only_callback(actual_event.data):
            return await handler(event, data)

        if isinstance(actual_event, CallbackQuery):
            # Edit the existing screen instead of sending repeated messages.
            if actual_event.message:
                try:
                    await actual_event.message.edit_text(
                        RESTRICTED_TEXT,
                        parse_mode="HTML",
                        reply_markup=get_restricted_keyboard(),
                    )
                except Exception:
                    # Telegram rejects an edit when the screen is already identical.
                    pass
            await actual_event.answer("Account restricted.")
        elif isinstance(actual_event, Message):
            # Delete new typed messages, so the chat is not flooded.
            try:
                await actual_event.delete()
            except Exception:
                pass

            # Send the restricted menu just once per bot process.
            if from_user.id not in _restricted_menu_shown:
                _restricted_menu_shown.add(from_user.id)
                await actual_event.answer(
                    RESTRICTED_TEXT,
                    parse_mode="HTML",
                    reply_markup=get_restricted_keyboard(),
                )

        return None
