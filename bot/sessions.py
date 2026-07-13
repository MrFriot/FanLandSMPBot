"""История игровых сессий в SQLite.

Ведётся независимо от телеграм-подписок: монитор фиксирует вход и выход
каждого игрока, который появляется на сервере.

Модель данных: одна строка таблицы sessions — одна сессия.
- joined_at заполняется при входе, left_at — при выходе;
- left_at IS NULL означает «игрок сейчас на сервере»; уникальный
  частичный индекс не даёт открыть две сессии одного игрока;
- время — unix-секунды (UTC), форматирование — забота вызывающего кода;
- ники хранятся как есть, с учётом регистра.

Точность ограничена периодом опроса (CHECK_INTERVAL) и временем работы
бота: событие записывается в момент обнаружения. Пока бот выключен,
история не пишется — при старте reconcile() сверяет открытые сессии
с реальным составом и закрывает расхождения текущим временем.
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id        INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL,
    joined_at INTEGER NOT NULL,
    left_at   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sessions_name ON sessions (name);

-- не больше одной открытой сессии на игрока
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_open
    ON sessions (name) WHERE left_at IS NULL;
"""


@dataclass(frozen=True)
class PlayerStats:
    """Сводка по игроку за всё время наблюдений."""
    first_seen: int       # unix-время первого захода
    sessions_count: int
    total_seconds: int    # открытая сессия считается до now
    longest_seconds: int


@dataclass(frozen=True)
class WindowStats:
    """Сводка по серверу на отрезке времени."""
    unique_players: int
    sessions: int         # сессии, пересекающиеся с отрезком
    total_seconds: int


class SessionStorage:
    """Запись и выборка игровых сессий (та же БД, что и подписки)."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- запись ------------------------------------------------------------

    def open_session(self, name: str, at: int) -> bool:
        """Открывает сессию. False, если у игрока уже есть открытая."""
        with self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO sessions (name, joined_at)"
                " SELECT ?, ? WHERE NOT EXISTS"
                " (SELECT 1 FROM sessions WHERE name = ? AND left_at IS NULL)",
                (name, at, name),
            )
        return cur.rowcount > 0

    def close_session(self, name: str, at: int) -> bool:
        """Закрывает открытую сессию игрока. False, если открытой не было."""
        with self._db:
            cur = self._db.execute(
                "UPDATE sessions SET left_at = ? WHERE name = ? AND left_at IS NULL",
                (at, name),
            )
        return cur.rowcount > 0

    def close_all(self, at: int) -> list[str]:
        """Закрывает все открытые сессии (остановка сервера).

        Возвращает отсортированный список имён, чьи сессии были закрыты.
        """
        with self._db:
            names = [
                name for (name,) in self._db.execute(
                    "SELECT name FROM sessions WHERE left_at IS NULL",
                )
            ]
            self._db.execute(
                "UPDATE sessions SET left_at = ? WHERE left_at IS NULL", (at,),
            )
        return sorted(names)

    def reconcile(self, online: set[str], at: int) -> None:
        """Сверка после запуска бота: БД приводится к реальному составу.

        Открытые сессии игроков, которых на сервере нет, закрываются
        (моментом сверки); тем, кто на сервере без открытой сессии,
        сессия открывается. Уже открытые сессии игроков онлайн не
        трогаются — считаем, что игрок был на сервере всё это время.
        """
        current = self.online_now()
        for name in current - online:
            self.close_session(name, at)
        for name in online - current:
            self.open_session(name, at)

    # -- выборки -------------------------------------------------------------

    def online_now(self) -> set[str]:
        """Игроки с открытой сессией."""
        rows = self._db.execute("SELECT name FROM sessions WHERE left_at IS NULL")
        return {name for (name,) in rows}

    def last_seen(self, name: str) -> tuple[int, int | None] | None:
        """(joined_at, left_at) последней сессии игрока.

        left_at = None — игрок сейчас на сервере;
        None целиком — игрок ни разу не появлялся.
        """
        row = self._db.execute(
            "SELECT joined_at, left_at FROM sessions"
            " WHERE name = ? ORDER BY joined_at DESC, id DESC LIMIT 1",
            (name,),
        ).fetchone()
        return None if row is None else (row[0], row[1])

    def top_playtime(self, since: int, until: int, limit: int = 10) -> list[tuple[str, int]]:
        """Топ игроков по времени в игре на отрезке [since, until].

        Открытая сессия считается длящейся до until. Игроки, не игравшие
        в этом окне, в выдачу не попадают. Сортировка: по времени по
        убыванию, при равенстве — по имени.
        """
        rows = self._db.execute(
            """
            SELECT name,
                   SUM(MAX(0, MIN(COALESCE(left_at, :until), :until)
                            - MAX(joined_at, :since))) AS total
            FROM sessions
            GROUP BY name
            HAVING total > 0
            ORDER BY total DESC, name
            LIMIT :limit
            """,
            {"since": since, "until": until, "limit": limit},
        )
        return [(name, total) for name, total in rows]

    def player_stats(self, name: str, now: int) -> PlayerStats | None:
        """Сводка по игроку; None, если игрок ни разу не появлялся."""
        row = self._db.execute(
            "SELECT MIN(joined_at), COUNT(*),"
            " SUM(COALESCE(left_at, :now) - joined_at),"
            " MAX(COALESCE(left_at, :now) - joined_at)"
            " FROM sessions WHERE name = :name",
            {"name": name, "now": now},
        ).fetchone()
        if row[1] == 0:
            return None
        return PlayerStats(
            first_seen=row[0],
            sessions_count=row[1],
            total_seconds=row[2],
            longest_seconds=row[3],
        )

    def window_stats(self, since: int, until: int) -> WindowStats:
        """Сводка по всем игрокам на отрезке [since, until].

        Учитываются сессии, пересекающиеся с отрезком; их длительность
        обрезается по его границам, открытые считаются до until.
        """
        row = self._db.execute(
            """
            SELECT COUNT(DISTINCT name),
                   COUNT(*),
                   COALESCE(SUM(MAX(0, MIN(COALESCE(left_at, :until), :until)
                                       - MAX(joined_at, :since))), 0)
            FROM sessions
            WHERE joined_at < :until AND COALESCE(left_at, :until) > :since
            """,
            {"since": since, "until": until},
        ).fetchone()
        return WindowStats(unique_players=row[0], sessions=row[1], total_seconds=row[2])

    def first_record(self) -> int | None:
        """Время самого первого захода в истории; None, если история пуста."""
        row = self._db.execute("SELECT MIN(joined_at) FROM sessions").fetchone()
        return row[0]

    def spans_between(self, since: int, until: int) -> list[tuple[int, int]]:
        """Отрезки присутствия игроков, обрезанные по [since, until].

        Открытые сессии считаются до until. Имена не возвращаются —
        отрезки нужны для агрегатов: пиковый онлайн, активность по часам.
        """
        rows = self._db.execute(
            "SELECT MAX(joined_at, :since), MIN(COALESCE(left_at, :until), :until)"
            " FROM sessions"
            " WHERE joined_at < :until AND COALESCE(left_at, :until) > :since",
            {"since": since, "until": until},
        )
        return [(start, end) for start, end in rows if end > start]

    def recent_sessions(self, name: str, limit: int = 5) -> list[tuple[int, int | None]]:
        """Последние сессии игрока, новые первыми: (joined_at, left_at)."""
        rows = self._db.execute(
            "SELECT joined_at, left_at FROM sessions"
            " WHERE name = ? ORDER BY joined_at DESC, id DESC LIMIT ?",
            (name, limit),
        )
        return [(joined, left) for joined, left in rows]

    def join_times(self, name: str) -> list[int]:
        """Времена всех заходов игрока (для анализа привычек)."""
        rows = self._db.execute(
            "SELECT joined_at FROM sessions WHERE name = ? ORDER BY joined_at",
            (name,),
        )
        return [t for (t,) in rows]

    def peak_online(self, since: int, until: int) -> tuple[int, int] | None:
        """Пиковый одновременный онлайн на отрезке: (игроков, когда).

        None, если на отрезке не было ни одной сессии. При выходе и входе
        в один и тот же момент выход учитывается первым, чтобы «смена
        состава» в один тик не завышала пик.
        """
        events = []
        for start, end in self.spans_between(since, until):
            events.append((start, 1))
            events.append((end, -1))
        if not events:
            return None

        events.sort()  # при равном времени -1 идёт раньше +1
        current = peak = 0
        peak_at = events[0][0]
        for at, delta in events:
            current += delta
            if current > peak:
                peak, peak_at = current, at
        return peak, peak_at

    def playtime(self, name: str, since: int, until: int) -> int:
        """Суммарные секунды в игре на отрезке [since, until].

        Открытая сессия считается длящейся до until.
        """
        rows = self._db.execute(
            "SELECT joined_at, left_at FROM sessions WHERE name = ?", (name,),
        )
        total = 0
        for joined, left in rows:
            end = until if left is None else left
            total += max(0, min(end, until) - max(joined, since))
        return total
