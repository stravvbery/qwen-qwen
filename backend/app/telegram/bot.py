"""Telegram bot entry point — aiogram 3 with polling.

Can be run standalone or integrated into the FastAPI app lifecycle.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..config import settings
from .handlers import router

log = logging.getLogger(__name__)


def create_bot() -> Bot:
    """Create and configure the aiogram Bot instance."""
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Set it via environment variable or .env file."
        )
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


def create_dispatcher() -> Dispatcher:
    """Create dispatcher and register all routers."""
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def run_polling() -> None:
    """Start the bot with long-polling (for development or standalone mode)."""
    bot = create_bot()
    dp = create_dispatcher()

    log.info("Starting Telegram bot polling...")

    # Delete any stale webhook
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


async def start_bot_background() -> tuple[Bot, Dispatcher, asyncio.Task]:
    """Start bot polling in background — for integration with FastAPI lifespan."""
    bot = create_bot()
    dp = create_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)

    task = asyncio.create_task(dp.start_polling(bot))
    log.info("Telegram bot started in background")
    return bot, dp, task


async def stop_bot_background(bot: Bot, dp: Dispatcher, task: asyncio.Task) -> None:
    """Gracefully stop the background bot."""
    await dp.stop_polling()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await bot.session.close()
    log.info("Telegram bot stopped")


# ---------------------------------------------------------------------------
# Standalone entry point: python -m app.telegram.bot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run_polling())
