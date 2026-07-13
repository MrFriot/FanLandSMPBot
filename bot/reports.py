"""Текстовые отчёты бота: профиль игрока (/seen) и дашборд сервера (/stats).

Чистые функции: данные приходят из SessionStorage, «сейчас» — параметром,
никакого ввода-вывода. Благодаря этому формат сообщений тестируется
посимвольно, без Telegram.
"""
from collections import Counter
from datetime import date, datetime, timedelta

from . import timefmt
from .sessions import SessionStorage

_BLOCKS = "▁▂▃▄▅▆▇█"
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_WEEK = 7 * 86400


# -- профиль игрока ----------------------------------------------------------

def player_profile(sessions: SessionStorage, name: str, now: int) -> str | None:
    """Полный профиль игрока; None, если игрок ни разу не появлялся."""
    last = sessions.last_seen(name)
    if last is None:
        return None

    joined_at, left_at = last
    if left_at is None:
        head = f"🟢 {name} сейчас на сервере, зашёл {timefmt.moment(joined_at, now)}."
    else:
        head = (
            f"⚪ {name} был на сервере {timefmt.moment(left_at, now)}, "
            f"сессия длилась {timefmt.duration(left_at - joined_at)}."
        )

    stats = sessions.player_stats(name, now)
    week = sessions.playtime(name, since=now - _WEEK, until=now)
    total_all = sessions.window_stats(0, now).total_seconds
    share = round(100 * stats.total_seconds / total_all) if total_all else 0

    lines = [
        head,
        "",
        f"Заходов: {stats.sessions_count} · наиграно: {timefmt.duration(stats.total_seconds)}",
        f"За последние 7 дн: {timefmt.duration(week)}",
        f"Средняя сессия: {timefmt.duration(stats.total_seconds // stats.sessions_count)}"
        f" · рекорд: {timefmt.duration(stats.longest_seconds)}",
        f"Доля всего онлайна сервера: {share}%",
    ]

    usual = usual_join_hour(sessions.join_times(name))
    if usual is not None:
        lines.append(f"Обычно заходит около {usual:02d}:00")
    lines.append(f"Впервые замечен: {timefmt.moment(stats.first_seen, now)}")

    lines += ["", "Последние сессии:"]
    for joined, left in sessions.recent_sessions(name, limit=5):
        tail = "сейчас на сервере" if left is None else timefmt.duration(left - joined)
        lines.append(f"• {timefmt.moment(joined, now)} — {tail}")
    return "\n".join(lines)


def usual_join_hour(join_times: list[int], minimum: int = 5) -> int | None:
    """Час (МСК), в который игрок заходит чаще всего.

    None, если заходов меньше minimum — по паре сессий привычку
    не угадать. При равенстве выбирается меньший час.
    """
    if len(join_times) < minimum:
        return None
    counts = Counter(datetime.fromtimestamp(t, timefmt.MSK).hour for t in join_times)
    return min(range(24), key=lambda hour: (-counts.get(hour, 0), hour))


# -- дашборд сервера -----------------------------------------------------------

def server_dashboard(sessions: SessionStorage, days: int, now: int) -> str:
    """Сводка по серверу за days дней + графики активности.

    График по дням всегда покрывает последние 7 календарных дней МСК,
    независимо от days; остальные показатели считаются по окну days.
    """
    first = sessions.first_record()
    if first is None:
        return "Пока нет ни одной записи об игроках."

    since = now - days * 86400
    window = sessions.window_stats(since, now)
    lines = [
        f"📊 Дашборд сервера за {days} дн",
        "",
        f"Сейчас онлайн: {len(sessions.online_now())}",
        f"Игроков: {window.unique_players} · заходов: {window.sessions}",
        f"Наиграно: {timefmt.duration(window.total_seconds)}",
    ]

    if window.sessions:
        peak_count, peak_at = sessions.peak_online(since, now)
        lines.append(f"Пиковый онлайн: {peak_count} ({timefmt.moment(peak_at, now)})")

        top = sessions.top_playtime(since, now, limit=3)
        lines += ["", "Топ-3:"]
        lines += [
            f"{place}. {name} — {timefmt.duration(seconds)}"
            for place, (name, seconds) in enumerate(top, start=1)
        ]

        lines += ["", "Активность за 7 дней:"]
        week_spans = sessions.spans_between(now - _WEEK, now)
        day_rows = daily_seconds(week_spans, now)
        peak_day = max((seconds for _, seconds in day_rows), default=0)
        for day, seconds in day_rows:
            label = _WEEKDAYS[day.weekday()]
            if seconds == 0:
                lines.append(f"{label} —")
            else:
                lines.append(f"{label} {bar(seconds, peak_day)} {timefmt.duration(seconds)}")

        hours = hourly_seconds(sessions.spans_between(since, now))
        lines += ["", f"По часам (МСК): {sparkline(hours)}"]
        peak_hour = min(range(24), key=lambda hour: (-hours[hour], hour))
        lines.append(f"Пик: {peak_hour:02d}:00–{(peak_hour + 1) % 24:02d}:00")

    alltime = sessions.window_stats(0, now)
    lines += [
        "",
        f"За всё время: игроков {alltime.unique_players}"
        f" · наиграно {timefmt.duration(alltime.total_seconds)}",
        f"Первая запись: {timefmt.moment(first, now)}",
    ]
    return "\n".join(lines)


# -- разбиение по корзинам и рисование ------------------------------------------

def daily_seconds(spans: list[tuple[int, int]], now: int) -> list[tuple[date, int]]:
    """Наигранные секунды по каждому из последних 7 календарных дней МСК.

    Отрезки, пересекающие полночь, делятся между днями. Порядок —
    от старых к новым, сегодняшний день последним.
    """
    today = datetime.fromtimestamp(now, timefmt.MSK).date()
    week_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    totals = dict.fromkeys(week_days, 0)

    for start, end in spans:
        t = start
        while t < end:
            day = datetime.fromtimestamp(t, timefmt.MSK).date()
            midnight = int(
                datetime(day.year, day.month, day.day, tzinfo=timefmt.MSK).timestamp()
            )
            chunk_end = min(end, midnight + 86400)
            if day in totals:
                totals[day] += chunk_end - t
            t = chunk_end

    return [(day, totals[day]) for day in week_days]


def hourly_seconds(spans: list[tuple[int, int]]) -> list[int]:
    """Наигранные секунды по 24 часам суток (МСК), суммарно за все дни.

    Отрезки, пересекающие границу часа, делятся между часами.
    """
    totals = [0] * 24
    for start, end in spans:
        t = start
        while t < end:
            hour_start = t - t % 3600
            chunk_end = min(end, hour_start + 3600)
            hour = datetime.fromtimestamp(t, timefmt.MSK).hour
            totals[hour] += chunk_end - t
            t = chunk_end
    return totals


def bar(value: int, peak: int, width: int = 8) -> str:
    """Полоса из «▇» длиной, пропорциональной value/peak (минимум один блок)."""
    if peak <= 0 or value <= 0:
        return ""
    return "▇" * max(1, round(value / peak * width))


def sparkline(values: list[int]) -> str:
    """Строка-график: одна ячейка «▁▂▃▄▅▆▇█» на значение."""
    peak = max(values, default=0)
    if peak == 0:
        return _BLOCKS[0] * len(values)
    cells = []
    for value in values:
        if value == 0:
            index = 0
        else:
            index = max(1, round(value / peak * (len(_BLOCKS) - 1)))
        cells.append(_BLOCKS[index])
    return "".join(cells)
