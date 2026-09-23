"""The separate Telegram bot used only for manual reseller deliveries.

Customers must press Start on this bot before Telegram lets it send them a
manual order.  The bot never exposes the main store bot or its token.
"""

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from config import DELIVERY_BOT_TOKEN


delivery_bot: Bot | None = None
delivery_dp: Dispatcher | None = None

if DELIVERY_BOT_TOKEN:
    delivery_bot = Bot(
        token=DELIVERY_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    delivery_dp = Dispatcher(storage=MemoryStorage())

    @delivery_dp.message(CommandStart())
    async def delivery_bot_start(message: Message) -> None:
        await message.answer(
            "📦 <b>Delivery Bot Ready</b>\n\n"
            "You will receive manual order details here when your reseller or "
            "store administrator completes the order."
        )

    @delivery_dp.message(F.text)
    async def delivery_bot_help(message: Message) -> None:
        await message.answer("This bot is only used for secure manual order delivery. Please wait for your order.")
