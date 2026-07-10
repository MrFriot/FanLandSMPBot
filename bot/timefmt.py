"""Форматирование интервалов времени для сообщений бота."""


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
