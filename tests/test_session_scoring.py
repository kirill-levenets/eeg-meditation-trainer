"""A session is scored on the metric that drives the feedback sound, and records which one it was (#51)."""

import os
import sqlite3
import tempfile

import pytest

from app.config import APP
from app.session.manager import NO_SCORE, SessionManager, SessionState
from app.session.scoring import goal_stats
from app.storage.database import DatabaseManager
from tests._app import FedSession, calls_of, frames, program_mode, reload_with


def _ticks(**series):
    """Per-tick metric dicts from equal-length value lists, e.g. _ticks(shamatha_score=[...], meditation_score=[...])."""
    n = len(next(iter(series.values())))
    return [{k: v[i] for k, v in series.items()} for i in range(n)]


# Shamatha and meditation disagree on every tick, so the scored metric decides the stats.
SHAMATHA_HIGH = _ticks(shamatha_score=[80, 85, 90, 20, 95], meditation_score=[10, 10, 10, 90, 10])
CALM_RATIO = [{"name": "Calm ratio", "formula": "alpha1"}]  # reads 70 on the sample the sessions below are fed


def _session(app, monkeypatch, metric: str = "shamatha_score", formulas=()) -> FedSession:
    """A simple session against a threshold of 50, the sound driven by `metric`; its ticks are the test's."""
    reload_with(app, {"active_formulas": list(formulas)}, threshold="50", audio_metric=metric)
    fed = FedSession(app, monkeypatch)
    fed.raw = {**fed.raw, "alpha1": 70.0}
    return fed


def _run(fed: FedSession, ticks) -> dict:
    """Run the ticks, each computing to its metrics; the session's stats so far."""
    for m in ticks:
        fed.tick(metrics=dict(m))
    return fed.app._session.manager.compute_statistics()


def _saved(app) -> dict:
    """End the session; its stored row."""
    app._stop_and_save()
    frames()
    return app._db.get_all_sessions(app._current_user_id)[0]


# --- the goal follows the feedback metric in a simple session ---------------------------------------------------

def test_the_default_feedback_metric_scores_the_session_on_shamatha(fresh_app, monkeypatch):
    stats = _run(_session(fresh_app, monkeypatch), SHAMATHA_HIGH)
    assert stats["score_metric_key"] == "shamatha_score"
    assert stats["time_above_threshold"] == 2  # 4 ticks >= 50 on shamatha (0.5 s each); meditation has 1
    assert stats["avg_score"] == pytest.approx((80 + 85 + 90 + 20 + 95) / 5)


def test_a_valid_custom_formula_scores_the_session(fresh_app, monkeypatch):
    stats = _run(_session(fresh_app, monkeypatch, "custom_formula", CALM_RATIO), SHAMATHA_HIGH)
    assert stats["score_metric_key"] == "custom_formula" and stats["time_above_threshold"] == 2  # 5 ticks: 2.5 s


def test_a_formula_slot_that_cant_run_falls_back_to_shamatha(fresh_app, monkeypatch):
    stats = _run(_session(fresh_app, monkeypatch, "custom_formula"), SHAMATHA_HIGH)  # the slot is empty
    assert stats["score_metric_key"] == "shamatha_score"


def test_a_metric_held_mid_session_scores_the_next_session(fresh_app, monkeypatch):
    # Settings refuses the change while a simple session runs; the session runs on the metric its Start read anyway.
    fed = _session(fresh_app, monkeypatch)
    marks = calls_of(monkeypatch, fresh_app._live_screen, "set_training_series")
    _run(fed, SHAMATHA_HIGH[:3])  # 3 ticks above on shamatha
    fresh_app._settings_store.change("audio_metric", "meditation_score")
    stats = _run(fed, SHAMATHA_HIGH[3:])  # shamatha: tick 5 above (95), tick 4 not
    assert stats["score_metric_key"] == "shamatha_score" and stats["time_above_threshold"] == 2
    assert marks == [("shamatha_score",)]  # the legend marked once, at the first tick
    fresh_app._stop_and_save()
    frames()
    fresh_app._shown.close(keep_notes=False)
    assert _run(FedSession(fresh_app, monkeypatch), SHAMATHA_HIGH)["score_metric_key"] == "meditation_score"


def test_a_session_started_during_a_screen_lock_marks_its_series_at_the_first_tick_after_it(fresh_app, monkeypatch):
    app = fresh_app
    fed = _session(app, monkeypatch)
    marks = calls_of(monkeypatch, app._live_screen, "set_training_series")
    app.on_pause()
    _run(fed, SHAMATHA_HIGH[:1])
    assert marks == []  # no UI dispatch while locked
    app.on_resume()
    frames()
    _run(fed, SHAMATHA_HIGH[1:2])
    assert marks == [("shamatha_score",)]


def test_a_program_session_keeps_its_segment_goal():
    sm = SessionManager()
    sm.start(threshold=50)
    sm._state = SessionState.RUNNING
    sm.start_segment("custom_formula", 60)  # what ProgramRun._enter_segment does
    for m in ({"custom_formula": 80, "shamatha_score": 0}, {"custom_formula": 90, "shamatha_score": 0}):
        sm.add_metric(m)
    assert sm._time_above_threshold == 1.0



# --- the live score the stats bar shows (#113) -------------------------------------------------------------------

def test_the_live_score_follows_the_scored_metric_from_running_totals():
    sm = SessionManager()
    sm.start(threshold=60)
    sm.set_active_goal("shamatha_score")
    for m in SHAMATHA_HIGH:  # shamatha 80, 85, 90, 20, 95
        sm.add_metric(m)
    score = sm.live_score()
    assert (score.value, score.target, score.streak, score.segmented) == (95, 60, 0.5, False)
    assert (score.time_above, score.longest_streak) == (2.0, 1.5)
    assert score.average == pytest.approx(74.0) == sm.compute_statistics()["avg_score"]  # the end card's average


def test_a_program_segment_starts_its_own_average_and_the_streak_carries_over():
    sm = SessionManager()
    sm.start(threshold=50)
    sm.start_segment("shamatha_score", 60)
    for m in ({"shamatha_score": 70}, {"shamatha_score": 80}):
        sm.add_metric(m)
    sm.start_segment("custom_formula", 10)
    sm.add_metric({"custom_formula": 12})
    score = sm.live_score()
    assert (score.average, score.segmented, score.target) == (12, True, 10)
    assert (score.streak, score.time_above) == (1.5, 1.5)  # one run across the boundary, as the scoring counts it


def test_the_live_average_rounds_as_the_end_cards_does():
    sm = SessionManager()
    sm.start(threshold=50)
    sm.set_active_goal("shamatha_score")
    for value in (63.4, 63.592, 63.496):  # mean 63.496: rounded once to 63, once via 63.50 to 64
        sm.add_metric({"shamatha_score": value})
    assert sm.live_score().average == sm.compute_statistics()["avg_score"]


def test_the_score_stays_after_the_stop_and_a_new_session_starts_with_none():
    sm = SessionManager()
    sm.start(threshold=50)
    sm.start_segment("shamatha_score", 60)
    sm.add_metric({"shamatha_score": 70})
    sm.stop()
    assert sm.live_score().time_above == 0.5  # the end of a session shows its numbers
    sm.start(threshold=50)
    assert sm.live_score() == NO_SCORE

# --- the record: key, display name and average, on every save path ---------------------------------------------

def test_the_saved_stats_carry_the_scored_metric_and_its_name(fresh_app, monkeypatch):
    fed = _session(fresh_app, monkeypatch, "custom_formula", CALM_RATIO)
    _run(fed, SHAMATHA_HIGH)
    row = _saved(fresh_app)
    assert (row["score_metric_key"], row["score_metric_name"]) == ("custom_formula", "Calm ratio")
    assert row["avg_score"] == pytest.approx(70.0)


def test_the_saved_name_of_the_scored_line_is_its_name_when_saved(fresh_app, monkeypatch):
    # Settings lets the scored slot's name change mid-session (not its formula): the session saves the new one.
    fed = _session(fresh_app, monkeypatch, "custom_formula", CALM_RATIO)
    _run(fed, SHAMATHA_HIGH)
    fresh_app._formula_settings.on_slot_change(0, "Evening ratio", CALM_RATIO[0]["formula"])
    assert _saved(fresh_app)["score_metric_name"] == "Evening ratio"


def _program_session(app, monkeypatch, name: str) -> FedSession:
    reload_with(app, threshold="50")
    program_mode(app, [{"minutes": 5, "target": 50, "formula": "shamatha_score"}])
    app._program_settings.name = name
    return FedSession(app, monkeypatch)


@pytest.mark.parametrize("name,recorded", [("Evening program", "Evening program"), ("", "Program")])
def test_a_program_session_records_program_its_name_and_no_average(fresh_app, monkeypatch, name, recorded):
    _run(_program_session(fresh_app, monkeypatch, name), SHAMATHA_HIGH)
    row = _saved(fresh_app)
    assert (row["score_metric_key"], row["score_metric_name"], row["avg_score"]) == ("program", recorded, None)


def test_a_program_session_keeps_the_name_of_the_program_it_ran(fresh_app, monkeypatch):
    # Settings loads or saves another program during the session: the editor's name changes, not the run's.
    _run(_program_session(fresh_app, monkeypatch, "Evening program"), SHAMATHA_HIGH)
    fresh_app._program_settings.name = "Morning program"
    assert _saved(fresh_app)["score_metric_name"] == "Evening program"


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
    # Before #51 no metric was saved: nothing is deduced for a simple session or a program.
    assert recorded_score({"score_metric_key": "", "session_program": "", "avg_meditation": 44.0}) is None
    assert recorded_score({"score_metric_key": "", "session_program": '[{"duration": 60}]'}) is None
    assert recorded_score({"score_metric_key": "program", "score_metric_name": "Evening ladder",
                           "avg_score": None}) == ("program", "Evening ladder", None)


def test_recomputing_from_the_stored_ticks_reproduces_the_stored_stats(fresh_app, monkeypatch):
    ticks = _ticks(shamatha_score=[60, 70, 10, 55, 56, 57, 20, 99], meditation_score=[0] * 8)
    stats = _run(_session(fresh_app, monkeypatch), ticks)
    time_above, streak = goal_stats([m[stats["score_metric_key"]] for m in ticks], stats["threshold_used"])
    assert (int(time_above), int(streak)) == (stats["time_above_threshold"], stats["longest_streak"])


def test_recomputing_from_ticks_stored_in_the_db_reproduces_the_stored_stats(fresh_app, monkeypatch):
    app = fresh_app
    ticks = _ticks(shamatha_score=[60, 70, 10, 55, 56, 57, 20, 99, 51, 52], meditation_score=[90] * 10)
    _run(_session(app, monkeypatch), ticks)
    row = _saved(app)
    stored = [m[row["score_metric_key"]] for m in app._db.get_session_metrics(row["id"])]
    time_above, streak = goal_stats(stored, row["threshold_used"])
    assert (int(time_above), int(streak)) == (row["time_above_threshold"], row["longest_streak"])
    assert row["score_metric_key"] == "shamatha_score"  # meditation (all 90) would give a different answer


# --- the real tick ---------------------------------------------------------------------------------------------

def _scored_on(app) -> str | None:
    return app._session.manager.compute_statistics()["score_metric_key"]


def test_a_simple_session_tick_scores_on_the_feedback_metric_and_marks_it(fresh_app, monkeypatch):
    fed = _session(fresh_app, monkeypatch, "meditation_score")
    marks = calls_of(monkeypatch, fresh_app._live_screen, "set_training_series")
    fed.tick(metrics=dict(SHAMATHA_HIGH[0]))
    assert _scored_on(fresh_app) == "meditation_score" and marks == [("meditation_score",)]


def test_a_program_session_tick_leaves_the_goal_to_the_program(fresh_app, monkeypatch):
    app = fresh_app
    reload_with(app, threshold="50", audio_metric="meditation_score")
    program_mode(app, [{"minutes": 5, "target": 60, "formula": "shamatha_score"}])
    FedSession(app, monkeypatch).tick(metrics=dict(SHAMATHA_HIGH[0]))
    score = app._session.manager.live_score()
    assert _scored_on(app) == "shamatha_score" and (score.segmented, score.target) == (True, 60)


def test_program_mode_with_no_usable_program_is_scored_like_a_simple_session(fresh_app, monkeypatch):
    app = fresh_app
    reload_with(app, threshold="50")
    program_mode(app, [])  # the Settings toggle; the session starts without a program
    FedSession(app, monkeypatch).tick(metrics=dict(SHAMATHA_HIGH[0]))
    assert _scored_on(app) == "shamatha_score" and not app._session.manager.live_score().segmented


def test_one_tick_scores_and_sounds_the_same_metric(fresh_app, monkeypatch):
    app = fresh_app
    fed = _session(app, monkeypatch)
    answers = iter(["shamatha_score", "meditation_score"])  # the driving metric changes mid-tick
    monkeypatch.setattr(app._session, "drive_key", lambda: next(answers, "meditation_score"))
    sounded = calls_of(monkeypatch, app._audio, "update")
    fed.tick(metrics={"shamatha_score": 11.0, "meditation_score": 77.0})
    assert _scored_on(app) == "shamatha_score"
    assert sounded[0][0] == 11.0  # the sound follows the scored metric's value


def test_the_partial_flush_saves_the_scored_metric(fresh_app, monkeypatch):
    app = fresh_app
    fed = _session(app, monkeypatch)
    app._session.recorder._flush_counter = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY) - 1  # this tick flushes
    fed.tick(metrics={"shamatha_score": 52.5})
    row = app._db.get_session(app._session.recorder.session_id)
    assert (row["score_metric_key"], row["score_metric_name"], row["avg_score"]) == ("shamatha_score", "Shamatha", 52.5)


@pytest.mark.parametrize("metric, formulas, recorded", [
    ("shamatha_score", (), ("shamatha_score", "Shamatha")),
    ("custom_formula", CALM_RATIO, ("custom_formula", "Calm ratio")),
], ids=["default", "formula"])
def test_a_session_stopped_before_any_tick_records_the_feedback_metric(fresh_app, monkeypatch, metric, formulas, recorded):
    sm = SessionManager()
    sm.start(threshold=50)
    stats = sm.compute_statistics()
    assert stats["score_metric_key"] is None and stats["avg_score"] is None  # nothing was scored
    _session(fresh_app, monkeypatch, metric, formulas)
    row = _saved(fresh_app)
    assert (row["score_metric_key"], row["score_metric_name"], row["avg_score"]) == (*recorded, None)
