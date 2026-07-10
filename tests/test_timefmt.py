import unittest

from bot import timefmt


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


if __name__ == "__main__":
    unittest.main()
