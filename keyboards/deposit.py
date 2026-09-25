# keyboards/deposit.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_deposit_menu() -> InlineKeyboardMarkup:
    """Deposit method selection keyboard with real Telegram button colors.

    Uses Bot API 9.4+ style parameter:
      - 'primary' (blue) — BEP20, UPI
      - 'success' (green) — Polygon, Redeem Promocode, My Deposits
      - 'danger' (red) — Binance Pay

    Deposit options grouped together, Main Menu separated below.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            # ── Deposit Methods ──
            [
                InlineKeyboardButton(
                    text="💎 USDT (BEP20)",
                    callback_data="deposit_bep20",
                    style="primary"
                ),
                InlineKeyboardButton(
                    text="💎 USDT (Polygon)",
                    callback_data="deposit_polygon",
                    style="success"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔴 Binance Pay",
                    callback_data="deposit_binance",
                    style="danger"
                ),
                InlineKeyboardButton(
                    text="💵 UPI (₹ INR)",
                    callback_data="deposit_upi",
                    style="primary"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏷️ Redeem Promocode",
                    callback_data="deposit_promo",
                    style="success"
                ),
            ],
            # ── History ──
            [
                InlineKeyboardButton(
                    text="📜 My Deposits",
                    callback_data="my_deposits",
                    style="success"
                ),
            ],
            # ── Navigation ──
            [
                InlineKeyboardButton(
                    text="🏠 Main Menu",
                    callback_data="main_menu",
                ),
            ],
        ]
    )