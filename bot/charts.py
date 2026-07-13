"""Отрисовка дашборда /stats картинкой (PNG).

matplotlib работает в headless-режиме (Agg, без дисплея). Вся математика
корзин переиспользуется из reports — здесь только рисование.

Сбор данных и рисование разделены намеренно: соединение SQLite нельзя
трогать из чужого потока, поэтому collect() выполняется в основном
потоке (event loop), а тяжёлый render() можно уносить в asyncio.to_thread —
он работает с уже готовыми данными.
"""
import io
from dataclasses import dataclass
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend выбирается до импорта pyplot)

from . import reports, timefmt
from .sessions import SessionStorage

_BG = "#1b1e2b"
_PANEL = "#242938"
_TEXT = "#e8e9f0"
_MUTED = "#9aa0b4"
_GREEN = "#57c785"
_BLUE = "#6c9bf2"
_AMBER = "#e5b567"

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


@dataclass(frozen=True)
class DashboardData:
    """Всё, что нужно для отрисовки, — без ссылок на БД."""
    days: int
    now: int
    online: int
    unique_players: int
    sessions: int
    total_seconds: int
    peak: tuple[int, int] | None
    top: list[tuple[str, int]]
    day_rows: list[tuple[date, int]]
    hour_rows: list[int]


def collect(sessions: SessionStorage, days: int, now: int) -> DashboardData | None:
    """Собирает данные дашборда. Вызывать в потоке, где создана БД.

    None, если истории ещё нет (рисовать нечего).
    """
    if sessions.first_record() is None:
        return None

    since = now - days * 86400
    window = sessions.window_stats(since, now)
    return DashboardData(
        days=days,
        now=now,
        online=len(sessions.online_now()),
        unique_players=window.unique_players,
        sessions=window.sessions,
        total_seconds=window.total_seconds,
        peak=sessions.peak_online(since, now),
        top=sessions.top_playtime(since, now, limit=5),
        day_rows=reports.daily_seconds(sessions.spans_between(now - 7 * 86400, now), now),
        hour_rows=reports.hourly_seconds(sessions.spans_between(since, now)),
    )


def render(data: DashboardData) -> bytes:
    """Рисует PNG из готовых данных; БД не трогает, потокобезопасно."""
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.5), dpi=130, facecolor=_BG)
    (ax_info, ax_top), (ax_days, ax_hours) = axes
    for ax in axes.flat:
        _style(ax)

    fig.suptitle(f"Дашборд сервера · {data.days} дн", color=_TEXT, fontsize=17, fontweight="bold")
    _draw_info(ax_info, data)
    _draw_top(ax_top, data.top, data.days)
    _draw_days(ax_days, data.day_rows)
    _draw_hours(ax_hours, data.hour_rows)

    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG)
    plt.close(fig)
    return buf.getvalue()


def dashboard_png(sessions: SessionStorage, days: int, now: int) -> bytes | None:
    """Однопоточный вариант: собрать и отрисовать сразу (удобно в тестах)."""
    data = collect(sessions, days, now)
    return None if data is None else render(data)


def _style(ax) -> None:
    ax.set_facecolor(_PANEL)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=_MUTED, labelsize=9, length=0)


def _draw_info(ax, data: DashboardData) -> None:
    ax.set_title("Сводка", loc="left", color=_MUTED, fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])

    rows = [
        ("Сейчас онлайн", str(data.online), _GREEN),
        ("Игроков · заходов", f"{data.unique_players} · {data.sessions}", _TEXT),
        ("Наиграно", timefmt.duration(data.total_seconds), _TEXT),
    ]
    if data.peak is not None:
        count, at = data.peak
        rows.append(("Пиковый онлайн", f"{count} · {timefmt.moment(at, data.now)}", _AMBER))

    y = 0.82
    for label, value, color in rows:
        ax.text(0.05, y, label, color=_MUTED, fontsize=11, transform=ax.transAxes)
        ax.text(0.95, y, value, color=color, fontsize=13, fontweight="bold",
                ha="right", transform=ax.transAxes)
        y -= 0.22


def _draw_top(ax, top: list[tuple[str, int]], days: int) -> None:
    ax.set_title(f"Топ-5 за {days} дн", loc="left", color=_MUTED, fontsize=11)
    if not top:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, "нет данных за период", color=_MUTED,
                ha="center", va="center", transform=ax.transAxes)
        return

    names = [name for name, _ in reversed(top)]
    values = [seconds / 3600 for _, seconds in reversed(top)]
    bars = ax.barh(names, values, color=_BLUE, height=0.6)
    ax.set_xticks([])
    ax.tick_params(axis="y", labelcolor=_TEXT, labelsize=10)
    for bar_patch, (_, seconds) in zip(bars, reversed(top)):
        ax.text(bar_patch.get_width(), bar_patch.get_y() + bar_patch.get_height() / 2,
                " " + timefmt.duration(seconds), color=_MUTED, fontsize=9, va="center")
    ax.set_xlim(0, max(values) * 1.35)


def _draw_days(ax, day_rows) -> None:
    ax.set_title("Активность за 7 дней", loc="left", color=_MUTED, fontsize=11)
    labels = [_WEEKDAYS[day.weekday()] for day, _ in day_rows]
    hours = [seconds / 3600 for _, seconds in day_rows]

    # сегодняшний (последний) столбик выделяем цветом
    colors = [_GREEN] * (len(hours) - 1) + [_AMBER]
    bars = ax.bar(labels, hours, color=colors, width=0.65)
    ax.set_yticks([])
    ax.set_ylim(0, max(hours + [1]) * 1.25)
    for bar_patch, (_, seconds) in zip(bars, day_rows):
        if seconds:
            ax.text(bar_patch.get_x() + bar_patch.get_width() / 2, bar_patch.get_height(),
                    f"{seconds // 3600}:{seconds % 3600 // 60:02d}",
                    color=_MUTED, fontsize=8, ha="center", va="bottom")


def _draw_hours(ax, hour_rows: list[int]) -> None:
    ax.set_title("По часам (МСК)", loc="left", color=_MUTED, fontsize=11)
    hours = [seconds / 3600 for seconds in hour_rows]
    colors = [_BLUE] * 24
    if any(hour_rows):
        colors[hour_rows.index(max(hour_rows))] = _AMBER  # пиковый час
    ax.bar(range(24), hours, color=colors, width=0.8)
    ax.set_yticks([])
    ax.set_xticks([0, 6, 12, 18, 23])
    ax.set_xticklabels(["00", "06", "12", "18", "23"])
    ax.set_ylim(0, max(hours + [1]) * 1.15)
