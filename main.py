import asyncio
import logging
import sys

# Force UTF-8 encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import config
from database import init_db
from handlers.start import start_router
from handlers.services import services_router
from handlers.payment import payment_router
from handlers.admin import admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("payment_bot")

async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN.startswith("123456789:ABC"):
        separator = "=" * 60
        err_msg = (
            f"\n{separator}\n"
            "🚨 CRITICAL CONFIGURATION ERROR:\n"
            "BOT_TOKEN is not configured in your .env file!\n"
            "Please create or edit your .env file with your token from @BotFather:\n"
            "BOT_TOKEN=your_actual_bot_token_here\n"
            f"{separator}\n"
        )
        logger.error(err_msg)
        sys.exit(1)

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully.")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Include routers in order
    dp.include_router(start_router)
    dp.include_router(services_router)
    dp.include_router(payment_router)
    dp.include_router(admin_router)

    # Fetch bot info
    me = await bot.get_me()
    logger.info(f"Bot @{me.username} (ID: {me.id}) started successfully.")
    logger.info(f"Admin Group ID configured: {config.ADMIN_GROUP_ID}")
    logger.info(f"Configured UPI ID: {config.UPI_ID}")

    try:
        # Start long polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
