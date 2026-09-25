"""Public FastAPI entry point.

Runs:
- Telegram bot polling
- Delivery bot polling
- Deposit checker
- Public reseller API

Start:
    python render_api.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.reseller_v1 import router as reseller_router
from bot_app import bot, dp
from delivery_bot_app import delivery_bot, delivery_dp
from services.deposit_checker import deposit_checker_loop
from config import API_MAX_REQUEST_BYTES


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("render_api")


# ============================================================
# ENVIRONMENT
# ============================================================

PORT = int(os.getenv("PORT", "10000"))

INTERNAL_SECRET = os.getenv("INTERNAL_API_SECRET", "").strip()

if not INTERNAL_SECRET:
    logger.warning(
        "INTERNAL_API_SECRET is not configured. "
        "The reseller API will reject requests."
    )


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    deposit_task: asyncio.Task | None = None
    polling_task: asyncio.Task | None = None
    delivery_polling_task: asyncio.Task | None = None

    try:
        # ----------------------------------------------------
        # Telegram main bot
        # ----------------------------------------------------

        await bot.delete_webhook(drop_pending_updates=True)

        me = await bot.get_me()

        logger.info(
            "Main Telegram bot connected: @%s",
            me.username,
        )

        # ----------------------------------------------------
        # Deposit checker
        # ----------------------------------------------------

        deposit_task = asyncio.create_task(
            deposit_checker_loop(),
            name="deposit-checker",
        )

        # ----------------------------------------------------
        # Main Telegram polling
        # ----------------------------------------------------

        polling_task = asyncio.create_task(
            dp.start_polling(
                bot,
                handle_signals=False,
                close_bot_session=False,
            ),
            name="telegram-polling",
        )

        # ----------------------------------------------------
        # Delivery bot
        # ----------------------------------------------------

        if delivery_bot and delivery_dp:

            await delivery_bot.delete_webhook(
                drop_pending_updates=False
            )

            delivery_polling_task = asyncio.create_task(
                delivery_dp.start_polling(
                    delivery_bot,
                    handle_signals=False,
                    close_bot_session=False,
                ),
                name="delivery-polling",
            )

            logger.info(
                "Separate manual Delivery Bot started"
            )

        logger.info(
            "FastAPI reseller API + Telegram services started"
        )

        yield

    finally:

        logger.info("Shutting down services...")

        tasks = (
            delivery_polling_task,
            polling_task,
            deposit_task,
        )

        for task in tasks:
            if task and not task.done():
                task.cancel()

        for task in tasks:
            if task:
                with suppress(asyncio.CancelledError):
                    await task

        if bot.session:
            await bot.session.close()

        if delivery_bot and delivery_bot.session:
            await delivery_bot.session.close()

        logger.info("Shutdown complete")


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Rain Reseller API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def api_validation_error(request: Request, exc: RequestValidationError):
    """Keep malformed public API requests small and predictable for clients."""

    if request.url.path.startswith("/api/v1/"):
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "invalid_request",
                "message": "Request contains invalid or missing fields.",
            },
        )

    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ============================================================
# REQUEST LOGGING
# ============================================================

@app.middleware("http")
async def request_logger(request: Request, call_next):

    if request.url.path.startswith("/api/v1/"):
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                request_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "invalid_request",
                        "message": "Content-Length must be a valid number.",
                    },
                )

            if request_size < 0 or request_size > API_MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "success": False,
                        "error": "request_too_large",
                        "message": (
                            f"API request body must not exceed "
                            f"{API_MAX_REQUEST_BYTES} bytes."
                        ),
                    },
                )

    logger.info(
        "%s %s",
        request.method,
        request.url.path,
    )

    try:
        response = await call_next(request)

        logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
        )

        return response

    except Exception:
        logger.exception(
            "Unhandled request error: %s %s",
            request.method,
            request.url.path,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "Internal server error.",
            },
        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Rain Reseller API",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Rain Reseller API",
    }


# ============================================================
# RESELLER API
# ============================================================

# IMPORTANT:
#
# This is now PUBLIC.
#
# There is no:
#
#     /internal/v1
#
# bridge anymore.
#
# Wasmer/external clients can call the API directly.
#
app.include_router(
    reseller_router,
)


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    logger.info(
        "Starting server on 0.0.0.0:%s",
        PORT,
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
