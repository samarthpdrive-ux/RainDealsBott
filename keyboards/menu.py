from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 Shop Products",
                    callback_data="products_menu",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="🎁 Refer & Earn",
                    callback_data="referrals_menu",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 My Orders",
                    callback_data="orders_menu",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="💰 My Wallet",
                    callback_data="deposit_start",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🆘 Help & Support",
                    callback_data="support_ticket",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="👤 My Profile",
                    callback_data="my_profile",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔑 API Access",
                    callback_data="api_key_menu",
                    style="primary",
                )
            ]
        ]
    )


def get_admin_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 Shop Products",
                    callback_data="products_menu",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="🎁 Refer & Earn",
                    callback_data="referrals_menu",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 My Orders",
                    callback_data="orders_menu",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="💰 My Wallet",
                    callback_data="deposit_start",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🆘 Help & Support",
                    callback_data="support_ticket",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="👤 My Profile",
                    callback_data="my_profile",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔑 API Access",
                    callback_data="api_key_menu",
                    style="primary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👑 Admin",
                    callback_data="admin_panel",
                    style="danger",
                )
            ]
        ]
    )
