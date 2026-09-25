# ============================================================
# NOMANBOT - RENDER POLLING ENTRY POINT
# ============================================================

import asyncio
import logging
import os

from aiohttp import web

from bot_app import bot, dp

from services.deposit_checker import deposit_checker_loop
from services.order_notifications import order_notification_loop


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# HEALTH
# ============================================================

async def health(request):

    return web.Response(
        text="NomanBot is running!"
    )


# ============================================================
# HTTP SERVER
# ============================================================

async def start_http_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health,
    )

    runner = web.AppRunner(
        app
    )

    await runner.setup()

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port,
    )

    await site.start()

    logger.info(
        "HTTP server running on port %s",
        port,
    )

    return runner


# ============================================================
# MAIN
# ============================================================

async def main():

    runner = None

    deposit_task = None
    order_notification_task = None

    # --------------------------------------------------------
    # HTTP SERVER
    # --------------------------------------------------------

    runner = await start_http_server()

    # --------------------------------------------------------
    # DEPOSIT CHECKER
    # --------------------------------------------------------

    deposit_task = asyncio.create_task(
        deposit_checker_loop(bot)
    )

    logger.info(
        "Deposit checker started"
    )

    order_notification_task = asyncio.create_task(
        order_notification_loop(bot)
    )

    logger.info(
        "Admin order notification service started"
    )

    # --------------------------------------------------------
    # BOT INFO
    # --------------------------------------------------------

    me = await bot.get_me()

    logger.info(
        "Logged in as @%s",
        me.username,
    )

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    # --------------------------------------------------------
    # POLLING
    # --------------------------------------------------------

    logger.info(
        "Starting polling..."
    )

    try:

        await dp.start_polling(
            bot
        )

    finally:

        if deposit_task and not deposit_task.done():

            deposit_task.cancel()

            try:

                await deposit_task

            except asyncio.CancelledError:

                pass

        if order_notification_task and not order_notification_task.done():

            order_notification_task.cancel()

            try:

                await order_notification_task

            except asyncio.CancelledError:

                pass

        if runner:

            await runner.cleanup()

            logger.info(
                "HTTP server runner cleaned up"
            )

        if bot and bot.session:

            await bot.session.close()

            logger.info(
                "Bot session closed"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "NomanBot stopped"
        )

    except Exception as exc:

        logger.exception(
            "FATAL ERROR: %s",
            exc,
        )


