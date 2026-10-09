"""NYSE full-day closures and 1 p.m. early closes. Extend both sets each December from nyse.com."""

from datetime import date, datetime

HOLIDAYS = {
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
    date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
    date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
}

# Stocks and equity options stop trading at 1 p.m. ET on these days
EARLY_CLOSES = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}


def trading_day(day: date | datetime) -> bool:
    day = day.date() if isinstance(day, datetime) else day
    return day.weekday() < 5 and day not in HOLIDAYS


def close_time(day: date | datetime) -> tuple[int, int]:
    """Regular-session close (hour, minute) in New York time for that day."""
    day = day.date() if isinstance(day, datetime) else day
    return (13, 0) if day in EARLY_CLOSES else (16, 0)
