import unittest

from aiogram.filters import CommandObject

from bot.handlers import commands

from .helpers import FakeBot, FakeMessage, FakeStatus, make_monitor, make_sessions, make_storage, set_server


class CommandsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = make_storage()
        self.monitor = make_monitor(FakeBot(), self.storage, make_sessions())


class TestStartStop(CommandsTestCase):
    async def test_start_in_topic_and_duplicate(self):
        msg = FakeMessage(100, thread_id=5)
        await commands.cmd_start(msg, self.storage)
        self.assertIn((100, 5), self.storage.all())

        await commands.cmd_start(msg, self.storage)
        self.assertIn("уже", msg.answers[-1])

    async def test_start_in_private_chat(self):
        msg = FakeMessage(200)
        await commands.cmd_start(msg, self.storage)
        self.assertIn((200, None), self.storage.all())

    async def test_stop_keeps_tracking(self):
        self.storage.add((100, 5))
        self.storage.track((100, 5), "Steve")
        msg = FakeMessage(100, thread_id=5)

        await commands.cmd_stop(msg, self.storage)
        self.assertNotIn((100, 5), self.storage.all())
        self.assertEqual(self.storage.all_tracked()[(100, 5)], {"Steve"})
        self.assertIn("Отслеживание игроков осталось", msg.answers[-1])

    async def test_stop_without_subscription(self):
        msg = FakeMessage(100)
        await commands.cmd_stop(msg, self.storage)
        self.assertIn("не было", msg.answers[-1])


class TestTrack(CommandsTestCase):
    async def test_add_duplicate_invalid(self):
        msg = FakeMessage(100, thread_id=5)
        await commands.cmd_track(
            msg, CommandObject(args="Steve alex_2 Steve плохой-ник"), self.storage, self.monitor,
        )
        answer = msg.answers[-1]
        self.assertIn("Теперь отслеживаю: Steve, alex_2", answer)
        self.assertIn("Уже отслеживались: Steve", answer)
        self.assertIn("Не похоже на ник Minecraft: плохой-ник", answer)
        self.assertEqual(self.storage.all_tracked()[(100, 5)], {"Steve", "alex_2"})

    async def test_list_with_statuses(self):
        self.storage.track((100, None), "Steve")
        self.storage.track((100, None), "Alex")
        msg = FakeMessage(100)

        set_server(self.monitor, status=FakeStatus(online=1), names=["Steve"])
        await commands.cmd_track(msg, CommandObject(), self.storage, self.monitor)
        self.assertIn("🟢 Steve — онлайн", msg.answers[-1])
        self.assertIn("⚪ Alex — офлайн", msg.answers[-1])

    async def test_list_when_server_offline(self):
        self.storage.track((100, None), "Steve")
        msg = FakeMessage(100)

        set_server(self.monitor, status=None, names=None)
        await commands.cmd_track(msg, CommandObject(), self.storage, self.monitor)
        self.assertIn("сервер офлайн", msg.answers[-1])
        self.assertIn("⚪ Steve — офлайн", msg.answers[-1])

    async def test_list_when_roster_unknown(self):
        self.storage.track((100, None), "Steve")
        msg = FakeMessage(100)

        set_server(self.monitor, status=FakeStatus(online=1, sample=None), names=None)
        await commands.cmd_track(msg, CommandObject(), self.storage, self.monitor)
        self.assertIn("статус неизвестен", msg.answers[-1])
        self.assertIn("❔ Steve", msg.answers[-1])

    async def test_list_when_nothing_tracked(self):
        msg = FakeMessage(100)
        await commands.cmd_track(msg, CommandObject(), self.storage, self.monitor)
        self.assertIn("Пока никто не отслеживается", msg.answers[-1])

    async def test_untrack(self):
        self.storage.track((100, None), "Steve")
        msg = FakeMessage(100)

        await commands.cmd_untrack(msg, CommandObject(args="Steve Ghost"), self.storage)
        answer = msg.answers[-1]
        self.assertIn("Больше не отслеживаю: Steve", answer)
        self.assertIn("И так не отслеживались: Ghost", answer)
        self.assertEqual(self.storage.all_tracked(), {})


class TestStatus(CommandsTestCase):
    async def test_online(self):
        msg = FakeMessage(100)
        set_server(self.monitor, status=FakeStatus(online=2, maximum=8, latency=37.4), names=["A", "B"])
        await commands.cmd_status(msg, self.monitor)
        answer = msg.answers[-1]
        self.assertIn("✅ Сервер онлайн", answer)
        self.assertIn("Игроки: 2/8", answer)
        self.assertIn("Онлайн: A, B", answer)
        self.assertIn("Пинг: 37 мс", answer)

    async def test_online_without_names(self):
        msg = FakeMessage(100)
        set_server(self.monitor, status=FakeStatus(online=0), names=[])
        await commands.cmd_status(msg, self.monitor)
        self.assertNotIn("Онлайн:", msg.answers[-1])

    async def test_offline(self):
        msg = FakeMessage(100)
        set_server(self.monitor, status=None, names=None)
        await commands.cmd_status(msg, self.monitor)
        self.assertIn("офлайн", msg.answers[-1])


if __name__ == "__main__":
    unittest.main()


class SessionsCommandsTestCase(CommandsTestCase):
    """База для команд, читающих историю сессий, с заморозкой времени."""

    def setUp(self):
        super().setUp()
        self.sessions = make_sessions()

    def freeze_now(self, value: int):
        original = commands._now
        commands._now = lambda: value
        self.addCleanup(setattr, commands, "_now", original)


class TestSeen(SessionsCommandsTestCase):
    async def test_usage_and_invalid_nick(self):
        msg = FakeMessage(1)
        await commands.cmd_seen(msg, CommandObject(), self.sessions)
        self.assertIn("Укажите ник", msg.answers[-1])

        await commands.cmd_seen(msg, CommandObject(args="плохой-ник"), self.sessions)
        self.assertIn("Не похоже на ник", msg.answers[-1])

    async def test_unknown_player(self):
        msg = FakeMessage(1)
        await commands.cmd_seen(msg, CommandObject(args="Nobody"), self.sessions)
        self.assertEqual(msg.answers[-1], "Не видел игрока Nobody на сервере.")

    async def test_player_online_now(self):
        self.sessions.open_session("Steve", at=1000)
        self.freeze_now(1000 + 3600)

        msg = FakeMessage(1)
        await commands.cmd_seen(msg, CommandObject(args="Steve"), self.sessions)
        self.assertEqual(
            msg.answers[-1],
            "🟢 Steve сейчас на сервере, зашёл 1 ч назад.",
        )

    async def test_player_offline(self):
        self.sessions.open_session("Steve", at=1000)
        self.sessions.close_session("Steve", at=1000 + 1800)
        self.freeze_now(1000 + 1800 + 2 * 3600)

        msg = FakeMessage(1)
        await commands.cmd_seen(msg, CommandObject(args="Steve"), self.sessions)
        self.assertEqual(
            msg.answers[-1],
            "⚪ Steve был на сервере 2 ч назад, сессия длилась 30 мин.",
        )

    async def test_seen_is_case_sensitive(self):
        self.sessions.open_session("Steve", at=1000)
        msg = FakeMessage(1)
        await commands.cmd_seen(msg, CommandObject(args="steve"), self.sessions)
        self.assertIn("Не видел игрока steve", msg.answers[-1])


class TestTop(SessionsCommandsTestCase):
    NOW = 1_000_000

    def seed(self):
        # Steve: 3 часа за последние сутки; Alex: 30 минут; Old: за пределами недели
        self.sessions.open_session("Steve", at=self.NOW - 4 * 3600)
        self.sessions.close_session("Steve", at=self.NOW - 3600)
        self.sessions.open_session("Alex", at=self.NOW - 1800)
        self.sessions.open_session("Old", at=self.NOW - 30 * 86400)
        self.sessions.close_session("Old", at=self.NOW - 29 * 86400)
        self.freeze_now(self.NOW)

    async def test_default_week(self):
        self.seed()
        msg = FakeMessage(1)
        await commands.cmd_top(msg, CommandObject(), self.sessions)
        self.assertEqual(
            msg.answers[-1],
            "🏆 Топ по времени в игре за 7 дн:\n"
            "1. Steve — 3 ч\n"
            "2. Alex — 30 мин",
        )

    async def test_wider_window_includes_old_player(self):
        self.seed()
        msg = FakeMessage(1)
        await commands.cmd_top(msg, CommandObject(args="60"), self.sessions)
        answer = msg.answers[-1]
        self.assertIn("за 60 дн", answer)
        self.assertIn("Old — 1 дн", answer)

    async def test_invalid_argument(self):
        self.freeze_now(self.NOW)
        msg = FakeMessage(1)
        for bad in ("abc", "0", "9999"):
            await commands.cmd_top(msg, CommandObject(args=bad), self.sessions)
            self.assertIn("Использование: /top", msg.answers[-1])

    async def test_empty_period(self):
        self.freeze_now(self.NOW)
        msg = FakeMessage(1)
        await commands.cmd_top(msg, CommandObject(), self.sessions)
        self.assertEqual(msg.answers[-1], "За последние 7 дн на сервере никого не было.")
