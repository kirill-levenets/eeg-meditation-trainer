"""History's totals around a day: the day, its Monday-to-Sunday week and its month, each summing the sessions' length
and time on target (each session against its own target) and taking their longest streak."""

import datetime

import pytest

from app.ui.period_totals import (
    PeriodTotals,
    period_totals,
    periods_around,
    session_day,
)

D = datetime.date
TODAY = D(2026, 10, 7)


def _session(when: str, duration: int, on_target: int = 0, streak: int = 0) -> dict:
    return {"date_time": when, "duration": duration, "time_above_threshold": on_target, "longest_streak": streak}


SESSIONS = [
    _session("2026-09-27T21:00:00", 600, 60, 30),     # Sunday: the week before
    _session("2026-09-28T06:00:00", 1200, 300, 120),  # Monday
    _session("2026-09-30T23:59:59", 900, 100, 200),   # Wednesday, a second before midnight: still the 30th
    _session("2026-10-01T00:00:00", 1800, 600, 90),   # Thursday, at midnight: the 1st, another month
    _session("2026-10-01T07:30:00", 1500, 0, 0),
    _session("2026-10-04T20:00:00", 300, 30, 15),     # Sunday: the week's last day
    _session("2026-10-05T06:00:00", 2400, 900, 400),  # Monday: the next week
]


def test_an_empty_period_is_all_zero():
    assert period_totals(SESSIONS, D(2026, 9, 29), D(2026, 9, 29)) == PeriodTotals(0, 0, 0, 0)
    assert period_totals([], D(2026, 1, 1), D(2026, 12, 31)) == PeriodTotals(0, 0, 0, 0)


def test_a_day_sums_its_sessions_and_takes_the_longest_streak():
    assert period_totals(SESSIONS, D(2026, 10, 1), D(2026, 10, 1)) == PeriodTotals(3300, 600, 90, 2)


def test_the_streak_is_the_longest_not_the_sum():
    week = period_totals(SESSIONS, D(2026, 9, 28), D(2026, 10, 4))
    assert week.best_streak == 200 and week.on_target == 300 + 100 + 600 + 0 + 30


def test_sessions_belong_to_the_local_day_they_started():
    assert period_totals(SESSIONS, D(2026, 9, 30), D(2026, 9, 30)).sessions == 1
    assert period_totals(SESSIONS, D(2026, 10, 1), D(2026, 10, 1)).sessions == 2


def test_a_week_runs_monday_to_sunday_and_a_month_by_the_calendar():
    (_, d0, d1), (_, w0, w1), (_, m0, m1) = periods_around(D(2026, 10, 1), TODAY)
    assert (d0, d1) == (D(2026, 10, 1), D(2026, 10, 1))
    assert (w0, w1) == (D(2026, 9, 28), D(2026, 10, 4))  # the week crosses into the month before
    assert (m0, m1) == (D(2026, 10, 1), D(2026, 10, 31))
    assert period_totals(SESSIONS, w0, w1).sessions == 5
    assert period_totals(SESSIONS, m0, m1).sessions == 4


@pytest.mark.parametrize("day, last", [(D(2026, 2, 10), D(2026, 2, 28)), (D(2028, 2, 10), D(2028, 2, 29)),
                                       (D(2026, 12, 31), D(2026, 12, 31))])
def test_a_month_ends_on_its_last_day(day, last):
    assert periods_around(day, day)[2][2] == last


@pytest.mark.parametrize("day, labels", [
    (D(2026, 10, 7), ["Wed 7 Oct", "5 – 11 Oct", "October"]),
    (D(2026, 10, 1), ["Thu 1 Oct", "28 Sep – 4 Oct", "October"]),   # the week crosses a month
    (D(2026, 12, 31), ["Thu 31 Dec", "28 Dec – 3 Jan", "December"]),  # and a year
])
def test_each_row_is_labelled_with_its_dates(day, labels):
    assert [label for label, _start, _end in periods_around(day, day)] == labels


def test_a_month_of_another_year_says_which():
    assert periods_around(D(2025, 12, 30), TODAY)[2][0] == "December 2025"
    assert periods_around(D(2026, 1, 5), TODAY)[2][0] == "January"


def test_a_session_belongs_to_the_day_its_start_is_dated():
    assert session_day({"date_time": "2026-10-07T23:59:59"}) == "2026-10-07"
    assert session_day({"date_time": None}) == session_day({}) == ""


def test_a_row_without_a_stored_value_counts_it_as_zero():
    # Older sessions can hold NULL in columns added later.
    rows = [{"date_time": "2026-10-07T06:00:00", "duration": 600, "time_above_threshold": None, "longest_streak": None}]
    assert period_totals(rows, D(2026, 10, 7), D(2026, 10, 7)) == PeriodTotals(600, 0, 0, 1)


def test_a_row_without_a_date_is_left_out():
    rows = [{"date_time": "", "duration": 600}, {"duration": 300}]
    assert period_totals(rows, D(2000, 1, 1), D(2100, 1, 1)).sessions == 0
