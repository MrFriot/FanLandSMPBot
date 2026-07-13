import unittest

from bot import reports

from .helpers import make_sessions, msk


class TestBar(unittest.TestCase):
    def test_scaling(self):
        self.assertEqual(reports.bar(0, 100), "")
        self.assertEqual(reports.bar(100, 0), "")
        self.assertEqual(reports.bar(100, 100), "▇" * 8)
        self.assertEqual(reports.bar(50, 100), "▇" * 4)
        self.assertEqual(reports.bar(1, 1000), "▇", "ненулевое значение видно всегда")


class TestSparkline(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(reports.sparkline([0, 0, 0]), "▁▁▁")
        # 0 — нижний уровень, максимум — верхний, ненулевой минимум заметен;
        # 350/700*7 = 3.5 округляется по-банковски до 4 -> "▅"
        self.assertEqual(reports.sparkline([0, 700, 350, 1]), "▁█▅▂")


class TestDailySeconds(unittest.TestCase):
    def test_split_across_midnight(self):
        # пятница 23:00 — суббота 01:00: по часу на каждый день
        spans = [(msk(2026, 7, 10, 23, 0), msk(2026, 7, 11, 1, 0))]
        rows = reports.daily_seconds(spans, now=msk(2026, 7, 12, 20, 0))

        totals = {day.isoformat(): seconds for day, seconds in rows}
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[-1][0].isoformat(), "2026-07-12", "сегодня — последним")
        self.assertEqual(totals["2026-07-10"], 3600)
        self.assertEqual(totals["2026-07-11"], 3600)
        self.assertEqual(totals["2026-07-12"], 0)

    def test_spans_outside_week_ignored(self):
        spans = [(msk(2026, 7, 1, 10, 0), msk(2026, 7, 1, 12, 0))]
        rows = reports.daily_seconds(spans, now=msk(2026, 7, 12, 20, 0))
        self.assertTrue(all(seconds == 0 for _, seconds in rows))


class TestHourlySeconds(unittest.TestCase):
    def test_split_across_hours(self):
        # 16:30–18:15 МСК: 30 мин в 16-й час, час в 17-й, 15 мин в 18-й
        spans = [(msk(2026, 7, 12, 16, 30), msk(2026, 7, 12, 18, 15))]
        hours = reports.hourly_seconds(spans)
        self.assertEqual(hours[16], 1800)
        self.assertEqual(hours[17], 3600)
        self.assertEqual(hours[18], 900)
        self.assertEqual(sum(hours), 6300)

    def test_accumulates_across_days(self):
        spans = [
            (msk(2026, 7, 11, 21, 0), msk(2026, 7, 11, 22, 0)),
            (msk(2026, 7, 12, 21, 0), msk(2026, 7, 12, 22, 0)),
        ]
        self.assertEqual(reports.hourly_seconds(spans)[21], 7200)


class TestUsualJoinHour(unittest.TestCase):
    def test_needs_enough_sessions(self):
        times = [msk(2026, 7, 12, 20, 0)] * 4
        self.assertIsNone(reports.usual_join_hour(times))

    def test_mode_hour(self):
        times = [
            msk(2026, 7, 8, 20, 10),
            msk(2026, 7, 9, 20, 45),
            msk(2026, 7, 10, 9, 0),
            msk(2026, 7, 11, 20, 30),
            msk(2026, 7, 12, 21, 0),
        ]
        self.assertEqual(reports.usual_join_hour(times), 20)


class TestPlayerProfile(unittest.TestCase):
    def setUp(self):
        self.sessions = make_sessions()

    def test_unknown_player(self):
        self.assertIsNone(reports.player_profile(self.sessions, "Nobody", now=100))

    def test_full_profile(self):
        self.sessions.open_session("Steve", at=msk(2026, 7, 10, 12, 0))
        self.sessions.close_session("Steve", at=msk(2026, 7, 10, 13, 0))
        self.sessions.open_session("Steve", at=msk(2026, 7, 12, 9, 0))
        self.sessions.close_session("Steve", at=msk(2026, 7, 12, 9, 30))

        profile = reports.player_profile(self.sessions, "Steve", now=msk(2026, 7, 12, 12, 0))
        self.assertEqual(
            profile,
            "⚪ Steve был на сервере сегодня в 09:30, сессия длилась 30 мин.\n"
            "\n"
            "Заходов: 2 · наиграно: 1 ч 30 мин\n"
            "За последние 7 дн: 1 ч 30 мин\n"
            "Средняя сессия: 45 мин · рекорд: 1 ч\n"
            "Доля всего онлайна сервера: 100%\n"
            "Впервые замечен: 10 июля в 12:00\n"
            "\n"
            "Последние сессии:\n"
            "• сегодня в 09:00 — 30 мин\n"
            "• 10 июля в 12:00 — 1 ч",
        )

    def test_online_share_usual_hour_and_open_session_line(self):
        # пять заходов Steve около 20:00, последняя сессия открыта
        for day in (7, 8, 9, 10):
            self.sessions.open_session("Steve", at=msk(2026, 7, day, 20, 0))
            self.sessions.close_session("Steve", at=msk(2026, 7, day, 20, 30))
        self.sessions.open_session("Steve", at=msk(2026, 7, 12, 20, 0))
        # Alex набирает столько же времени — доля Steve 50%
        self.sessions.open_session("Alex", at=msk(2026, 7, 11, 10, 0))
        self.sessions.close_session("Alex", at=msk(2026, 7, 11, 12, 30))

        now = msk(2026, 7, 12, 20, 30)
        profile = reports.player_profile(self.sessions, "Steve", now)
        self.assertIn("🟢 Steve сейчас на сервере, зашёл сегодня в 20:00.", profile)
        self.assertIn("Заходов: 5 · наиграно: 2 ч 30 мин", profile)
        self.assertIn("Доля всего онлайна сервера: 50%", profile)
        self.assertIn("Обычно заходит около 20:00", profile)
        self.assertIn("• сегодня в 20:00 — сейчас на сервере", profile)
        # ровно 5 последних сессий в списке
        self.assertEqual(profile.count("• "), 5)


class TestServerDashboard(unittest.TestCase):
    def setUp(self):
        self.sessions = make_sessions()

    def test_empty_history(self):
        self.assertEqual(
            reports.server_dashboard(self.sessions, days=7, now=100),
            "Пока нет ни одной записи об игроках.",
        )

    def test_full_dashboard(self):
        now = msk(2026, 7, 12, 20, 0)  # воскресенье
        self.sessions.open_session("Steve", at=msk(2026, 7, 12, 16, 0))
        self.sessions.close_session("Steve", at=msk(2026, 7, 12, 19, 0))
        self.sessions.open_session("Alex", at=msk(2026, 7, 12, 19, 30))
        self.sessions.open_session("Bob", at=msk(2026, 7, 10, 23, 0))
        self.sessions.close_session("Bob", at=msk(2026, 7, 11, 1, 0))

        self.assertEqual(
            reports.server_dashboard(self.sessions, days=7, now=now),
            "📊 Дашборд сервера за 7 дн\n"
            "\n"
            "Сейчас онлайн: 1\n"
            "Игроков: 3 · заходов: 3\n"
            "Наиграно: 5 ч 30 мин\n"
            "Пиковый онлайн: 1 (10 июля в 23:00)\n"
            "\n"
            "Топ-3:\n"
            "1. Steve — 3 ч\n"
            "2. Bob — 2 ч\n"
            "3. Alex — 30 мин\n"
            "\n"
            "Активность за 7 дней:\n"
            "пн —\n"
            "вт —\n"
            "ср —\n"
            "чт —\n"
            "пт ▇▇ 1 ч\n"
            "сб ▇▇ 1 ч\n"
            "вс ▇▇▇▇▇▇▇▇ 3 ч 30 мин\n"
            "\n"
            "По часам (МСК): █▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁███▅▁▁▁█\n"
            "Пик: 00:00–01:00\n"
            "\n"
            "За всё время: игроков 3 · наиграно 5 ч 30 мин\n"
            "Первая запись: 10 июля в 23:00",
        )

    def test_window_without_activity_has_no_charts(self):
        self.sessions.open_session("Old", at=msk(2026, 6, 1, 10, 0))
        self.sessions.close_session("Old", at=msk(2026, 6, 1, 12, 0))

        dashboard = reports.server_dashboard(self.sessions, days=7, now=msk(2026, 7, 12, 20, 0))
        self.assertIn("Игроков: 0 · заходов: 0", dashboard)
        self.assertNotIn("Топ-3", dashboard)
        self.assertNotIn("По часам", dashboard)
        self.assertIn("За всё время: игроков 1 · наиграно 2 ч", dashboard)


if __name__ == "__main__":
    unittest.main()
