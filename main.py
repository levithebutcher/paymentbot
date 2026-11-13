import asyncio
import logging
import sys

# Force UTF-8 encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import os
from aiohttp import web
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

async def start_healthcheck_server():
    """Starts a lightweight HTTP server if running on cloud platforms like Render that require an open PORT."""
    port_str = os.getenv("PORT")
    if not port_str:
        return None
    try:
        port = int(port_str)
        app = web.Application()
        async def health(request):
            return web.Response(text="Payment Bot is healthy and running!")
        app.router.add_get("/", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Render healthcheck HTTP server running on port {port}")
        return runner
    except Exception as e:
        logger.warning(f"Could not start healthcheck server on port {port_str}: {e}")
        return None

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

    # Configure official bot command menu (Menu button on bottom left)
    from aiogram.types import BotCommand
    commands = [
        BotCommand(command="start", description="🏠 Main Menu & Services"),
        BotCommand(command="services", description="💎 View Services Catalog"),
        BotCommand(command="orders", description="📦 My Orders History"),
        BotCommand(command="support", description="💬 Live Customer Support"),
        BotCommand(command="help", description="ℹ️ How to Order & FAQs"),
        BotCommand(command="resolve", description="🔗 Resolve S3 / Paste Link"),
        BotCommand(command="cancel", description="✕ Cancel Active Order"),
    ]
    try:
        await bot.set_my_commands(commands)
        logger.info("Bot command menu configured successfully.")
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")

    health_runner = await start_healthcheck_server()

    try:
        # Start long polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if health_runner:
            await health_runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
