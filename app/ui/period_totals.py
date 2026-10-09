"""History's totals around a day (#58): its day, Monday-to-Sunday week and month, from the sessions History holds."""

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class PeriodTotals:
    seconds: int  # the sessions' length
    on_target: int  # time above threshold, each session against its own target
    best_streak: int  # the longest one: a streak doesn't span sessions
    sessions: int


def session_day(session: dict) -> str:
    """'YYYY-MM-DD': the local day a session started, the calendar's key; ISO dates order as strings do."""
    return (session.get("date_time") or "")[:10]


def period_totals(sessions: list[dict], start: datetime.date, end: datetime.date) -> PeriodTotals:
    """Totals of the sessions that started from `start` to `end`, local dates, both included."""
    first, last = start.isoformat(), end.isoformat()
    inside = [s for s in sessions if first <= session_day(s) <= last]
    return PeriodTotals(
        seconds=sum(int(s.get("duration") or 0) for s in inside),
        on_target=sum(int(s.get("time_above_threshold") or 0) for s in inside),
        best_streak=max((int(s.get("longest_streak") or 0) for s in inside), default=0),
        sessions=len(inside),
    )


ALL_TIME = ("All time", datetime.date.min, datetime.date.max)  # every session, whichever day is shown


def day_month(day: datetime.date) -> str:
    return f"{day.day} {day:%b}"


def day_range(first: datetime.date, last: datetime.date) -> str:
    """'5 – 11 Oct', '28 Sep – 4 Oct': day first, the month once when both days share it."""
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day} – {day_month(last)}"
    return f"{day_month(first)} – {day_month(last)}"


def periods_around(day: datetime.date, today: datetime.date) -> list[tuple[str, datetime.date, datetime.date]]:
    """(label, first day, last day) of the day, its Monday-to-Sunday week (the calendar's) and its month; a month of
    another year than today's says which."""
    monday = day - datetime.timedelta(days=day.weekday())
    sunday = monday + datetime.timedelta(days=6)
    week = day_range(monday, sunday)
    first = day.replace(day=1)
    last = (first + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    return [(f"{day:%a} {day_month(day)}", day, day), (week, monday, sunday),
            (f"{day:%B}" if day.year == today.year else f"{day:%B %Y}", first, last)]
