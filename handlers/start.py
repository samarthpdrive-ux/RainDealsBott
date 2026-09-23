# handlers/start.py — FULLY FIXED + MAX SPEED + EXACT WALLET BALANCE

import asyncio
import logging
import uuid
from types import SimpleNamespace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from html import escape as html_escape

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import SessionLocal, transaction, retry_on_write_conflict
from models.user import User
from config import ADMIN_IDS, CHANNEL_LINK, GROUP_LINK, TOS_LINK

from keyboards.menu import get_main_menu, get_admin_main_menu
from utils.ui import show

# Membership check
from middleware.membership import check_user_membership, get_join_keyboard

logger = logging.getLogger(__name__)

router = Router()


# ╔══════════════════════════════════════════════════════════════╗
# ║  HTML-SAFE HELPERS                                         ║
# ╚══════════════════════════════════════════════════════════════╝

def safe(text: str) -> str:
    return html_escape(str(text), quote=False)


def link(text: str, url: str) -> str:
    return f"<a href='{url}'>{safe(text)}</a>"


# ╔══════════════════════════════════════════════════════════════╗
# ║  PRE-COMPUTED STATIC STRINGS                                ║
# ╚══════════════════════════════════════════════════════════════╝

_DOUBLE_LINE = "════════════════════════════"
_SINGLE_LINE = "────────────────────────────"
_DASH_LINE = "━━━━━━━━━━━━━━━━━━━━━━"

_BOX_WELCOME = (
    "╔════════════════════════════╗\n"
    "║        🎉 WELCOME          ║\n"
    "╚════════════════════════════╝"
)

_NEW_USER_GUIDE = (
    f"{_DOUBLE_LINE}\n\n"
    f"🎯 <b>Your Account is Ready!</b>\n\n"
    f"<b>📋 Quick Start Guide:</b>\n\n"
    f"💰 <b>1. Deposit Funds</b>\n"
    f"   └ Add balance via crypto or UPI\n\n"
    f"🛍 <b>2. Browse Products</b>\n"
    f"   └ Explore our catalog\n\n"
    f"🛒 <b>3. Make a Purchase</b>\n"
    f"   └ Instant delivery for auto products\n\n"
    f"🤝 <b>4. Refer Friends</b>\n"
    f"   └ Earn commission on their purchases\n"
)

_NEW_REF_BONUS = (
    f"\n{_DOUBLE_LINE}\n\n"
    f"🎁 <b>You joined via a referral link!</b>\n"
    f"Your referrer will earn commission on your first\n"
    f"purchases. You too can share your own referral\n"
    f"link to earn rewards! 🤝"
)


# ╔══════════════════════════════════════════════════════════════╗
# ║  FAST HELPERS                                              ║
# ╚══════════════════════════════════════════════════════════════╝

def _time_greeting() -> tuple[str, str]:
    h = datetime.now().hour
    if h < 12:
        return ("🌅", "Good Morning")
    if h < 17:
        return ("☀️", "Good Afternoon")
    if h < 21:
        return ("🌆", "Good Evening")
    return ("🌙", "Good Night")


def _status(balance: float) -> str:
    if balance <= 0:
        return "Empty"
    if balance < 10:
        return "Low"
    if balance < 100:
        return "Active"
    return "Premium"


def _get_member_since(user) -> str:
    created = (
            getattr(user, 'created_at', None) or
            getattr(user, 'date_joined', None) or
            getattr(user, 'created', None) or
            getattr(user, 'joined_at', None) or
            getattr(user, 'registered_at', None)
    )
    if created is not None and hasattr(created, 'strftime'):
        return created.strftime("%d %b %Y")
    return "N/A"


def generate_ref_code() -> str:
    return uuid.uuid4().hex[:8].upper()


def _format_balance(raw_balance) -> str:
    """Display wallet values with at most three decimal places."""
    try:
        dec_val = Decimal(str(raw_balance or 0))
        rounded = dec_val.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return format(rounded, "f").rstrip("0").rstrip(".") or "0"
    except Exception:
        return "0"


# ╔══════════════════════════════════════════════════════════════╗
# ║  AUDIT-STYLE PROFILE BUILDER                               ║
# ╚══════════════════════════════════════════════════════════════╝

def _build_audit_profile(user, telegram_id: int) -> str:
    """Terminal audit-style profile dashboard."""
    is_admin = telegram_id in ADMIN_IDS
    is_banned = bool(getattr(user, 'is_banned', False))
    balance_raw = getattr(user, 'balance_display', getattr(user, 'balance', 0))
    balance_str = _format_balance(balance_raw)

    ref_earnings = float(getattr(user, 'referral_earnings_display', 0))
    total_dep = float(getattr(user, 'total_deposited', 0) or 0)
    total_spent = float(getattr(user, 'total_spent', 0) or 0)
    total_orders = getattr(user, 'total_orders', 0) or 0
    total_refs = getattr(user, 'total_referrals', 0) or 0
    ref_code = getattr(user, 'referral_code', 'N/A') or 'N/A'
    member_since = _get_member_since(user)
    username = str(getattr(user, 'username', '') or 'user')
    full_name = str(getattr(user, 'full_name', 'Unknown'))

    if is_banned:
        role = "Banned"
    elif is_admin:
        role = "Administrator"
    else:
        role = "Standard"

    if total_orders > 0:
        avg_order = f"${(total_spent / total_orders):.2f}"
    else:
        avg_order = "$0.00"

    try:
        numeric_bal = float(balance_raw or 0)
    except Exception:
        numeric_bal = 0.0

    return (
        f"<code>┌──({username}㉿Rain)-[/audit]</code>\n"
        f"<code>└─$ sudo profilectl audit</code>\n"
        f"<code>[sudo] password for {username}:</code>\n"
        f"<code>************</code>\n"
        f"<code>:: Authenticating identity...</code>\n"
        f"<code>:: Mounting vault...</code>\n"
        f"<code>:: Indexing ledger...</code>\n"
        f"<code>:: Loading activity logs...</code>\n"
        f"<code>:: Synchronizing referrals...</code>\n"
        f"<code>{_DASH_LINE}</code>\n"
        f"<code>PROFILE</code>\n"
        f"<code>Name        {full_name}</code>\n"
        f"<code>UID         {telegram_id}</code>\n"
        f"<code>Role        {role}</code>\n"
        f"<code>Joined      {member_since}</code>\n"
        f"<code>{_DASH_LINE}</code>\n"
        f"<code>ACCOUNT</code>\n"
        f"<code>Balance     ${balance_str}</code>\n"
        f"<code>Status      {_status(numeric_bal)}</code>\n"
        f"<code>Deposited   ${total_dep:.2f}</code>\n"
        f"<code>Spent       ${total_spent:.2f}</code>\n"
        f"<code>Rewards     ${ref_earnings:.2f}</code>\n"
        f"<code>{_DASH_LINE}</code>\n"
        f"<code>NETWORK</code>\n"
        f"<code>Orders      {total_orders}</code>\n"
        f"<code>Avg Order   {avg_order}</code>\n"
        f"<code>Referrals   {total_refs}</code>\n"
        f"<code>Invite ID   {ref_code}</code>\n"
        f"<code>{_DASH_LINE}</code>\n"
        f"<code>Audit complete.</code>\n"
        f"<code>root@Rain:~#</code>"
    )


# ╔══════════════════════════════════════════════════════════════╗
# ║  MODERN /start BUILDER — TERMINAL STYLE                     ║
# ╚══════════════════════════════════════════════════════════════╝

def _build_start_welcome(user, full_name: str) -> str:
    """Terminal-style welcome dashboard with exact fractional balance display."""
    balance_raw = getattr(user, 'balance_display', getattr(user, 'balance', 0))
    balance_str = _format_balance(balance_raw)

    total_orders = int(getattr(user, 'total_orders', 0) or 0)
    total_refs = int(getattr(user, 'total_referrals', 0) or 0)

    first_name = full_name.split()[0] if full_name else "user"

    return (
        "🛍 Rain Store\n"
        "Premium Digital Marketplace\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 Welcome back, {safe(first_name)}\n\n"
        "💎 Standard Plan\n\n"
        f"💰 Wallet: ${balance_str}\n"
        f"📦 Orders: {total_orders}\n"
        f"🎁 Rewards: {total_refs}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "<blockquote>"
        "✓ Verified Premium Products\n"
        "✓ Instant Delivery\n"
        "✓ Secure Payments\n"
        "✓ Dedicated Customer Support"
        "</blockquote>\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "<blockquote>"
        "🛒 Shop \"Browse premium digital products\"\n"
        "💰 Deposit \"Top up your wallet instantly\"\n"
        "👤 Profile \"Manage your account & wallet\"\n"
        "📦 Orders \"View purchases & product keys\"\n"
        "📞 Support \"Get help from our support team\""
        "</blockquote>\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📢 Stay Updated: @Senacoun\n\n"
        "👇 Tap a button below to get started."
    )


# ╔══════════════════════════════════════════════════════════════╗
# ║  CALLBACK HANDLERS                                         ║
# ╚══════════════════════════════════════════════════════════════╝

@router.callback_query(F.data == "profile_back")
async def profile_back_cb(callback: CallbackQuery):
    """Back button from Profile → DELETES the profile message. Main menu stays."""
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "main_menu")
async def main_menu_cb(callback: CallbackQuery, state: FSMContext):
    """Back to main menu — edits the current message."""
    await state.clear()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == callback.from_user.id).first()
        if not user:
            await callback.answer("User not found.", show_alert=True)
            return

        text = _build_start_welcome(user, callback.from_user.full_name)
        is_admin = callback.from_user.id in ADMIN_IDS
        keyboard = get_admin_main_menu() if is_admin else get_main_menu()

        await show(callback, text, reply_markup=keyboard, parse_mode="HTML")
    finally:
        db.close()

    await callback.answer()


@router.callback_query(F.data == "my_profile")
async def my_profile(callback: CallbackQuery):
    """Profile → sends NEW audit-style message with Back button. Main menu stays."""
    await callback.answer()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == callback.from_user.id).first()
        if not user:
            await callback.answer("User not found.", show_alert=True)
            return

        text = _build_audit_profile(user, callback.from_user.id)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Back", callback_data="profile_back")],
            ]
        )

        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    finally:
        db.close()


# ╔══════════════════════════════════════════════════════════════╗
# ║  MEMBERSHIP RETRY CALLBACK                                 ║
# ╚══════════════════════════════════════════════════════════════╝

@router.callback_query(F.data == "check_membership_retry")
async def retry_membership_check(callback: CallbackQuery):
    """Re-check if user has joined the channel."""
    is_member = await check_user_membership(callback.bot, callback.from_user.id)

    if is_member:
        await callback.message.delete()
        await callback.message.answer(
            "✅ <b>Verification Successful!</b>\n\n"
            "Send /start to begin using the bot.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Verified! Send /start", show_alert=True)
    else:
        await callback.answer(
            "❌ You haven't joined yet! Please join all channels first.",
            show_alert=True
        )


# ╔══════════════════════════════════════════════════════════════╗
# ║  USER CREATION                                             ║
# ╚══════════════════════════════════════════════════════════════╝

@retry_on_write_conflict(max_attempts=3)
def _get_or_create_user(telegram_id: int, username: str, full_name: str, ref_payload: str) -> dict:
    with transaction() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        is_new = False
        referral_bonus = False

        if not user:
            is_new = True
            referred_by = None

            if ref_payload:
                referrer = (
                    db.query(User)
                    .filter(User.referral_code == ref_payload)
                    .with_for_update()
                    .first()
                )
                if referrer is not None and referrer.telegram_id != telegram_id:
                    referred_by = referrer.telegram_id
                    referrer.total_referrals = (referrer.total_referrals or 0) + 1
                    referral_bonus = True

            user = User(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                balance=0,
                referral_code=generate_ref_code(),
                referred_by=referred_by,
                total_referrals=0,
                referral_earnings=0,
                total_orders=0,
                total_spent=0,
                total_deposited=0,
                is_banned=False,
            )
            db.add(user)
            db.flush()
        else:
            user.username = username
            user.full_name = full_name

        return {
            "is_new": is_new,
            "referral_bonus": referral_bonus,
            "referral_code": user.referral_code,
            "referred_by": getattr(user, "referred_by", None),
            # Return the dashboard values from the same transaction. This
            # removes the second remote database query from every /start.
            "profile": {
                "balance": user.balance,
                "total_orders": user.total_orders,
                "total_referrals": user.total_referrals,
            },
        }


# ╔══════════════════════════════════════════════════════════════╗
# ║  /start COMMAND — With Membership Check                     ║
# ╚══════════════════════════════════════════════════════════════╝

@router.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject):
    telegram_id = message.from_user.id

    # ═══════════════════════════════════════════════════════
    # CHANNEL MEMBERSHIP CHECK (skip for admins)
    # ═══════════════════════════════════════════════════════
    if telegram_id not in ADMIN_IDS:
        is_member = await check_user_membership(message.bot, telegram_id)
        if not is_member:
            await message.answer(
                "⚠️ <b>Access Restricted</b>\n\n"
                "You must join our channel to use the bot.\n\n"
                "👇 Join below, then press <b>Try Again</b>",
                reply_markup=get_join_keyboard(),
                parse_mode="HTML"
            )
            return

    username = message.from_user.username
    full_name = message.from_user.full_name
    ref_payload = (command.args or "").strip() if command else ""
    is_admin = telegram_id in ADMIN_IDS

    db_task = asyncio.to_thread(
        _get_or_create_user, telegram_id, username, full_name, ref_payload
    )

    emoji, greeting = _time_greeting()

    try:
        result = await db_task
    except Exception:
        logger.exception("Failed to create/update user %s on /start", telegram_id)
        await message.answer(
            "❌ <b>Startup Error</b>\n\nSomething went wrong starting your session.\nPlease try again with /start",
            parse_mode="HTML"
        )
        return

    if result["is_new"]:
        admin_greet = "👑 Welcome back, Admin!" if is_admin else "🎉 Welcome aboard!"
        welcome_text = (
            f"{_BOX_WELCOME}\n\n"
            f"{emoji} {greeting}, <b>{safe(full_name)}</b>!\n"
            f"{admin_greet}\n\n"
            f"{_NEW_USER_GUIDE}"
        )
        if result["referral_bonus"]:
            welcome_text += _NEW_REF_BONUS
        welcome_text += (
            f"\n{_DOUBLE_LINE}\n\n"
            f"🔗 <b>Your Referral Code:</b>\n<code>{safe(result['referral_code'])}</code>\n\n"
            f"<i>Share this code with friends to earn!</i>\n\n"
            f"👇 <b>Your main menu is below:</b>"
        )
        await message.answer(welcome_text, parse_mode="HTML", disable_web_page_preview=True)

    user = SimpleNamespace(**result["profile"])
    text = _build_start_welcome(user, full_name)
    keyboard = get_admin_main_menu() if is_admin else get_main_menu()
    await message.answer(
        text, reply_markup=keyboard, parse_mode="HTML",
        disable_web_page_preview=True
    )
