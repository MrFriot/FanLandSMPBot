"""Точка входа: сборка зависимостей и запуск long polling."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from .config import load_config
from .handlers.commands import router
from .monitor import ServerMonitor
from .sessions import SessionStorage
from .storage import SubscriberStorage


async def main() -> None:
    config = load_config()

    # Логи пишем в stdout, чтобы их показывал `docker compose logs`
    logging.basicConfig(
        level=config.log_level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    storage = SubscriberStorage(config.db_file)
    sessions = SessionStorage(config.db_file)
    monitor = ServerMonitor(bot, storage, sessions, config)

    monitor_task = asyncio.create_task(monitor.run())
    try:
        # зависимости прокидываются в хендлеры через DI aiogram 3
        await dp.start_polling(bot, storage=storage, monitor=monitor, sessions=sessions)
    finally:
        monitor_task.cancel()
        await bot.session.close()
        storage.close()
        sessions.close()


if __name__ == "__main__":
    asyncio.run(main())
