"""Месяцы и периоды для сравнения."""

import calendar
from datetime import date, timedelta


def month_range(month: str) -> tuple[date, date]:
    """'2026-11' -> (1 ноября, 1 декабря) — конец не входит в период."""
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end


def compare_ranges(month: str, today: date) -> tuple[date, date, date, date, int | None]:
    """Периоды для сравнения: этот месяц и те же дни прошлого месяца.

    Для текущего месяца берём дни с 1-го по сегодня, иначе — месяцы целиком.
    Возвращает (начало, конец, начало прошлого, конец прошлого, число дней или None);
    концы периодов не входят в них.
    """
    start, end = month_range(month)
    prev_start = (start - timedelta(days=1)).replace(day=1)
    if start <= today < end:
        days = today.day
        prev_len = calendar.monthrange(prev_start.year, prev_start.month)[1]
        return start, today + timedelta(days=1), prev_start, prev_start + timedelta(days=min(days, prev_len)), days
    return start, end, prev_start, start, None
