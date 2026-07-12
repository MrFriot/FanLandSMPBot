"""Форматирование времени для сообщений бота."""
from datetime import datetime, timedelta, timezone

# Московское время: с 2014 года это фиксированный UTC+3 без сезонных
# переходов, поэтому обходимся без базы часовых поясов (в slim-образе её нет).
MSK = timezone(timedelta(hours=3), "МСК")

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def moment(ts: int, now: int) -> str:
    """Момент времени по МСК относительно текущей даты.

    'сегодня в 18:42', 'вчера в 09:15', '5 июля в 22:03',
    для прошлых лет — '5 июля 2025 в 22:03'.
    """
    dt = datetime.fromtimestamp(ts, MSK)
    today = datetime.fromtimestamp(now, MSK).date()
    clock = f"{dt.hour:02d}:{dt.minute:02d}"

    if dt.date() == today:
        return f"сегодня в {clock}"
    if dt.date() == today - timedelta(days=1):
        return f"вчера в {clock}"
    day_month = f"{dt.day} {_MONTHS[dt.month - 1]}"
    if dt.year == today.year:
        return f"{day_month} в {clock}"
    return f"{day_month} {dt.year} в {clock}"



def duration(seconds: int) -> str:
    """Интервал в виде двух старших единиц: '3 дн 4 ч', '2 ч 15 мин', '45 мин'.

    Минуты опускаются, если есть дни; всё, что меньше минуты, — '< 1 мин'.
    """
    if seconds < 60:
        return "< 1 мин"
    minutes = seconds // 60
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)

    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours:
        parts.append(f"{hours} ч")
    if mins and not days:
        parts.append(f"{mins} мин")
    return " ".join(parts)
