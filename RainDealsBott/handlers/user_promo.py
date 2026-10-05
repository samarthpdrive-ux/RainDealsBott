"""
handlers/user_promo.py
"""

from decimal import Decimal
import logging

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import SessionLocal
from models.promocode import PromoCode
from models.user import User
from models.deposit import Deposit
from utils.ui import show, update_card

router = Router()
logger = logging.getLogger(__name__)


class RedeemState(StatesGroup):
    waiting_for_code = State()


@router.message(Command("redeem"))
async def redeem_command(message: Message, state: FSMContext):
    parts = (message.text or "").split()

    if len(parts) >= 2:
        await _process_redeem(message, parts[1].strip().upper(), state=state)
        return

    await update_card(
        message, state,
        "🎫 <b>Redeem a Promocode</b>\n\n"
        "Send the promocode or type <code>cancel</code>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅ Cancel",
                        callback_data="deposit_start",
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )

    await state.set_state(RedeemState.waiting_for_code)


@router.callback_query(F.data == "redeem_promo")
async def redeem_button(callback: CallbackQuery, state: FSMContext):
    await show(
        callback,
        "🎫 <b>Redeem a Promocode</b>\n\n"
        "Please send your promocode:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅ Cancel",
                        callback_data="deposit_start",
                    )
                ]
            ]
        ),
        parse_mode="HTML",
        state=state,
    )

    await state.set_state(RedeemState.waiting_for_code)
    await callback.answer()


@router.message(RedeemState.waiting_for_code)
async def redeem_code_input(message: Message, state: FSMContext):
    text = (message.text or "").strip().upper()

    if text == "CANCEL":
        await update_card(message, state, "❌ Redeem cancelled.")
        await state.clear()
        return

    await _process_redeem(message, text, state=state)
    await state.clear()


async def _process_redeem(message: Message, code: str, state: FSMContext | None = None):
    db = SessionLocal()

    try:
        promo = (
            db.query(PromoCode)
            .filter(PromoCode.code == code)
            .first()
        )

        if not promo:
            await update_card(
                message, state,
                f"❌ Invalid promocode:\n<code>{code}</code>",
                parse_mode="HTML",
            )
            return

        if not promo.is_active:
            await update_card(
                message, state,
                "❌ This promocode has been deactivated.",
                parse_mode="HTML",
            )
            return

        if not promo.can_use():
            await update_card(
                message, state,
                "❌ This promocode has reached its usage limit.",
                parse_mode="HTML",
            )
            return

        already_used = (
            db.query(Deposit)
            .filter(
                Deposit.telegram_id == message.from_user.id,
                Deposit.tx_hash == f"PROMO_{code}",
                Deposit.status == "completed",
            )
            .first()
        )

        if already_used:
            await update_card(
                message, state,
                "❌ You have already redeemed this promocode.",
                parse_mode="HTML",
            )
            return

        user = (
            db.query(User)
            .filter(User.telegram_id == message.from_user.id)
            .first()
        )

        if not user:
            await update_card(
                message, state,
                "❌ User not found.\nPlease use /start first."
            )
            return

        # -----------------------------
        # FIX: Always use Decimal
        # -----------------------------
        promo_amount = Decimal(str(promo.amount))

        user.balance += promo_amount
        promo.used_count += 1

        deposit = Deposit(
            telegram_id=message.from_user.id,
            amount=promo_amount,
            tx_hash=f"PROMO_{code}",
            network="PROMO",
            status="completed",
        )

        db.add(deposit)
        db.commit()
        db.refresh(user)

        await update_card(
            message, state,
            f"🎉 <b>Promocode Redeemed!</b>\n\n"
            f"🏷 <code>{code}</code>\n"
            f"💰 <b>+{promo_amount} USDT</b>\n"
            f"💳 Balance: <b>{user.balance} USDT</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅ Main Menu", callback_data="main_menu")]]
            ),
        )

        logger.info(
            "Promo redeemed | Code=%s | Amount=%s | User=%s",
            code,
            promo_amount,
            message.from_user.id,
        )

    except Exception:
        db.rollback()
        logger.exception("Promo redeem error")
        await update_card(message, state, "❌ An unexpected error occurred.")

    finally:
        db.close()