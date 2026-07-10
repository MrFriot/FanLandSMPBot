import unittest

from .helpers import (
    FakeBot,
    FakeSamplePlayer,
    FakeStatus,
    make_db_path,
    make_monitor,
    make_sessions,
    make_storage,
    set_server,
)


class MonitorTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = FakeBot()
        # подписки и сессии живут в одном файле БД, как в проде
        db_path = make_db_path()
        self.storage = make_storage(db_path)
        self.sessions = make_sessions(db_path)

    def make(self, **kwargs):
        return make_monitor(self.bot, self.storage, self.sessions, **kwargs)


class TestServerStatusNotifications(MonitorTestCase):
    async def test_first_tick_is_silent(self):
        """Бот запустился при работающем сервере — рассылки нет."""
        self.storage.add((1, None))
        mon = self.make()
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(mon._players, {"Steve"})

    async def test_single_failure_below_threshold_is_silent(self):
        self.storage.add((1, None))
        mon = self.make(fail_threshold=2)
        set_server(mon, status=FakeStatus(), names=[])
        await mon._tick()

        set_server(mon, status=None, names=None)
        await mon._tick()
        self.assertEqual(self.bot.sent, [])

    async def test_stop_and_start_notifications(self):
        self.storage.add((1, None))
        mon = self.make(fail_threshold=2)
        set_server(mon, status=FakeStatus(), names=[])
        await mon._tick()

        set_server(mon, status=None, names=None)
        await mon._tick()
        await mon._tick()
        self.assertEqual(self.bot.sent, [(1, None, "🔴 Сервер остановлен.")])

        # длительный офлайн не дублирует уведомление
        await mon._tick()
        self.assertEqual(len(self.bot.sent), 1)

        set_server(mon, status=FakeStatus(), names=[])
        await mon._tick()
        self.assertIn((1, None, "✅ Сервер запущен!"), self.bot.sent)

    async def test_offline_on_bot_start_is_silent(self):
        """Бот запустился при лежащем сервере — «остановлен» не рассылается."""
        self.storage.add((1, None))
        mon = self.make(fail_threshold=1)
        set_server(mon, status=None, names=None)
        await mon._tick()
        self.assertEqual(self.bot.sent, [])
        self.assertIs(mon._online, False)


class TestPlayerTracking(MonitorTestCase):
    async def test_join_and_leave(self):
        self.storage.track((2, 10), "Steve")
        self.storage.track((2, 10), "Alex")
        mon = self.make()
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        set_server(mon, status=FakeStatus(online=2), names=["Steve", "Alex"])
        await mon._tick()
        self.assertEqual(self.bot.sent, [(2, 10, "🎮 Alex зашёл на сервер")])
        self.bot.sent.clear()

        set_server(mon, status=FakeStatus(online=1), names=["Alex"])
        await mon._tick()
        self.assertEqual(self.bot.sent, [(2, 10, "🚪 Steve вышел с сервера")])

    async def test_tracking_is_case_sensitive(self):
        self.storage.track((3, None), "steve")
        mon = self.make()
        set_server(mon, status=FakeStatus(), names=[])
        await mon._tick()

        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()
        self.assertEqual(self.bot.sent, [], "«steve» не совпадает со «Steve»")

    async def test_query_outage_does_not_fake_leaves(self):
        self.storage.track((2, None), "Steve")
        mon = self.make()
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        # query замолчал, sample нет — состав «неизвестен», а не пуст
        set_server(mon, status=FakeStatus(online=1, sample=None), names=None)
        await mon._tick()
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(mon._players, {"Steve"})

    async def test_events_in_one_tick_are_batched(self):
        self.storage.track((2, None), "Steve")
        self.storage.track((2, None), "Alex")
        mon = self.make()
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        set_server(mon, status=FakeStatus(online=1), names=["Alex"])
        await mon._tick()
        self.assertEqual(
            self.bot.sent,
            [(2, None, "🎮 Alex зашёл на сервер\n🚪 Steve вышел с сервера")],
        )


class TestShutdownReport(MonitorTestCase):
    async def _run_shutdown(self, mon):
        set_server(mon, status=None, names=None)
        await mon._tick()
        await mon._tick()

    async def test_merged_message_and_isolation(self):
        # A — только статус; B — статус + трекинг; C — трекинг игрока не онлайн
        self.storage.add((1, None))
        self.storage.add((2, 10))
        self.storage.track((2, 10), "Alex")
        self.storage.track((3, None), "Ghost")
        mon = self.make(fail_threshold=2)
        set_server(mon, status=FakeStatus(online=1), names=["Alex"])
        await mon._tick()

        await self._run_shutdown(mon)
        self.assertEqual(sorted(self.bot.sent), [
            (1, None, "🔴 Сервер остановлен."),
            (2, 10, "🔴 Сервер остановлен.\n🚪 Alex вышел с сервера из-за его остановки."),
        ])
        self.assertIsNone(mon._players)

    async def test_plural_and_tracking_only_chat(self):
        self.storage.track((5, None), "Alex")
        self.storage.track((5, None), "Steve")
        mon = self.make(fail_threshold=2)
        set_server(mon, status=FakeStatus(online=2), names=["Alex", "Steve"])
        await mon._tick()

        await self._run_shutdown(mon)
        self.assertEqual(
            self.bot.sent,
            [(5, None, "🚪 Alex, Steve вышли с сервера из-за его остановки.")],
        )

    async def test_rejoin_after_restart_is_announced(self):
        self.storage.track((5, None), "Alex")
        mon = self.make(fail_threshold=2)
        set_server(mon, status=FakeStatus(online=1), names=["Alex"])
        await mon._tick()
        await self._run_shutdown(mon)
        self.bot.sent.clear()

        set_server(mon, status=FakeStatus(online=1), names=["Alex"])
        await mon._tick()
        self.assertEqual(self.bot.sent, [(5, None, "🎮 Alex зашёл на сервер")])


class TestDeadChatCleanup(MonitorTestCase):
    async def test_forbidden_and_deleted_thread(self):
        self.storage.add((1, None))
        self.storage.add((2, 10))
        self.storage.track((2, 10), "Steve")
        self.storage.track((3, 7), "Steve")
        self.bot.forbidden.add(2)
        self.bot.dead_threads.add((3, 7))
        mon = self.make()

        set_server(mon, status=FakeStatus(), names=[])
        await mon._tick()
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        self.assertNotIn((2, 10), self.storage.all())
        self.assertNotIn((2, 10), self.storage.all_tracked())
        self.assertNotIn((3, 7), self.storage.all_tracked())
        self.assertIn((1, None), self.storage.all())


class TestGetPlayerNames(MonitorTestCase):
    async def test_sources_and_fallbacks(self):
        mon = self.make()

        set_server(mon, status=None, names=["A", "B"])
        self.assertEqual(await mon.get_player_names(FakeStatus(online=2)), ["A", "B"])

        set_server(mon, status=None, names=None)
        self.assertEqual(
            await mon.get_player_names(FakeStatus(online=0)), [],
            "0 игроков — состав известен и пуст",
        )

        sample = [FakeSamplePlayer("A"), FakeSamplePlayer("B")]
        self.assertEqual(
            await mon.get_player_names(FakeStatus(online=2, sample=sample)), ["A", "B"],
        )

        self.assertIsNone(
            await mon.get_player_names(FakeStatus(online=2, sample=None)),
            "нет ни query, ни sample — состав неизвестен",
        )


if __name__ == "__main__":
    unittest.main()


class TestSessionRecording(MonitorTestCase):
    """Запись истории входов/выходов — независимо от телеграм-подписок."""

    async def test_records_all_players_without_subscriptions(self):
        mon = self.make()
        mon._now = lambda: 100
        set_server(mon, status=FakeStatus(), names=[])
        await mon._tick()

        mon._now = lambda: 200
        set_server(mon, status=FakeStatus(online=2), names=["Steve", "Alex"]) 
        await mon._tick()
        self.assertEqual(self.sessions.online_now(), {"Steve", "Alex"})
        self.assertEqual(self.sessions.last_seen("Steve"), (200, None))

        mon._now = lambda: 500
        set_server(mon, status=FakeStatus(online=1), names=["Alex"])
        await mon._tick()
        self.assertEqual(self.sessions.last_seen("Steve"), (200, 500))
        self.assertEqual(self.sessions.online_now(), {"Alex"})
        self.assertEqual(self.bot.sent, [], "подписок нет — запись всё равно ведётся")

    async def test_first_fetch_reconciles_stale_sessions(self):
        # бот был выключен: Ghost «завис» открытым, Steve реально на сервере
        self.sessions.open_session("Ghost", at=10)
        self.sessions.open_session("Steve", at=10)

        mon = self.make()
        mon._now = lambda: 100
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        self.assertEqual(self.sessions.online_now(), {"Steve"})
        self.assertEqual(self.sessions.last_seen("Ghost"), (10, 100))
        self.assertEqual(self.sessions.last_seen("Steve"), (10, None), "живая сессия не пересоздана")

    async def test_shutdown_closes_open_sessions(self):
        mon = self.make(fail_threshold=2)
        mon._now = lambda: 100
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        mon._now = lambda: 300
        set_server(mon, status=None, names=None)
        await mon._tick()
        await mon._tick()

        self.assertEqual(self.sessions.online_now(), set())
        self.assertEqual(self.sessions.last_seen("Steve"), (100, 300))

    async def test_restart_opens_fresh_session(self):
        mon = self.make(fail_threshold=1)
        mon._now = lambda: 100
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        mon._now = lambda: 200
        set_server(mon, status=None, names=None)
        await mon._tick()

        mon._now = lambda: 300
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        self.assertEqual(self.sessions.last_seen("Steve"), (300, None))
        self.assertEqual(self.sessions.playtime("Steve", since=0, until=400), 200)

    async def test_query_outage_keeps_sessions_intact(self):
        mon = self.make()
        mon._now = lambda: 100
        set_server(mon, status=FakeStatus(online=1), names=["Steve"])
        await mon._tick()

        mon._now = lambda: 200
        set_server(mon, status=FakeStatus(online=1, sample=None), names=None)
        await mon._tick()
        self.assertEqual(self.sessions.online_now(), {"Steve"})
        self.assertEqual(self.sessions.last_seen("Steve"), (100, None))
