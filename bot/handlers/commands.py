"""Обработчики команд бота.

Аргументы storage и monitor попадают в хендлеры через DI aiogram:
они переданы как kwargs в dp.start_polling() (см. main.py).
"""
import asyncio
import logging
import re
import time

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, Message

from .. import charts, reports, timefmt
from ..monitor import ServerMonitor
from ..sessions import SessionStorage
from ..storage import Subscriber, SubscriberStorage

router = Router()
logger = logging.getLogger(__name__)


def _now() -> int:
    """Текущее время; вынесено в функцию, чтобы подменять в тестах."""
    return int(time.time())

# ник Minecraft: латиница, цифры, подчёркивание
_NICK_RE = re.compile(r"^\w{1,16}$", re.ASCII)

_TRACK_USAGE = "\n\nДобавить: /track <ник> [ник2 ...] (регистр важен)\nУбрать: /untrack <ник>"


def _sub_key(message: Message) -> Subscriber:
    """Адрес подписки: чат + тема форума, из которой пришла команда."""
    thread_id = message.message_thread_id if message.is_topic_message else None
    return (message.chat.id, thread_id)


async def _answer(message: Message, text: str) -> None:
    """Ответ в ту же тему: aiogram сам подставляет message_thread_id в answer()."""
    await message.answer(text)


@router.message(CommandStart())
async def cmd_start(message: Message, storage: SubscriberStorage) -> None:
    if storage.add(_sub_key(message)):
        logger.info("Новая подписка на статус: %s", _sub_key(message))
        await _answer(
            message,
            "Подписка оформлена ✅\n"
            "Пришлю уведомление, когда сервер запустится или остановится.\n\n"
            "Команды:\n"
            "/status — текущее состояние сервера\n"
            "/track <ник> — следить за входом/выходом игрока\n"
            "/untrack <ник> — перестать следить\n"
            "/seen <ник> — профиль игрока\n"
            "/top [дней] — топ по времени в игре\n"
            "/stats [дней] — дашборд сервера\n"
            "/stop — отписаться от уведомлений о сервере",
        )
    else:
        await _answer(message, "Здесь уже есть подписка. /status — текущее состояние.")


@router.message(Command("stop"))
async def cmd_stop(message: Message, storage: SubscriberStorage) -> None:
    sub = _sub_key(message)
    if storage.remove(sub):
        logger.info("Отписка от статуса: %s", sub)
        text = "Подписка на статус сервера отменена."
        if storage.tracked_for(sub):
            text += "\nОтслеживание игроков осталось — список в /track."
        await _answer(message, text)
    else:
        await _answer(message, "Здесь подписки и не было 🙂")


@router.message(Command("status"))
async def cmd_status(message: Message, monitor: ServerMonitor) -> None:
    status = await monitor.get_status()
    if status is None:
        await _answer(message, "🔴 Сервер офлайн или недоступен.")
        return

    lines = [
        "✅ Сервер онлайн",
        f"Игроки: {status.players.online}/{status.players.max}",
    ]

    names = await monitor.get_player_names(status)
    if names:
        lines.append("Онлайн: " + ", ".join(names))

    lines.append(f"Пинг: {status.latency:.0f} мс")
    await _answer(message, "\n".join(lines))


@router.message(Command("track"))
async def cmd_track(
    message: Message,
    command: CommandObject,
    storage: SubscriberStorage,
    monitor: ServerMonitor,
) -> None:
    sub = _sub_key(message)

    if not command.args:
        tracked = storage.tracked_for(sub)
        if not tracked:
            await _answer(message, "Пока никто не отслеживается." + _TRACK_USAGE)
        else:
            await _answer(message, await _tracked_report(monitor, tracked))
        return

    added, already, invalid = [], [], []
    for name in command.args.split():
        if not _NICK_RE.match(name):
            invalid.append(name)
        elif storage.track(sub, name):
            added.append(name)
        else:
            already.append(name)

    if added:
        logger.info("В %s начали отслеживать: %s", sub, ", ".join(added))

    parts = []
    if added:
        parts.append("Теперь отслеживаю: " + ", ".join(added))
    if already:
        parts.append("Уже отслеживались: " + ", ".join(already))
    if invalid:
        parts.append("Не похоже на ник Minecraft: " + ", ".join(invalid))
    await _answer(message, "\n".join(parts))


async def _tracked_report(monitor: ServerMonitor, tracked: list[str]) -> str:
    """Список отслеживаемых ников с их текущим статусом."""
    status = await monitor.get_status()

    if status is not None:
        names = await monitor.get_player_names(status)
        if names is None:
            # сервер онлайн, но состав получить не удалось
            body = "\n".join(f"❔ {name}" for name in tracked)
            return "Отслеживаемые игроки (статус неизвестен — query не ответил):\n" + body + _TRACK_USAGE
        online = set(names)
        header = "Отслеживаемые игроки:"
    else:
        online = set()
        header = "Отслеживаемые игроки (сервер офлайн):"

    body = "\n".join(
        f"🟢 {name} — онлайн" if name in online else f"⚪ {name} — офлайн"
        for name in tracked
    )
    return header + "\n" + body + _TRACK_USAGE


@router.message(Command("untrack"))
async def cmd_untrack(message: Message, command: CommandObject, storage: SubscriberStorage) -> None:
    sub = _sub_key(message)

    if not command.args:
        await _answer(message, "Укажите ник: /untrack <ник> [ник2 ...]")
        return

    removed, missing = [], []
    for name in command.args.split():
        if storage.untrack(sub, name):
            removed.append(name)
        else:
            missing.append(name)

    if removed:
        logger.info("В %s перестали отслеживать: %s", sub, ", ".join(removed))

    parts = []
    if removed:
        parts.append("Больше не отслеживаю: " + ", ".join(removed))
    if missing:
        parts.append("И так не отслеживались: " + ", ".join(missing))
    await _answer(message, "\n".join(parts))


@router.message(Command("seen"))
async def cmd_seen(message: Message, command: CommandObject, sessions: SessionStorage) -> None:
    if not command.args:
        await _answer(message, "Укажите ник: /seen <ник> (регистр важен)")
        return

    name = command.args.split()[0]
    if not _NICK_RE.match(name):
        await _answer(message, "Не похоже на ник Minecraft: " + name)
        return

    profile = reports.player_profile(sessions, name, _now())
    if profile is None:
        await _answer(message, f"Не видел игрока {name} на сервере.")
        return
    await _answer(message, profile)


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, sessions: SessionStorage) -> None:
    days = 7
    if command.args:
        arg = command.args.split()[0]
        if not arg.isdigit() or not 1 <= int(arg) <= 365:
            await _answer(message, "Использование: /top [дней], число от 1 до 365. По умолчанию 7.")
            return
        days = int(arg)

    now = _now()
    top = sessions.top_playtime(since=now - days * 86400, until=now, limit=10)
    if not top:
        await _answer(message, f"За последние {days} дн на сервере никого не было.")
        return

    lines = [f"🏆 Топ по времени в игре за {days} дн:"]
    lines += [
        f"{place}. {name} — {timefmt.duration(seconds)}"
        for place, (name, seconds) in enumerate(top, start=1)
    ]
    await _answer(message, "\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject, sessions: SessionStorage) -> None:
    days = 7
    if command.args:
        arg = command.args.split()[0]
        if not arg.isdigit() or not 1 <= int(arg) <= 365:
            await _answer(message, "Использование: /stats [дней], число от 1 до 365. По умолчанию 7.")
            return
        days = int(arg)

    now = _now()
    # запросы к SQLite — только из потока, где создано соединение
    data = charts.collect(sessions, days, now)
    png = None
    if data is not None:
        try:
            # рендер CPU-bound и БД не трогает — уводим из event loop
            png = await asyncio.to_thread(charts.render, data)
        except Exception:
            logger.exception("Не удалось отрисовать дашборд, отвечаю текстом")

    if png is None:
        # истории ещё нет или рендер упал — текстовый дашборд
        await _answer(message, reports.server_dashboard(sessions, days, now))
        return

    await message.answer_photo(
        BufferedInputFile(png, filename="stats.png"),
        caption=f"📊 Дашборд сервера за {days} дн",
    )
