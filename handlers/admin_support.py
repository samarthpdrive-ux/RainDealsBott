from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import SessionLocal
from models.ticket import Ticket
from config import ADMIN_IDS

router = Router()


def is_admin(user_id: int):
    return user_id in ADMIN_IDS


# =====================================================
# TICKET LIST
# =====================================================

@router.callback_query(
    F.data == "admin_tickets"
)
async def admin_tickets(
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

        tickets = (
            db.query(Ticket)
            .order_by(
                Ticket.id.desc()
            )
            .limit(50)
            .all()
        )

        keyboard = []

        for ticket in tickets:

            icon = (
                "🟢"
                if ticket.status == "Open"
                else "🔴"
            )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=
                        f"{icon} "
                        f"#{ticket.id} "
                        f"{ticket.user_id}",
                        callback_data=
                        f"ticket_{ticket.id}"
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
            "🎫 Support Tickets",
            reply_markup=
            InlineKeyboardMarkup(
                inline_keyboard=keyboard
            )
        )

        await callback.answer()

    finally:
        db.close()


# =====================================================
# OPEN TICKET
# =====================================================

@router.callback_query(
    F.data.startswith("ticket_")
)
async def open_ticket(
        callback: CallbackQuery
):

    ticket_id = int(
        callback.data.split("_")[1]
    )

    db = SessionLocal()

    try:

        ticket = (
            db.query(Ticket)
            .filter(
                Ticket.id == ticket_id
            )
            .first()
        )

        if not ticket:

            await callback.answer(
                "Ticket not found."
            )
            return

        try:

            user = await callback.bot.get_chat(
                ticket.user_id
            )

            full_name = (
                user.full_name
            )

            username = (
                f"@{user.username}"
                if user.username
                else "No Username"
            )

        except:

            full_name = "Unknown"
            username = "Unknown"

        text = f"""
🎫 Ticket #{ticket.id}

👤 Name:
{full_name}

🆔 User ID:
<code>{ticket.user_id}</code>

🔗 Username:
{username}

📄 Status:
{ticket.status}

💬 Message:

{ticket.message}
"""

        keyboard = []

        if (
            username != "No Username"
            and username != "Unknown"
        ):

            keyboard.append(
                [
                    InlineKeyboardButton(
                        text="💬 Open User",
                        url=
                        f"https://t.me/"
                        f"{user.username}"
                    )
                ]
            )

        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        text="❌ Close Ticket",
                        callback_data=
                        f"close_ticket_{ticket.id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅ Back",
                        callback_data=
                        "admin_tickets"
                    )
                ]
            ]
        )

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


# =====================================================
# CLOSE TICKET
# =====================================================

@router.callback_query(
    F.data.startswith(
        "close_ticket_"
    )
)
async def close_ticket(
        callback: CallbackQuery
):

    ticket_id = int(
        callback.data.split("_")[2]
    )

    db = SessionLocal()

    try:

        ticket = (
            db.query(Ticket)
            .filter(
                Ticket.id == ticket_id
            )
            .first()
        )

        if not ticket:

            await callback.answer(
                "Ticket not found."
            )
            return

        ticket.status = "Closed"

        db.commit()

    finally:
        db.close()

    await callback.answer(
        "✅ Ticket closed."
    )

    await admin_tickets(
        callback
    )