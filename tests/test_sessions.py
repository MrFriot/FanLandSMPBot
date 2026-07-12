import sqlite3
import unittest

from bot.sessions import SessionStorage

from .helpers import make_sessions


class TestOpenClose(unittest.TestCase):
    def test_open_close(self):
        s = make_sessions()
        self.assertTrue(s.open_session("Steve", at=100))
        self.assertEqual(s.online_now(), {"Steve"})
        self.assertTrue(s.close_session("Steve", at=200))
        self.assertEqual(s.online_now(), set())

    def test_double_open_ignored(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        self.assertFalse(s.open_session("Steve", at=150), "вторая открытая сессия не создаётся")
        self.assertEqual(s.last_seen("Steve"), (100, None), "первая сессия не перезаписана")

    def test_close_without_open(self):
        s = make_sessions()
        self.assertFalse(s.close_session("Steve", at=100))

    def test_reopen_creates_new_session(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.close_session("Steve", at=200)
        self.assertTrue(s.open_session("Steve", at=300))
        self.assertEqual(s.last_seen("Steve"), (300, None))
        # обе сессии в истории: 100 + 50 секунд
        s.close_session("Steve", at=350)
        self.assertEqual(s.playtime("Steve", since=0, until=1000), 150)

    def test_names_are_case_sensitive(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        self.assertTrue(s.open_session("steve", at=100))
        self.assertEqual(s.online_now(), {"Steve", "steve"})
        s.close_session("steve", at=200)
        self.assertEqual(s.last_seen("Steve"), (100, None))


class TestCloseAll(unittest.TestCase):
    def test_closes_everything_and_reports_names(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.open_session("Alex", at=110)
        s.close_session("Alex", at=120)
        s.open_session("Zed", at=130)

        self.assertEqual(s.close_all(at=200), ["Steve", "Zed"])
        self.assertEqual(s.online_now(), set())
        self.assertEqual(s.last_seen("Steve"), (100, 200))
        self.assertEqual(s.last_seen("Alex"), (110, 120), "закрытые сессии не трогаются")

    def test_idempotent(self):
        s = make_sessions()
        self.assertEqual(s.close_all(at=100), [])


class TestReconcile(unittest.TestCase):
    def test_reconcile(self):
        s = make_sessions()
        s.open_session("Ghost", at=10)   # ушёл, пока бот был выключен
        s.open_session("Steve", at=10)   # так и сидит на сервере
        # Alex зашёл, пока бот был выключен

        s.reconcile({"Steve", "Alex"}, at=100)

        self.assertEqual(s.online_now(), {"Steve", "Alex"})
        self.assertEqual(s.last_seen("Ghost"), (10, 100), "пропавший закрыт временем сверки")
        self.assertEqual(s.last_seen("Steve"), (10, None), "живая сессия сохранена")
        self.assertEqual(s.last_seen("Alex"), (100, None))

    def test_reconcile_with_empty_server(self):
        s = make_sessions()
        s.open_session("Ghost", at=10)
        s.reconcile(set(), at=100)
        self.assertEqual(s.online_now(), set())


class TestQueries(unittest.TestCase):
    def test_last_seen_unknown_player(self):
        s = make_sessions()
        self.assertIsNone(s.last_seen("Nobody"))

    def test_last_seen_picks_latest(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.close_session("Steve", at=200)
        s.open_session("Steve", at=300)
        s.close_session("Steve", at=400)
        self.assertEqual(s.last_seen("Steve"), (300, 400))

    def test_playtime_clamps_to_window(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.close_session("Steve", at=200)

        self.assertEqual(s.playtime("Steve", since=0, until=1000), 100)
        self.assertEqual(s.playtime("Steve", since=150, until=1000), 50)
        self.assertEqual(s.playtime("Steve", since=0, until=150), 50)
        self.assertEqual(s.playtime("Steve", since=120, until=180), 60)
        self.assertEqual(s.playtime("Steve", since=500, until=1000), 0, "сессия вне окна")

    def test_playtime_open_session_counts_until_now(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        self.assertEqual(s.playtime("Steve", since=0, until=250), 150)

    def test_playtime_unknown_player(self):
        s = make_sessions()
        self.assertEqual(s.playtime("Nobody", since=0, until=100), 0)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.close_session("Steve", at=200)
        s.open_session("Alex", at=300)

        reloaded = SessionStorage(str(s._path))
        self.assertEqual(reloaded.online_now(), {"Alex"})
        self.assertEqual(reloaded.last_seen("Steve"), (100, 200))

    def test_open_session_unique_index_guards_db_level(self):
        """Даже прямой INSERT мимо API не создаст вторую открытую сессию."""
        s = make_sessions()
        s.open_session("Steve", at=100)
        with self.assertRaises(sqlite3.IntegrityError):
            with s._db:
                s._db.execute(
                    "INSERT INTO sessions (name, joined_at) VALUES (?, ?)", ("Steve", 150),
                )

    def test_close(self):
        s = make_sessions()
        s.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            s.online_now()


if __name__ == "__main__":
    unittest.main()


class TestTopPlaytime(unittest.TestCase):
    def test_orders_by_time_desc(self):
        s = make_sessions()
        s.open_session("Steve", at=0)
        s.close_session("Steve", at=3 * 3600)
        s.open_session("Alex", at=0)
        s.close_session("Alex", at=1800)

        top = s.top_playtime(since=0, until=10_000_000)
        self.assertEqual(top, [("Steve", 3 * 3600), ("Alex", 1800)])

    def test_tie_breaks_by_name(self):
        s = make_sessions()
        s.open_session("Steve", at=0)
        s.close_session("Steve", at=3600)
        s.open_session("Alex", at=100)
        s.close_session("Alex", at=3700)

        top = s.top_playtime(since=0, until=10_000)
        self.assertEqual(top, [("Alex", 3600), ("Steve", 3600)])

    def test_window_clamps_and_excludes_outside(self):
        s = make_sessions()
        s.open_session("Old", at=10)          # целиком до окна
        s.close_session("Old", at=500)
        s.open_session("Edge", at=800)        # наполовину в окне
        s.close_session("Edge", at=1100)

        top = s.top_playtime(since=1000, until=2000)
        self.assertEqual(top, [("Edge", 100)])

    def test_open_session_counts_until_end_of_window(self):
        s = make_sessions()
        s.open_session("Steve", at=1000)
        top = s.top_playtime(since=0, until=1000 + 3600)
        self.assertEqual(top, [("Steve", 3600)])

    def test_limit(self):
        s = make_sessions()
        for i in range(5):
            name = f"P{i}"
            s.open_session(name, at=0)
            s.close_session(name, at=100 * (i + 1))

        top = s.top_playtime(since=0, until=1000, limit=2)
        self.assertEqual(top, [("P4", 500), ("P3", 400)])


class TestPlayerStats(unittest.TestCase):
    def test_unknown_player(self):
        s = make_sessions()
        self.assertIsNone(s.player_stats("Nobody", now=100))

    def test_aggregates(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.close_session("Steve", at=700)     # 600 c
        s.open_session("Steve", at=1000)     # открыта, к now=1300 набегает 300 c

        stats = s.player_stats("Steve", now=1300)
        self.assertEqual(stats.first_seen, 100)
        self.assertEqual(stats.sessions_count, 2)
        self.assertEqual(stats.total_seconds, 900)
        self.assertEqual(stats.longest_seconds, 600)


class TestWindowStats(unittest.TestCase):
    def test_counts_and_clamping(self):
        s = make_sessions()
        s.open_session("Steve", at=100)
        s.close_session("Steve", at=700)
        s.open_session("Alex", at=900)       # открыта — до until
        s.open_session("Old", at=10)
        s.close_session("Old", at=50)        # целиком до окна

        stats = s.window_stats(since=400, until=1000)
        self.assertEqual(stats.unique_players, 2)
        self.assertEqual(stats.sessions, 2)
        # Steve: 700-400=300; Alex: 1000-900=100
        self.assertEqual(stats.total_seconds, 400)

    def test_empty_window(self):
        s = make_sessions()
        stats = s.window_stats(since=0, until=100)
        self.assertEqual(stats, type(stats)(unique_players=0, sessions=0, total_seconds=0))


class TestFirstRecord(unittest.TestCase):
    def test_first_record(self):
        s = make_sessions()
        self.assertIsNone(s.first_record())
        s.open_session("Alex", at=500)
        s.open_session("Steve", at=100)
        self.assertEqual(s.first_record(), 100)


class TestPeakOnline(unittest.TestCase):
    def test_peak_and_timestamp(self):
        s = make_sessions()
        s.open_session("A", at=100); s.close_session("A", at=200)
        s.open_session("B", at=150); s.close_session("B", at=300)
        s.open_session("C", at=180); s.close_session("C", at=190)

        self.assertEqual(s.peak_online(since=0, until=1000), (3, 180))

    def test_swap_at_same_moment_is_not_double_counted(self):
        s = make_sessions()
        s.open_session("A", at=0); s.close_session("A", at=100)
        s.open_session("B", at=100); s.close_session("B", at=200)

        self.assertEqual(s.peak_online(since=0, until=1000), (1, 0))

    def test_open_session_and_window_clamp(self):
        s = make_sessions()
        s.open_session("A", at=50)  # открыта; в окно попадает с since
        self.assertEqual(s.peak_online(since=100, until=500), (1, 100))

    def test_no_sessions_in_window(self):
        s = make_sessions()
        s.open_session("Old", at=10)
        s.close_session("Old", at=50)
        self.assertIsNone(s.peak_online(since=100, until=200))
        self.assertIsNone(make_sessions().peak_online(since=0, until=100))
