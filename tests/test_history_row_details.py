"""Each History row shows the session's date and time, its score, duration and longest streak, and its notes (#49)."""

import datetime
import time
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.metrics import dp

from app.config import APP
from app.session.manager import SessionManager
from app.ui.history_screen import HistoryScreen, _SessionRow
from app.ui.session_labels import (
    session_label,
    session_notes_line,
    session_stats_line,
    session_threshold_row,
    session_title,
)

WHEN = "2026-09-26T14:05:12.993002"  # as stored: ISO with a T and microseconds


# ---- line 1: date, time and the name without an auto-generated time ----


@pytest.mark.parametrize("name, title, label", [
    ("2026-09-26 14:05 - MindWave Mobile", "2026-09-26 14:05 - MindWave Mobile", "MindWave Mobile"),  # new auto name
    ("14:05 - MindWave Mobile", "2026-09-26 14:05 - MindWave Mobile", "MindWave Mobile"),  # old auto name
    ("Morning sit", "2026-09-26 14:05 - Morning sit", "Morning sit"),  # renamed
    ("", "2026-09-26 14:05", ""),  # unnamed
    ("06:30 - Before work", "2026-09-26 14:05 - 06:30 - Before work", "06:30 - Before work"),  # a user's own time
    ("2026-09-25 14:05 - Yesterday's note", "2026-09-26 14:05 - 2026-09-25 14:05 - Yesterday's note",
     "2026-09-25 14:05 - Yesterday's note"),  # another day's stamp is part of the name
])
def test_a_title_is_the_date_and_time_then_the_name_without_its_auto_time(name, title, label):
    session = {"date_time": WHEN, "session_name": name}
    assert session_title(session) == title
    assert session_label(session) == label


def test_a_title_with_an_unreadable_date_still_shows_it():
    assert session_title({"date_time": "garbage", "session_name": "x"}) == "garbage - x"


# ---- line 2: the scored metric and its average, the duration, the streak ----


def _scored(**kw) -> dict:
    return {"score_metric_key": "shamatha_score", "score_metric_name": "Shamatha", "avg_score": 72.4,
            "session_program": "", "duration": 1500, "longest_streak": 270, **kw}


def test_the_stats_line_names_the_metric_the_session_was_scored_on():
    assert session_stats_line(_scored()) == "Shamatha 72 · 25m 00s · Streak 4m 30s"
    assert session_stats_line(_scored(score_metric_key="custom_formula", score_metric_name="Calm ratio",
                                      avg_score=133.0)) == "Calm ratio 133 · 25m 00s · Streak 4m 30s"


@pytest.mark.parametrize("program", ["", '[{"duration": 60}]'])
def test_a_session_that_saved_no_metric_keeps_its_old_line(program):
    # Before #51 no metric was saved (and the streak was measured on meditation): average shamatha and the duration.
    legacy = {"score_metric_key": "", "session_program": program, "avg_meditation": 44.0, "avg_shamatha": 70.0,
              "duration": 600, "longest_streak": 30}
    assert session_stats_line(legacy) == "Shamatha 70 · 10m 00s"


@pytest.mark.parametrize("session, row", [
    (_scored(threshold_used=50), ("Scored on", "Shamatha ≥ 50")),
    (_scored(score_metric_key="custom_formula", score_metric_name="Calm ratio", threshold_used=120),
     ("Scored on", "Calm ratio ≥ 120")),
    (_scored(score_metric_key="program", score_metric_name="Evening ladder", avg_score=None, threshold_used=40,
             session_program='[{"duration": 60}]'), ("Scored on", "Evening ladder (program)")),
    ({"score_metric_key": "", "session_program": "", "threshold_used": 50}, ("Threshold Used", "50")),
    ({"score_metric_key": "", "session_program": '[{"duration": 60}]', "threshold_used": 40}, ("Threshold Used", "40")),
])
def test_the_threshold_row_names_the_saved_metric_or_keeps_the_old_row(session, row):
    assert session_threshold_row(session) == row


def test_a_program_session_shows_the_program_name_and_no_average():
    program = _scored(score_metric_key="program", score_metric_name="Evening ladder", avg_score=None,
                      session_program='[{"duration": 60}]')
    assert session_stats_line(program) == "Evening ladder · 25m 00s · Streak 4m 30s"


def test_no_streak_and_no_average_are_left_out():
    assert session_stats_line(_scored(longest_streak=0)) == "Shamatha 72 · 25m 00s"
    assert session_stats_line(_scored(avg_score=None, duration=20, longest_streak=None)) == "Shamatha · 20s"


# ---- line 3: the first line of the notes ----


@pytest.mark.parametrize("notes, line", [
    ("Calm, then sleepy\nsecond line", "Calm, then sleepy"),
    ("\n  \n  Late start  \nmore", "Late start"),
    ("   \n ", ""),
    ("", ""),
    (None, ""),
])
def test_the_notes_line_is_the_first_line_with_text(notes, line):
    assert session_notes_line({"notes": notes}) == line


# ---- the rows ----


def _frames(n: int = 10) -> None:
    for _ in range(n):
        EventLoop.idle()


@pytest.fixture
def history():
    from kivy.core.window import Window
    EventLoop.ensure_window()
    h = HistoryScreen()
    Window.add_widget(h)
    _frames()
    yield h
    Window.remove_widget(h)


def _sessions() -> list[dict]:
    return [
        {"id": 1, "date_time": "2026-09-26T14:05:12", "session_name": "2026-09-26 14:05 - MindWave Mobile",
         "duration": 1500, "longest_streak": 270, "avg_shamatha": 70, "score_metric_key": "shamatha_score",
         "score_metric_name": "Shamatha", "avg_score": 72.4, "session_program": "", "notes": "Calm, then sleepy"},
        {"id": 2, "date_time": "2026-09-25T08:30:00", "session_name": "08:30 - MindWave Mobile", "duration": 600,
         "longest_streak": 0, "avg_shamatha": 50, "score_metric_key": "", "avg_meditation": 44.0,
         "session_program": "", "notes": ""},
    ]


def _views(h: HistoryScreen) -> dict:
    return {v.sid: v for v in h._rv.layout_manager.children if isinstance(v, _SessionRow)}


def test_a_row_shows_its_three_lines_and_one_without_notes_shows_two(history):
    history.load_sessions(_sessions())
    _frames()
    rows = _views(history)
    with_notes, without = rows[1], rows[2]
    assert with_notes._name_label.text == "2026-09-26 14:05 - MindWave Mobile"
    assert with_notes._stats_label.text == "Shamatha 72 · 25m 00s · Streak 4m 30s"
    assert with_notes._notes_label.text == "Calm, then sleepy" and with_notes._notes_label.parent is not None
    assert without._name_label.text == "2026-09-25 08:30 - MindWave Mobile"
    assert without._notes_label.parent is None  # detached, not an empty line
    assert with_notes.height > without.height == dp(56)
    assert with_notes._card.height == with_notes.height


def test_long_lines_are_cut_to_one_line_not_wrapped(history):
    sessions = _sessions()
    sessions[0]["session_name"] = "A very long custom session name that cannot fit on a phone row " * 2
    sessions[0]["notes"] = "Long notes that run well past the width of the row on a phone screen " * 3
    history.load_sessions(sessions)
    _frames()
    row = _views(history)[1]
    for label in (row._name_label, row._stats_label, row._notes_label):
        assert label.shorten and label.texture_size[0] <= label.width + 1
        assert label.texture_size[1] < 2 * label.font_size * 1.5  # a single line


def test_saved_notes_show_on_the_row_at_once(history):
    history.load_sessions(_sessions())
    _frames()
    history.update_session(2, notes="Restless\nthen fine")
    _frames()
    row = _views(history)[2]
    assert row._notes_label.text == "Restless" and row._notes_label.parent is not None
    assert row.height > dp(56)
    history.update_session(2, notes="")  # cleared: back to two lines
    _frames()
    row = _views(history)[2]
    assert row._notes_label.parent is None and row.height == dp(56)


def test_saving_the_rename_editor_unchanged_writes_nothing(history):
    renamed = []
    history._on_rename_session = lambda sid, name: renamed.append((sid, name))
    history.load_sessions(_sessions())
    _frames()
    history._toggle_rename(1)
    _frames()
    history._rename_input.dispatch("on_text_validate")
    _frames()
    assert renamed == []  # the stored "2026-09-26 14:05 - MindWave Mobile" keeps its date
    assert history._sessions[0]["session_name"] == "2026-09-26 14:05 - MindWave Mobile"
    assert history._renaming_sid is None


def test_the_rename_editor_edits_the_name_and_the_row_keeps_its_date(history):
    renamed = []
    history._on_rename_session = lambda sid, name: renamed.append((sid, name))
    history.load_sessions(_sessions())
    _frames()
    history._toggle_rename(1)
    _frames()
    assert history._rename_input.text == "MindWave Mobile"  # not the date and time, which aren't the name
    history._rename_input.text = "Morning sit"
    history._rename_input.dispatch("on_text_validate")
    _frames()
    assert renamed == [(1, "Morning sit")]
    assert _views(history)[1]._name_label.text == "2026-09-26 14:05 - Morning sit"


def test_a_renamed_row_with_notes_is_taller_by_the_editor(history):
    history.load_sessions(_sessions())
    _frames()
    plain = _views(history)[1].height
    history._toggle_rename(1)
    _frames()
    row = _views(history)[1]
    assert row.height == plain + history._rename_row.height
    assert row._card.height == plain


# ---- the session detail and the default name ----


def test_the_session_detail_is_titled_like_its_row():
    from app.ui.diary_screen import DiaryScreen
    diary = DiaryScreen()
    diary.show_session_detail(dict(_sessions()[0]))
    assert diary._detail_title.text == "2026-09-26 14:05 - MindWave Mobile"


def test_a_new_session_is_named_with_its_date(monkeypatch):
    from app.ui.app_manager import EEGMeditationApp
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._session_manager = SessionManager()
    app._real_stream = MagicMock()
    app._session_manager.start()
    started = time.time() - 3600
    app._session_manager._start_time = started
    assert app._make_session_name() == datetime.datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M") + " - Mock"


def test_a_long_session_title_is_cut_to_the_detail_screen_width():
    from app.ui.diary_screen import DiaryScreen
    diary = DiaryScreen()
    session = dict(_sessions()[0], session_name="Evening sit after a long day at work with lots of meetings")
    diary.show_session_detail(session)
    title = diary._detail_title
    title.width = dp(320)
    title.texture_update()
    assert title.texture_size[0] <= title.width + 1


def test_the_default_name_is_recognised_as_the_sessions_own_time(monkeypatch):
    # The name and the row's date come from the same start: the title must not show the time twice.
    from app.ui.app_manager import EEGMeditationApp
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._session_manager = SessionManager()
    app._real_stream = MagicMock()
    app._session_manager.start()
    started = app._session_manager.started_at
    session = {"date_time": datetime.datetime.fromtimestamp(started).isoformat(),
               "session_name": app._make_session_name()}
    assert session_label(session) == "Mock"
    assert session_title(session) == datetime.datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M") + " - Mock"


# ---- the session detail and the end card name what the threshold stats were measured on ----


def _diary_with(session):
    from app.ui.diary_screen import DiaryScreen
    diary = DiaryScreen()
    diary.show_session_detail(dict(session))
    return diary


def _legend_texts(diary) -> list[str]:
    diary._rebuild_legend("metrics")
    return [w.text for w in diary._legend_container.children]


def test_the_session_detail_names_what_the_session_was_scored_on():
    diary = _diary_with(dict(_sessions()[0], threshold_used=50))
    assert (diary._scored_on_title.text, diary._detail_stats["scored_on"].text) == ("Scored on", "Shamatha ≥ 50")
    assert "» Shamatha" in _legend_texts(diary)


def test_the_session_detail_shows_only_the_scored_stats():
    diary = _diary_with(dict(_sessions()[0], threshold_used=50))
    assert list(diary._detail_stats) == ["duration", "scored_on", "time_above_threshold", "longest_streak",
                                         "mood_rating"]  # no averages and no time shamatha >= 90
    grid = diary._stats_grid
    rows = len(grid.children) // 2
    assert grid.height >= rows * dp(20) + (rows - 1) * grid.spacing[1] + grid.padding[1] + grid.padding[3]


def test_a_session_that_saved_no_metric_keeps_its_threshold_row_and_marks_no_series():
    diary = _diary_with(dict(_sessions()[1], threshold_used=50))
    assert (diary._scored_on_title.text, diary._detail_stats["scored_on"].text) == ("Threshold Used", "50")
    assert not any(t.startswith("» ") for t in _legend_texts(diary))


def test_a_program_session_marks_no_single_series():
    diary = _diary_with(dict(_sessions()[0], score_metric_key="program", score_metric_name="Evening ladder",
                             avg_score=None, session_program='[{"duration": 60, "target": 50}]'))
    assert diary._detail_stats["scored_on"].text == "Evening ladder (program)"
    assert not any(t.startswith("» ") for t in _legend_texts(diary))


def test_the_end_card_shows_the_name_duration_and_the_scored_stats():
    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    stats = {"duration": 600, "avg_shamatha": 70, "avg_meditation": 50, "time_above_threshold": 300,
             "time_shamatha_90": 20, "longest_streak": 120, "threshold_used": 50,
             "score_metric_key": "shamatha_score", "score_metric_name": "Shamatha", "avg_score": 70.0}
    screen.show_summary(7, stats, title="2026-10-03 20:05 - MindWave Mobile")
    shown = {k: v.text for k, v in screen._summary_stats.items()}
    assert shown == {"name": "2026-10-03 20:05 - MindWave Mobile", "duration": "10m 00s",
                     "scored_on": "Shamatha ≥ 50", "time_above": "5m 00s", "longest_streak": "2m 00s"}
    assert screen._summary_scored_on_title.text == "Scored on"
    card = screen._summary_stats_card
    assert card.height >= sum(c.height for c in card.children) + card.padding[1] + card.padding[3]


def test_the_end_card_is_titled_with_the_saved_session(monkeypatch):
    from app.ui.app_manager import EEGMeditationApp
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = MagicMock()
    app._db = MagicMock()
    app._db.get_session.return_value = {"id": 9, "date_time": "2026-10-03T20:05:46.25",
                                        "session_name": "2026-10-03 20:05 - MindWave Mobile"}
    for name in ("_reload_live_graphs_from_mirror", "_undo_session_setup", "_mark_history_dirty"):
        monkeypatch.setattr(app, name, MagicMock())
    app._finalize_stop_ui({"duration": 96}, 9)
    app._live_screen.show_summary.assert_called_once_with(
        9, {"duration": 96}, title="2026-10-03 20:05 - MindWave Mobile")


# ---- review round: widths at phone size, one name per series, a failed title read ----


def _natural_width(label) -> float:
    from kivy.core.text import Label as CoreLabel
    core = CoreLabel(text=label.text, font_size=label.font_size, bold=label.bold)
    core.refresh()
    return core.texture.size[0]


@pytest.fixture
def phone_window():
    from kivy.core.window import Window
    EventLoop.ensure_window()
    old = Window.size
    Window.size = (dp(360), dp(640))
    _frames()
    yield Window
    Window.size = old
    _frames()


def test_the_end_card_shows_a_long_scored_on_value_whole_on_a_phone(phone_window):
    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    phone_window.add_widget(screen)
    try:
        stats = {"duration": 600, "threshold_used": 40, "score_metric_key": "program",
                 "score_metric_name": "Morning ladder", "avg_score": None}
        screen.show_summary(1, stats, title="2026-10-03 07:15 - MindWave Mobile")
        _frames()
        value = screen._summary_stats["scored_on"]
        assert value.text == "Morning ladder (program)"
        assert value.width >= _natural_width(value), (value.width, _natural_width(value))
    finally:
        screen.hide_summary()
        phone_window.remove_widget(screen)


def test_the_session_detail_shows_a_long_scored_on_value_whole_on_a_phone(phone_window):
    from app.ui.diary_screen import DiaryScreen
    diary = DiaryScreen()
    phone_window.add_widget(diary)
    try:
        diary.show_session_detail(dict(_sessions()[0], score_metric_key="program", score_metric_name="Morning ladder",
                                       avg_score=None, session_program='[{"duration": 60, "target": 50}]'))
        _frames()
        value = diary._detail_stats["scored_on"]
        assert value.width >= _natural_width(value), (value.width, _natural_width(value))
    finally:
        phone_window.remove_widget(diary)


def test_the_detail_legend_names_a_series_as_the_live_graph_does():
    # Scored on reads the name the live graph gave the metric; the legend under it must say the same.
    from app.ui.live_session import SERIES_NAMES
    diary = _diary_with(dict(_sessions()[0], score_metric_key="native_meditation", score_metric_name="NS Meditation",
                             threshold_used=50))
    assert diary._detail_stats["scored_on"].text == "NS Meditation ≥ 50"
    assert diary._metrics_graph.series_name("native_meditation") == SERIES_NAMES["native_meditation"]
    assert "» NS Meditation" in _legend_texts(diary)


def test_a_failed_title_read_still_shows_the_end_card(monkeypatch):
    import sqlite3

    from app.ui.app_manager import EEGMeditationApp
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = MagicMock()
    app._db = MagicMock()
    app._db.get_session.side_effect = sqlite3.OperationalError("disk I/O error")
    for name in ("_reload_live_graphs_from_mirror", "_undo_session_setup", "_mark_history_dirty"):
        monkeypatch.setattr(app, name, MagicMock())
    app._finalize_stop_ui({"duration": 96}, 9)  # the session is saved; only its title couldn't be read
    app._live_screen.show_summary.assert_called_once_with(9, {"duration": 96}, title="")
