"""Фейки и утилиты, общие для всех тестов.

Тесты не ходят в сеть: Telegram подменяется FakeBot-ом,
а ответы Minecraft-сервера — методом set_server().
"""
import tempfile
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.config import Config
from bot.monitor import ServerMonitor
from bot.sessions import SessionStorage
from bot.storage import SubscriberStorage


class FakeBot:
    """Записывает отправленные сообщения и умеет имитировать мёртвые чаты."""

    def __init__(self):
        self.sent: list[tuple] = []       # (chat_id, thread_id, text)
        self.forbidden: set[int] = set()  # чаты, где бот заблокирован
        self.dead_threads: set[tuple] = set()  # (chat_id, thread_id) удалённых тем

    async def send_message(self, chat_id, text, message_thread_id=None):
        if chat_id in self.forbidden:
            raise TelegramForbiddenError(None, "Forbidden: bot was blocked by the user")
        if (chat_id, message_thread_id) in self.dead_threads:
            raise TelegramBadRequest(None, "Bad Request: message thread not found")
        self.sent.append((chat_id, message_thread_id, text))


class FakeSamplePlayer:
    def __init__(self, name):
        self.name = name


class FakePlayers:
    def __init__(self, online, maximum, sample):
        self.online = online
        self.max = maximum
        self.sample = sample


class FakeStatus:
    """Минимальный аналог JavaStatusResponse."""

    def __init__(self, online=0, maximum=8, sample=None, latency=42.0):
        self.players = FakePlayers(online, maximum, sample)
        self.latency = latency


class FakeQueryPlayers:
    def __init__(self, names):
        self.list = list(names)


class FakeQuery:
    """Минимальный аналог QueryResponse."""

    def __init__(self, names):
        self.players = FakeQueryPlayers(names)


class FakeChat:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    """Минимальный аналог aiogram.types.Message для вызова хендлеров."""

    def __init__(self, chat_id, thread_id=None):
        self.chat = FakeChat(chat_id)
        self.message_thread_id = thread_id
        self.is_topic_message = thread_id is not None
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


def make_db_path() -> str:
    return str(Path(tempfile.mkdtemp()) / "bot.db")


def make_storage(path: str | None = None) -> SubscriberStorage:
    return SubscriberStorage(path or make_db_path())


def make_sessions(path: str | None = None) -> SessionStorage:
    return SessionStorage(path or make_db_path())


def make_monitor(bot, storage, sessions, fail_threshold=2) -> ServerMonitor:
    cfg = Config(
        bot_token="test-token",
        mc_host="mc.test",
        mc_port=25565,
        check_interval=30,
        fail_threshold=fail_threshold,
        db_file="unused.db",
    )
    return ServerMonitor(bot, storage, sessions, cfg)


def set_server(monitor: ServerMonitor, *, status, names) -> None:
    """Подменяет ответы сервера для монитора.

    status — FakeStatus или None (сервер недоступен);
    names — список ников для query или None (query не отвечает).
    """
    async def get_status():
        return status

    async def get_query():
        return FakeQuery(names) if names is not None else None

    monitor.get_status = get_status
    monitor.get_query = get_query
