# ============================================================
# NOMANBOT - BOT APPLICATION
# ============================================================

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN

from middleware.membership import BannedUserMiddleware


# ============================================================
# USER ROUTERS
# ============================================================

from handlers.start import router as start_router
from handlers.products import router as products_router
from handlers.orders import router as orders_router
from handlers.deposit import router as deposit_router
from handlers.referral import router as referrals_router
from handlers.support import router as support_router
from handlers.user_promo import router as user_promo_router
from handlers.api_keys import router as api_keys_router


# ============================================================
# ADMIN ROUTERS
# ============================================================

from handlers.admin import router as admin_router
from handlers.admin_products import router as admin_products_router
from handlers.admin_product_manage import router as admin_product_manage_router
from handlers.admin_orders import router as admin_orders_router
from handlers.admin_deposits import router as admin_deposits_router
from handlers.admin_support import router as admin_support_router
from handlers.admin_promo import router as admin_promo_router


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# BOT TOKEN
# ============================================================

if not BOT_TOKEN:

    raise RuntimeError(
        "BOT_TOKEN is not configured."
    )


# ============================================================
# BOT
# ============================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)


# ============================================================
# DISPATCHER
# ============================================================

dp = Dispatcher(
    storage=MemoryStorage(),
)


# ============================================================
# GLOBAL BAN MIDDLEWARE
# ============================================================

dp.update.outer_middleware(
    BannedUserMiddleware()
)


# ============================================================
# LOAD USER ROUTERS
# ============================================================

logger.info(
    "Loading user routers..."
)

dp.include_router(
    start_router
)

dp.include_router(
    products_router
)

dp.include_router(
    orders_router
)

dp.include_router(
    referrals_router
)

dp.include_router(
    deposit_router
)

dp.include_router(
    user_promo_router
)

# API Access button handler
dp.include_router(
    api_keys_router
)

dp.include_router(
    support_router
)


# ============================================================
# LOAD ADMIN ROUTERS
# ============================================================

logger.info(
    "Loading admin routers..."
)

dp.include_router(
    admin_router
)

dp.include_router(
    admin_products_router
)

dp.include_router(
    admin_product_manage_router
)

dp.include_router(
    admin_orders_router
)

dp.include_router(
    admin_deposits_router
)

dp.include_router(
    admin_support_router
)

dp.include_router(
    admin_promo_router
)


# ============================================================
# READY
# ============================================================

logger.info(
    "=================================================="
)

logger.info(
    "NomanBot initialized successfully"
)

logger.info(
    "All routers loaded"
)

logger.info(
    "=================================================="
)


# ============================================================
# BOT INFO
# ============================================================

async def get_bot_info():

    return await bot.get_me()


# ============================================================
# CLOSE BOT
# ============================================================

async def close_bot():

    try:

        await bot.session.close()

        logger.info(
            "Bot session closed"
        )

    except Exception:

        logger.exception(
            "Error closing bot session"
        )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "bot",
    "dp",
    "get_bot_info",
    "close_bot",
]