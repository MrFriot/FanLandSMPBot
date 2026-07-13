import unittest

from bot import charts

from .helpers import make_sessions, msk

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    """Ширина и высота из заголовка IHDR."""
    return int.from_bytes(data[16:20]), int.from_bytes(data[20:24])


class TestDashboardPng(unittest.TestCase):
    def setUp(self):
        self.sessions = make_sessions()

    def test_empty_history_returns_none(self):
        self.assertIsNone(charts.dashboard_png(self.sessions, days=7, now=100))

    def test_renders_png_with_data(self):
        self.sessions.open_session("Steve", at=msk(2026, 7, 12, 16, 0))
        self.sessions.close_session("Steve", at=msk(2026, 7, 12, 19, 0))
        self.sessions.open_session("Alex", at=msk(2026, 7, 12, 19, 30))
        self.sessions.open_session("Bob", at=msk(2026, 7, 10, 23, 0))
        self.sessions.close_session("Bob", at=msk(2026, 7, 11, 1, 0))

        png = charts.dashboard_png(self.sessions, days=7, now=msk(2026, 7, 12, 20, 0))
        self.assertTrue(png.startswith(_PNG_MAGIC))
        width, height = png_size(png)
        self.assertGreater(width, 800)
        self.assertGreater(height, 500)

    def test_renders_when_window_is_empty(self):
        """История есть, но в окне пусто: не должно быть деления на ноль."""
        self.sessions.open_session("Old", at=msk(2026, 6, 1, 10, 0))
        self.sessions.close_session("Old", at=msk(2026, 6, 1, 12, 0))

        png = charts.dashboard_png(self.sessions, days=7, now=msk(2026, 7, 12, 20, 0))
        self.assertTrue(png.startswith(_PNG_MAGIC))


if __name__ == "__main__":
    unittest.main()
