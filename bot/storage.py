"""Хранилище подписок на SQLite (stdlib sqlite3)."""
import sqlite3
from pathlib import Path

# Адрес подписки: (chat_id, message_thread_id).
# thread_id = None для личек, обычных групп и темы General в форумах.
Subscriber = tuple[int, int | None]

# В SQLite NULL-ы внутри PRIMARY KEY считаются различными, поэтому
# «нет темы» храним не как NULL, а как 0 (реальные id тем Telegram >= 1).
_NO_THREAD = 0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    chat_id   INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    PRIMARY KEY (chat_id, thread_id)
);

CREATE TABLE IF NOT EXISTS tracked_players (
    chat_id   INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    name      TEXT    NOT NULL,  -- регистр значим (сравнение BINARY)
    PRIMARY KEY (chat_id, thread_id, name)
);
"""


class SubscriberStorage:
    """Подписки и отслеживаемые игроки в SQLite.

    Два независимых набора:
    - subscriptions: кому слать уведомления о запуске/остановке сервера;
    - tracked_players: какие ники отслеживает каждый чат/тема.

    Запросы синхронные: с WAL они выполняются за доли миллисекунды,
    и на масштабе этого бота выносить их из event loop незачем.
    При росте нагрузки класс заменяется на aiosqlite/Postgres,
    интерфейс останется тем же.
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- подписка на статус сервера ------------------------------------------

    def add(self, sub: Subscriber) -> bool:
        """Возвращает False, если подписка уже была."""
        with self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO subscriptions (chat_id, thread_id) VALUES (?, ?)",
                self._encode(sub),
            )
        return cur.rowcount > 0

    def remove(self, sub: Subscriber) -> bool:
        with self._db:
            cur = self._db.execute(
                "DELETE FROM subscriptions WHERE chat_id = ? AND thread_id = ?",
                self._encode(sub),
            )
        return cur.rowcount > 0

    def all(self) -> set[Subscriber]:
        rows = self._db.execute("SELECT chat_id, thread_id FROM subscriptions")
        return {self._decode(chat_id, thread_id) for chat_id, thread_id in rows}

    # -- отслеживание игроков --------------------------------------------------

    def track(self, sub: Subscriber, name: str) -> bool:
        """Возвращает False, если этот ник здесь уже отслеживается."""
        with self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO tracked_players (chat_id, thread_id, name)"
                " VALUES (?, ?, ?)",
                (*self._encode(sub), name),
            )
        return cur.rowcount > 0

    def untrack(self, sub: Subscriber, name: str) -> bool:
        with self._db:
            cur = self._db.execute(
                "DELETE FROM tracked_players"
                " WHERE chat_id = ? AND thread_id = ? AND name = ?",
                (*self._encode(sub), name),
            )
        return cur.rowcount > 0

    def tracked_for(self, sub: Subscriber) -> list[str]:
        """Ники, отслеживаемые в этом чате/теме."""
        rows = self._db.execute(
            "SELECT name FROM tracked_players"
            " WHERE chat_id = ? AND thread_id = ? ORDER BY name",
            self._encode(sub),
        )
        return [name for (name,) in rows]

    def all_tracked(self) -> dict[Subscriber, set[str]]:
        """Все подписки на игроков: подписка -> набор ников."""
        result: dict[Subscriber, set[str]] = {}
        rows = self._db.execute("SELECT chat_id, thread_id, name FROM tracked_players")
        for chat_id, thread_id, name in rows:
            result.setdefault(self._decode(chat_id, thread_id), set()).add(name)
        return result

    # -- очистка -----------------------------------------------------------------

    def drop(self, sub: Subscriber) -> None:
        """Полностью забыть чат/тему (бот удалён из чата, тема удалена)."""
        key = self._encode(sub)
        with self._db:  # оба удаления в одной транзакции
            self._db.execute(
                "DELETE FROM subscriptions WHERE chat_id = ? AND thread_id = ?", key,
            )
            self._db.execute(
                "DELETE FROM tracked_players WHERE chat_id = ? AND thread_id = ?", key,
            )

    # -- кодирование thread_id ------------------------------------------------------

    @staticmethod
    def _encode(sub: Subscriber) -> tuple[int, int]:
        chat_id, thread_id = sub
        return chat_id, _NO_THREAD if thread_id is None else thread_id

    @staticmethod
    def _decode(chat_id: int, thread_id: int) -> Subscriber:
        return chat_id, None if thread_id == _NO_THREAD else thread_id
