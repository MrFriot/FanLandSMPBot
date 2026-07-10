import sqlite3
import unittest

from bot.storage import SubscriberStorage

from .helpers import make_storage


class TestSubscribers(unittest.TestCase):
    def test_add_remove(self):
        st = make_storage()
        self.assertTrue(st.add((1, None)))
        self.assertFalse(st.add((1, None)), "повторная подписка не создаётся")
        self.assertEqual(st.all(), {(1, None)})
        self.assertTrue(st.remove((1, None)))
        self.assertFalse(st.remove((1, None)))

    def test_topics_are_independent(self):
        st = make_storage()
        st.add((1, 10))
        st.add((1, 20))
        self.assertEqual(st.all(), {(1, 10), (1, 20)})


class TestTracking(unittest.TestCase):
    def test_track_untrack(self):
        st = make_storage()
        self.assertTrue(st.track((1, None), "Steve"))
        self.assertFalse(st.track((1, None), "Steve"), "дубликат не добавляется")
        self.assertTrue(st.untrack((1, None), "Steve"))
        self.assertFalse(st.untrack((1, None), "Steve"))

    def test_case_sensitive(self):
        st = make_storage()
        st.track((1, None), "Steve")
        self.assertTrue(st.track((1, None), "steve"), "регистр различается")
        self.assertFalse(st.untrack((1, None), "STEVE"))
        self.assertEqual(st.tracked_for((1, None)), ["Steve", "steve"])

    def test_tracking_is_per_topic(self):
        st = make_storage()
        st.track((1, 10), "Steve")
        st.track((1, 20), "Alex")
        self.assertEqual(st.all_tracked(), {(1, 10): {"Steve"}, (1, 20): {"Alex"}})

    def test_tracked_for_is_sorted(self):
        st = make_storage()
        for name in ("zed", "Alex", "Steve"):
            st.track((1, None), name)
        self.assertEqual(st.tracked_for((1, None)), ["Alex", "Steve", "zed"])


class TestPersistence(unittest.TestCase):
    def test_reload_from_disk(self):
        st = make_storage()
        st.add((1, None))
        st.add((2, 5))
        st.track((2, 5), "Steve")

        reloaded = SubscriberStorage(str(st._path))
        self.assertEqual(reloaded.all(), {(1, None), (2, 5)})
        self.assertEqual(reloaded.all_tracked(), {(2, 5): {"Steve"}})

    def test_drop_clears_everything(self):
        st = make_storage()
        st.add((1, 5))
        st.track((1, 5), "Steve")
        st.drop((1, 5))

        self.assertEqual(st.all(), set())
        self.assertEqual(st.all_tracked(), {})
        reloaded = SubscriberStorage(str(st._path))
        self.assertEqual(reloaded.all(), set())
        self.assertEqual(reloaded.all_tracked(), {})


class TestSQLiteSpecifics(unittest.TestCase):
    def test_none_thread_deduplicated_across_reopen(self):
        """Регресс на квирк SQLite: NULL-ы в PRIMARY KEY не дедуплицируются.

        Поэтому «нет темы» хранится как 0, и повторный /start в личке
        не должен создавать вторую строку — даже после переоткрытия БД.
        """
        st = make_storage()
        self.assertTrue(st.add((1, None)))
        self.assertFalse(st.add((1, None)))

        reloaded = SubscriberStorage(str(st._path))
        self.assertFalse(reloaded.add((1, None)))
        self.assertEqual(reloaded.all(), {(1, None)})

    def test_thread_id_roundtrip(self):
        """None и настоящие id тем не перепутываются при кодировании."""
        st = make_storage()
        st.add((1, None))
        st.add((1, 7))
        st.track((2, None), "Steve")
        st.track((2, 7), "Alex")

        reloaded = SubscriberStorage(str(st._path))
        self.assertEqual(reloaded.all(), {(1, None), (1, 7)})
        self.assertEqual(
            reloaded.all_tracked(), {(2, None): {"Steve"}, (2, 7): {"Alex"}},
        )

    def test_no_null_thread_ids_in_db(self):
        st = make_storage()
        st.add((1, None))
        st.track((1, None), "Steve")

        rows = st._db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE thread_id IS NULL",
        ).fetchone()
        self.assertEqual(rows[0], 0)
        rows = st._db.execute(
            "SELECT COUNT(*) FROM tracked_players WHERE thread_id IS NULL",
        ).fetchone()
        self.assertEqual(rows[0], 0)

    def test_drop_unknown_sub_is_noop(self):
        st = make_storage()
        st.add((1, None))
        st.drop((999, 42))  # не должно падать и не должно ничего задеть
        self.assertEqual(st.all(), {(1, None)})

    def test_close(self):
        st = make_storage()
        st.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            st.all()


if __name__ == "__main__":
    unittest.main()
