"""Application entry point & scheduler startup."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.config import get_settings
from bot.container import Container
from bot.db.database import Database
from bot.handlers import chat, commands
from bot.middlewares import ContainerMiddleware
from bot.services.memory import MemoryService
from bot.services.scheduler import CheckinScheduler

logger = logging.getLogger(__name__)


async def set_default_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Say hi"),
            BotCommand(command="reset", description="Clear recent chat history"),
            BotCommand(command="memory", description="See what Aura remembers"),
        ]
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    db = Database(settings.db_path)
    await db.connect()

    bot = Bot(token=settings.bot_token)
    memory = MemoryService(db)
    container = Container(settings=settings, db=db, bot=bot, memory=memory)
    container.debouncer = chat.Debouncer(container)
    scheduler = CheckinScheduler(container)

    dp = Dispatcher()
    dp.message.middleware(ContainerMiddleware(container))
    dp.include_router(commands.router)
    dp.include_router(chat.router)

    async def on_startup() -> None:
        await set_default_commands(bot)
        scheduler.start()
        logger.info("Aura is up and running")

    async def on_shutdown() -> None:
        scheduler.shutdown()
        await db.close()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
