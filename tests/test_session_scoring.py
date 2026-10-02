"""A session is scored on the metric that drives the feedback sound, and records which one it was (#51)."""

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock

import pytest

from app.metrics.custom_formula import CustomFormulaEvaluator
from app.session.manager import SessionManager, SessionState
from app.storage.database import DatabaseManager
from app.ui.app_manager import FORMULA_KEYS, EEGMeditationApp
from tests.test_resume_mirror import _drive_tick, _make_tick_app, _metrics, _raw_sample


def _ticks(**series):
    """Per-tick metric dicts from equal-length value lists, e.g. _ticks(shamatha_score=[...], meditation_score=[...])."""
    n = len(next(iter(series.values())))
    return [{k: v[i] for k, v in series.items()} for i in range(n)]


# Shamatha and meditation disagree on every tick, so the scored metric decides the stats.
SHAMATHA_HIGH = _ticks(shamatha_score=[80, 85, 90, 20, 95], meditation_score=[10, 10, 10, 90, 10])


def _app(metric_key: str = "shamatha_score", formulas=()):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._audio_metric_key = metric_key
    app._session_program_active = False
    app._program_audio_key = ""
    app._active_program = None
    app._session_program_name = ""
    app._formula_slots = list(formulas) or [CustomFormulaEvaluator() for _ in FORMULA_KEYS]
    app._live_screen = MagicMock()
    app._live_screen.graph.series_name.side_effect = lambda k: {"shamatha_score": "Shamatha",
                                                                "meditation_score": "Meditation",
                                                                "custom_formula": "Calm ratio"}.get(k, k)
    app._is_paused = False
    app._scored_key = None
    sm = SessionManager()
    sm.start(threshold=50)
    sm._state = SessionState.RUNNING
    app._session_manager = sm
    return app


def _run(app, ticks):
    for m in ticks:
        app._score_on_drive_key()
        app._session_manager.add_metric(m)
    return app._session_manager.compute_statistics()


# --- the goal follows the feedback metric in a simple session ---------------------------------------------------

def test_the_default_feedback_metric_scores_the_session_on_shamatha():
    stats = _run(_app("shamatha_score"), SHAMATHA_HIGH)
    assert stats["score_metric_key"] == "shamatha_score"
    assert stats["time_above_threshold"] == 2  # 4 ticks >= 50 on shamatha (0.5 s each); meditation has 1
    assert stats["avg_score"] == pytest.approx((80 + 85 + 90 + 20 + 95) / 5)


def test_a_valid_custom_formula_scores_the_session_and_an_invalid_one_falls_back_to_shamatha():
    valid = CustomFormulaEvaluator()
    valid.set_formula("100 * s_alpha1")
    assert valid.is_valid
    app = _app("custom_formula", formulas=[valid, CustomFormulaEvaluator(), CustomFormulaEvaluator()])
    stats = _run(app, [{**m, "custom_formula": 70.0} for m in SHAMATHA_HIGH])
    assert stats["score_metric_key"] == "custom_formula" and stats["time_above_threshold"] == 2  # 5 ticks: 2.5 s

    invalid = CustomFormulaEvaluator()  # no formula: not valid
    stats = _run(_app("custom_formula", formulas=[invalid, CustomFormulaEvaluator(), CustomFormulaEvaluator()]),
                 SHAMATHA_HIGH)
    assert stats["score_metric_key"] == "shamatha_score"


def test_changing_the_feedback_metric_mid_session_moves_the_scoring():
    app = _app("shamatha_score")
    _run(app, SHAMATHA_HIGH[:3])  # 3 ticks above on shamatha
    app._audio_metric_key = "meditation_score"
    stats = _run(app, SHAMATHA_HIGH[3:])  # meditation: tick 4 above (90), tick 5 not
    assert stats["score_metric_key"] == "meditation_score"
    assert app._session_manager._time_above_threshold == 2.0  # 3 + 1 ticks


def test_the_legend_marks_the_scored_series_once_per_change():
    app = _app("shamatha_score")
    marks = [app._scored_mark(app._score_on_drive_key()) for _ in range(3)]
    app._audio_metric_key = "meditation_score"
    marks.append(app._scored_mark(app._score_on_drive_key()))
    assert marks == ["shamatha_score", None, None, "meditation_score"]


def test_a_change_during_a_screen_lock_is_marked_by_the_first_tick_after_it():
    app = _app("shamatha_score")
    app._scored_mark(app._score_on_drive_key())
    app._audio_metric_key = "meditation_score"
    app._is_paused = True
    assert app._scored_mark(app._score_on_drive_key()) is None  # no UI dispatch while locked
    app._is_paused = False
    assert app._scored_mark(app._score_on_drive_key()) == "meditation_score"


def test_a_program_session_keeps_its_segment_goal():
    sm = SessionManager()
    sm.start(threshold=50)
    sm._state = SessionState.RUNNING
    sm.set_active_goal("custom_formula", 60)  # what _apply_program_segment does
    for m in ({"custom_formula": 80, "shamatha_score": 0}, {"custom_formula": 90, "shamatha_score": 0}):
        sm.add_metric(m)
    assert sm._time_above_threshold == 1.0


# --- the record: key, display name and average, on every save path ---------------------------------------------

def test_the_saved_stats_carry_the_scored_metric_and_its_name():
    app = _app("custom_formula", formulas=[_valid(), CustomFormulaEvaluator(), CustomFormulaEvaluator()])
    stats = app._with_score(_run(app, [{**m, "custom_formula": 70.0} for m in SHAMATHA_HIGH]))
    assert (stats["score_metric_key"], stats["score_metric_name"]) == ("custom_formula", "Calm ratio")
    assert stats["avg_score"] == pytest.approx(70.0)


@pytest.mark.parametrize("name,recorded", [("Evening program", "Evening program"), ("", "Program")])
def test_a_program_session_records_program_its_name_and_no_average(name, recorded):
    app = _app()
    app._session_program_active = True
    app._active_program = MagicMock(segments=[{"duration": 60}])
    app._session_program_name = name
    stats = app._with_score(_run(app, SHAMATHA_HIGH))
    assert (stats["score_metric_key"], stats["score_metric_name"], stats["avg_score"]) == ("program", recorded, None)


def _valid():
    ev = CustomFormulaEvaluator()
    ev.set_formula("100 * s_alpha1")
    return ev


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = DatabaseManager(db_path=path)
    yield d
    d.close()
    os.remove(path)


def test_the_final_save_and_the_partial_flush_write_the_score_columns(db):
    uid = db.create_user("someone")
    first = {"duration": 60, "score_metric_key": "shamatha_score", "score_metric_name": "Shamatha", "avg_score": 61.5}
    sid = db.save_session(first, user_id=uid)  # the 60 s partial flush
    row = db.get_session(sid)
    assert (row["score_metric_key"], row["score_metric_name"], row["avg_score"]) == ("shamatha_score", "Shamatha", 61.5)
    db.update_session(sid, {**first, "score_metric_key": "custom_formula", "score_metric_name": "Calm ratio",
                            "avg_score": 70.0})  # the final save
    row = db.get_session(sid)
    assert (row["score_metric_key"], row["score_metric_name"], row["avg_score"]) == ("custom_formula", "Calm ratio", 70.0)


def test_an_old_database_gets_the_score_columns(tmp_path):
    path = str(tmp_path / "old.db")
    d = DatabaseManager(db_path=path)
    sid = d.save_session({"duration": 600}, user_id=d.create_user("someone"))
    d.close()
    conn = sqlite3.connect(path)  # turn it into a database from before #51
    present = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    for col in ("score_metric_key", "score_metric_name", "avg_score"):
        if col in present:
            conn.execute(f"ALTER TABLE sessions DROP COLUMN {col}")
    conn.commit()
    conn.close()
    d = DatabaseManager(db_path=path)
    try:
        row = d.get_session(sid)
        assert (row["score_metric_key"], row["score_metric_name"], row["avg_score"]) == ("", "", None)
    finally:
        d.close()


# --- reading a stored session: legacy rows keep the meaning their stats had --------------------------------------

def test_recorded_score_of_new_legacy_and_program_rows():
    from app.session.scoring import recorded_score
    assert recorded_score({"score_metric_key": "custom_formula", "score_metric_name": "Calm ratio",
                           "avg_score": 70.0}) == ("custom_formula", "Calm ratio", 70.0)
    assert recorded_score({"score_metric_key": "", "session_program": "", "avg_meditation": 44.0}) == (
        "meditation_score", "Meditation", 44.0)  # a legacy simple session was scored on meditation
    assert recorded_score({"score_metric_key": "", "session_program": '[{"duration": 60}]'}) == (
        "program", "Program", None)


def test_recomputing_from_the_stored_ticks_reproduces_the_stored_stats():
    from app.session.scoring import goal_stats
    app = _app("shamatha_score")
    ticks = _ticks(shamatha_score=[60, 70, 10, 55, 56, 57, 20, 99], meditation_score=[0] * 8)
    stats = _run(app, ticks)
    time_above, streak = goal_stats([m[stats["score_metric_key"]] for m in ticks], stats["threshold_used"])
    assert (int(time_above), int(streak)) == (stats["time_above_threshold"], stats["longest_streak"])


# --- the real tick ---------------------------------------------------------------------------------------------

def test_a_simple_session_tick_scores_on_the_feedback_metric_and_marks_it():
    app = _make_tick_app()
    app._timer_mode = "simple"
    app._audio_metric_key = "meditation_score"
    _drive_tick(app, _raw_sample(), _metrics())
    app._session_manager.set_active_goal.assert_called_with("meditation_score")
    ui_update = app._on_main.call_args_list[-1].args[0]
    ui_update()
    app._live_screen.set_training_series.assert_called_with("meditation_score")


def test_a_program_session_tick_leaves_the_goal_to_the_program():
    app = _make_tick_app()
    app._timer_mode = "program"
    app._session_program_active = True
    app._apply_program_tick = MagicMock()
    _drive_tick(app, _raw_sample(), _metrics())
    app._session_manager.set_active_goal.assert_not_called()


def test_program_mode_with_no_usable_program_is_scored_like_a_simple_session():
    app = _make_tick_app()
    app._timer_mode = "program"  # the Settings toggle; the session started without a program
    app._session_program_active = False
    app._audio_metric_key = "shamatha_score"
    _drive_tick(app, _raw_sample(), _metrics())
    app._session_manager.set_active_goal.assert_called_with("shamatha_score")


def test_one_tick_scores_and_sounds_the_same_metric():
    app = _make_tick_app()
    app._timer_mode = "simple"
    app._audio_drive_key = MagicMock(side_effect=["shamatha_score", "meditation_score"])  # changes mid-tick
    metrics = {**_metrics(), "shamatha_score": 11.0, "meditation_score": 77.0}
    _drive_tick(app, _raw_sample(), metrics)
    app._session_manager.set_active_goal.assert_called_with("shamatha_score")
    app._audio.update.assert_called_with(11.0)


def test_the_partial_flush_saves_the_scored_metric():
    from app.config import APP
    app = _make_tick_app()
    app._timer_mode = "simple"
    app._current_session_id = None
    app._metrics_buffer = [{"shamatha_score": 1.0}]
    app._flush_counter = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY) - 1  # this tick flushes
    app._session_manager.compute_statistics.return_value = {"duration": 60, "score_metric_key": "shamatha_score",
                                                            "avg_score": 52.5}
    app._live_screen.graph.series_name.return_value = "Shamatha"
    _drive_tick(app, _raw_sample(), _metrics())
    stats = app._db.save_session.call_args.args[0]
    assert (stats["score_metric_key"], stats["score_metric_name"], stats["avg_score"]) == (
        "shamatha_score", "Shamatha", 52.5)


def test_a_session_stopped_before_any_tick_records_the_feedback_metric():
    sm = SessionManager()
    sm.start(threshold=50)
    stats = sm.compute_statistics()
    assert stats["score_metric_key"] is None and stats["avg_score"] is None  # nothing was scored
    app = _app("shamatha_score")
    recorded = app._with_score(stats)
    assert (recorded["score_metric_key"], recorded["score_metric_name"], recorded["avg_score"]) == (
        "shamatha_score", "Shamatha", None)


def test_recomputing_from_ticks_stored_in_the_db_reproduces_the_stored_stats(db):
    from app.session.scoring import goal_stats
    app = _app("shamatha_score")
    ticks = _ticks(shamatha_score=[60, 70, 10, 55, 56, 57, 20, 99, 51, 52], meditation_score=[90] * 10)
    stats = app._with_score(_run(app, ticks))
    sid = db.save_session(stats, user_id=db.create_user("someone"))
    db.save_metrics_batch(sid, [{**m, "timestamp": i * 0.5} for i, m in enumerate(ticks)])
    row = db.get_session(sid)
    stored = [m[row["score_metric_key"]] for m in db.get_session_metrics(sid)]
    time_above, streak = goal_stats(stored, row["threshold_used"])
    assert (int(time_above), int(streak)) == (row["time_above_threshold"], row["longest_streak"])
    assert row["score_metric_key"] == "shamatha_score"  # meditation (all 90) would give a different answer
