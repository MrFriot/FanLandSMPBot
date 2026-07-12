import unittest
from datetime import datetime, timezone

from bot import timefmt

from .helpers import msk


class TestDuration(unittest.TestCase):
    def test_formats(self):
        cases = [
            (0, "< 1 мин"),
            (59, "< 1 мин"),
            (60, "1 мин"),
            (45 * 60, "45 мин"),
            (3600, "1 ч"),
            (2 * 3600 + 15 * 60, "2 ч 15 мин"),
            (86400, "1 дн"),
            (86400 + 3600, "1 дн 1 ч"),
            (3 * 86400, "3 дн"),
            # минуты опускаются, когда счёт идёт на дни
            (2 * 86400 + 5 * 3600 + 7 * 60, "2 дн 5 ч"),
        ]
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(timefmt.duration(seconds), expected)


class TestMoment(unittest.TestCase):
    NOW = msk(2026, 7, 12, 15, 0)

    def test_formats(self):
        cases = [
            (msk(2026, 7, 12, 9, 5), "сегодня в 09:05"),
            (msk(2026, 7, 12, 0, 30), "сегодня в 00:30"),
            (msk(2026, 7, 11, 23, 59), "вчера в 23:59"),
            (msk(2026, 7, 5, 22, 3), "5 июля в 22:03"),
            (msk(2026, 1, 1, 0, 0), "1 января в 00:00"),
            (msk(2025, 12, 31, 10, 0), "31 декабря 2025 в 10:00"),
        ]
        for ts, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(timefmt.moment(ts, self.NOW), expected)

    def test_utc_is_converted_to_msk(self):
        # 22:30 UTC 11 июля = 01:30 МСК 12 июля, то есть уже «сегодня»
        ts = int(datetime(2026, 7, 11, 22, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual(timefmt.moment(ts, self.NOW), "сегодня в 01:30")


if __name__ == "__main__":
    unittest.main()
