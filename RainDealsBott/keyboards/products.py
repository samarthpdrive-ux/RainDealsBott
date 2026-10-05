from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)


def buy_keyboard(product_id: int, button_text: str = "🛒 Buy"):
    """
    Opens the quantity selector instead of buying instantly — lets the
    customer pick how many units they want before confirming.
    `button_text` can be swapped to "📦 Preorder" for out-of-stock items
    that have preorder enabled.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"select_qty_{product_id}"
                )
            ]
        ]
    )
