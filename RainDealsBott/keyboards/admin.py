from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)


def get_admin_panel():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👥 Users",
                    callback_data="admin_users"
                ),
                InlineKeyboardButton(
                    text="📦 Products",
                    callback_data="admin_products"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📦 Orders",
                    callback_data="admin_orders"
                ),
                InlineKeyboardButton(
                    text="💰 Deposits",
                    callback_data="admin_deposits"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🎫 Tickets",
                    callback_data="admin_tickets"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📢 Broadcast",
                    callback_data="admin_broadcast"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Back",
                    callback_data="admin_back"
                )
            ]
        ]
    )