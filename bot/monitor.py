import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from mcstatus import JavaServer
from mcstatus.responses import JavaStatusResponse, QueryResponse

from .config import Config
from .sessions import SessionStorage
from .storage import Subscriber, SubscriberStorage

logger = logging.getLogger(__name__)


class ServerMonitor:
    """Фоновый цикл опроса Minecraft-сервера.

    Раз в check_interval секунд снимает статус и состав игроков,
    сравнивает с предыдущим состоянием и рассылает уведомления:
    - о запуске/остановке сервера — подписчикам /start;
    - о входе/выходе отслеживаемых игроков — чатам с /track
      (ники сравниваются строго, с учётом регистра).

    Помимо уведомлений ведёт историю сессий: каждый вход и выход
    любого игрока пишется в SessionStorage независимо от подписок.

    Состояние между тиками:
    - _online: True/False; None — ещё неизвестно (бот только запустился);
    - _players: последний известный состав; None — состав неизвестен,
      что не то же самое, что пустой сервер;
    - _fail_count: сервер объявляется офлайн только после fail_threshold
      неудачных проверок подряд — защита от единичных сетевых сбоев.
    """

    def __init__(
        self,
        bot: Bot,
        storage: SubscriberStorage,
        sessions: SessionStorage,
        config: Config,
    ):
        self._bot = bot
        self._storage = storage
        self._sessions = sessions
        self._cfg = config
        self._now = lambda: int(time.time())  # подменяется в тестах
        self._address = f"{config.mc_host}:{config.mc_port}"
        self._online: bool | None = None
        self._fail_count = 0
        self._players: set[str] | None = None

    # -- запросы к серверу -------------------------------------------------

    async def get_status(self) -> JavaStatusResponse | None:
        """Текущий статус сервера или None, если он недоступен."""
        try:
            server = await JavaServer.async_lookup(self._address)
            return await asyncio.wait_for(server.async_status(), timeout=10)
        except Exception:
            return None

    async def get_query(self) -> QueryResponse | None:
        """Данные query-протокола (полный список ников) или None.

        Требует enable-query=true в server.properties.
        """
        try:
            server = await JavaServer.async_lookup(self._address)
            return await asyncio.wait_for(server.async_query(), timeout=10)
        except Exception:
            return None

    async def get_player_names(self, status: JavaStatusResponse) -> list[str] | None:
        """Полный список ников онлайн-игроков.

        Основной источник — query; фолбэк — sample из status.
        None означает «данных нет» (это не то же самое, что пустой сервер).
        """
        query = await self.get_query()
        if query is not None:
            return query.players.list
        if status.players.online == 0:
            return []
        if status.players.sample is not None:
            return [p.name for p in status.players.sample]
        return None

    # -- основной цикл -------------------------------------------------------

    async def run(self) -> None:
        logger.info("Мониторинг %s запущен (интервал %s c)", self._address, self._cfg.check_interval)
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("Ошибка в цикле мониторинга")
            await asyncio.sleep(self._cfg.check_interval)

    async def _tick(self) -> None:
        status = await self.get_status()

        if status is not None:
            self._fail_count = 0
            if self._online is False:
                logger.info("Сервер запущен")
                await self._broadcast("✅ Сервер запущен!")
                # сервер только что поднялся: стартуем с пустого состава,
                # чтобы объявить вход каждого отслеживаемого игрока
                self._players = set()
            self._online = True
            await self._check_players(status)
            return

        self._fail_count += 1
        if self._fail_count >= self._cfg.fail_threshold and self._online is not False:
            if self._online is True:
                logger.info("Сервер остановлен (%s неудачных проверок подряд)", self._fail_count)
                await self._notify_shutdown()
                self._sessions.close_all(self._now())
            self._online = False
            self._players = None

    # -- отслеживание игроков -------------------------------------------------

    async def _check_players(self, status: JavaStatusResponse) -> None:
        names = await self.get_player_names(status)
        if names is None:
            # данных о составе нет (query временно недоступен) —
            # не считаем, что все вышли, просто ждём следующего тика
            return

        current = set(names)
        previous, self._players = self._players, current

        if previous is None:
            # бот только что запустился: запоминаем состав без уведомлений
            # и приводим открытые сессии в БД к реальности
            self._sessions.reconcile(current, self._now())
            logger.info("Состав игроков: %s", ", ".join(sorted(current)) or "никого")
            return

        joined = current - previous
        left = previous - current
        if joined or left:
            now = self._now()
            for name in joined:
                self._sessions.open_session(name, now)
            for name in left:
                self._sessions.close_session(name, now)
            logger.info(
                "Изменение состава — вход: %s; выход: %s",
                ", ".join(sorted(joined)) or "—",
                ", ".join(sorted(left)) or "—",
            )
            await self._notify_trackers(joined, left)

    async def _notify_trackers(self, joined: set[str], left: set[str]) -> None:
        for sub, tracked in self._storage.all_tracked().items():
            lines = [f"🎮 {name} зашёл на сервер" for name in sorted(joined & tracked)]
            lines += [f"🚪 {name} вышел с сервера" for name in sorted(left & tracked)]
            if lines:
                await self._send(sub, "\n".join(lines))

    async def _notify_shutdown(self) -> None:
        """Сервер остановился: одно сообщение на чат — статус + кто вышел."""
        last_players = self._players or set()
        status_subs = self._storage.all()
        tracked_map = self._storage.all_tracked()

        for sub in status_subs | tracked_map.keys():
            lines = []
            if sub in status_subs:
                lines.append("🔴 Сервер остановлен.")
            gone = sorted(last_players & tracked_map.get(sub, set()))
            if gone:
                verb = "вышел" if len(gone) == 1 else "вышли"
                lines.append(f"🚪 {', '.join(gone)} {verb} с сервера из-за его остановки.")
            if lines:
                await self._send(sub, "\n".join(lines))

    # -- отправка --------------------------------------------------------------

    async def _broadcast(self, text: str) -> None:
        for sub in self._storage.all():
            await self._send(sub, text)

    async def _send(self, sub: Subscriber, text: str) -> None:
        chat_id, thread_id = sub
        try:
            await self._bot.send_message(chat_id, text, message_thread_id=thread_id)
        except TelegramForbiddenError:
            # бота удалили из чата или заблокировали — чистим все подписки
            logger.info("Чат %s недоступен (forbidden), подписки удалены", sub)
            self._storage.drop(sub)
        except TelegramBadRequest as e:
            if "thread not found" in str(e).lower():
                # тему форума удалили — подписки больше не нужны
                logger.info("Тема %s удалена, подписки удалены", sub)
                self._storage.drop(sub)
            else:
                logger.exception("Не удалось отправить сообщение в %s", sub)
        except Exception:
            logger.exception("Не удалось отправить сообщение в %s", sub)
