from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from decimal import Decimal, ROUND_HALF_UP

from database import SessionLocal
from config import ADMIN_IDS
from models.deposit import Deposit

router = Router()


def is_admin(user_id: int):
    return user_id in ADMIN_IDS


def _format_value(value, places: str) -> str:
    try:
        rounded = Decimal(str(value or 0)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
        return format(rounded, "f").rstrip("0").rstrip(".") or "0"
    except Exception:
        return "0"


def _admin_deposit_amount(deposit) -> str:
    if (deposit.network or "").upper() == "UPI" and deposit.status == "completed":
        credited = _format_value(deposit.received_amount or deposit.amount, "0.001")
        if deposit.inr_amount is not None:
            return f"₹{_format_value(deposit.inr_amount, '0.01')} → ${credited}"
        return f"${credited}"
    if (deposit.network or "").upper() == "UPI":
        return f"₹{_format_value(deposit.amount, '0.01')}"
    return f"${_format_value(deposit.received_amount or deposit.amount, '0.001')}"


# ==================================================
# DEPOSIT LIST
# ==================================================

@router.callback_query(
    F.data == "admin_deposits"
)
async def admin_deposits(
        callback: CallbackQuery
):

    if not is_admin(
            callback.from_user.id
    ):

        await callback.answer(
            "Access denied.",
            show_alert=True
        )
        return

    db = SessionLocal()

    try:

        deposits = (
            db.query(Deposit)
            .order_by(
                Deposit.id.desc()
            )
            .limit(50)
            .all()
        )

        if not deposits:

            await callback.message.edit_text(
                "❌ No deposits found.",
                reply_markup=
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅ Back",
                                callback_data="admin_panel"
                            )
                        ]
                    ]
                )
            )

            await callback.answer()
            return

        keyboard = []

        for deposit in deposits:

            if deposit.status == "completed":
                icon = "✅"

            elif deposit.status == "failed":
                icon = "❌"

            else:
                icon = "⏳"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=(
                            f"#{deposit.id} "
                            f"{icon} "
                            f"{_admin_deposit_amount(deposit)}"
                        ),

                        callback_data=
                        f"deposit_{deposit.id}"
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    text="⬅ Back",
                    callback_data="admin_panel"
                )
            ]
        )

        await callback.message.edit_text(
            "💰 Latest Deposits",
            reply_markup=
            InlineKeyboardMarkup(
                inline_keyboard=keyboard
            )
        )

        await callback.answer()

    finally:
        db.close()


# ==================================================
# SINGLE DEPOSIT
# ==================================================

@router.callback_query(
    F.data.startswith(
        "deposit_"
    )
)
async def deposit_info(
        callback: CallbackQuery
):

    deposit_id = int(
        callback.data.split("_")[1]
    )

    db = SessionLocal()

    try:

        deposit = (
            db.query(Deposit)
            .filter(
                Deposit.id == deposit_id
            )
            .first()
        )

        if not deposit:

            await callback.answer(
                "Deposit not found."
            )
            return

        text = f"""
💰 Deposit #{deposit.id}

👤 User ID:
<code>{deposit.telegram_id}</code>

💵 Amount:
{_admin_deposit_amount(deposit)}

🌐 Network:
{deposit.network}

🔗 TXID:
<code>{deposit.tx_hash or "Not Submitted"}</code>

📄 Status:
{deposit.status}

📅 Date:
{deposit.created_at}
"""

        keyboard = [

            [
                InlineKeyboardButton(
                    text="⬅ Back",
                    callback_data=
                    "admin_deposits"
                )
            ]
        ]

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=
            InlineKeyboardMarkup(
                inline_keyboard=keyboard
            )
        )

        await callback.answer()

    finally:
        db.close()
