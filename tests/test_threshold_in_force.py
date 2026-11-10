"""The Settings threshold is the target in force for a simple session: the sound, the scoring and the SHAMATHA pill
follow it together, from the next tick, and a drag is one change at the value it settles on; a program's segments own
their targets. The live graph steps its threshold line where the ticks' target changes, and so does the session
detail."""

from types import SimpleNamespace

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch

from app.session.manager import SessionManager, SessionState
from app.session.scoring import target_steps
from app.ui.diary_screen import detail_graph_data
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.settings_screen import SettingsScreen
from tests._app import (
    FedSession,
    calls_of,
    frames,
    frames_until,
    popup_message,
    popups,
    program_mode,
    reload_with,
    tick_metrics,
)
from tests.test_bt_wait_reconnect import wait  # noqa: F401  (fixture)
from tests.test_session_detail_open import (  # noqa: F401  (fixture)
    _frames,
    _select,
    app,
)

SETTLE_S = 0.5  # the app's settle window (EEGMeditationApp._PERSIST_SETTLE_S)
SEGMENTS = [{"minutes": 5, "formula": "shamatha_score", "target": 60},
            {"minutes": 5, "formula": "meditation_score", "target": 80}]


def _simple(app_, monkeypatch, threshold: int = 70) -> FedSession:
    """A simple session against the Settings threshold, its ticks the test's."""
    reload_with(app_, threshold=str(threshold))
    return FedSession(app_, monkeypatch)


def _program(app_, monkeypatch, segments=SEGMENTS, threshold: int = 70) -> FedSession:
    """A program session (the Settings threshold beside it), its ticks the test's."""
    reload_with(app_, threshold=str(threshold))
    program_mode(app_, segments)
    return FedSession(app_, monkeypatch)


def _next_target(app_) -> float:
    return app_._session_manager.add_metric({"shamatha_score": 60.0})["score_target"]


def _settled(app_) -> None:
    """Until the slider's settle window has passed."""
    frames_until(lambda: False, SETTLE_S + 0.2)


def test_the_shamatha_pill_crosses_at_the_base_in_force(fresh_app, monkeypatch):
    fed = _simple(fresh_app, monkeypatch, threshold=50)
    calm = {**tick_metrics(), "shamatha_score": 60.0}
    for _ in range(3):  # three ticks above the base of 50: the pill comes on
        fed.tick(metrics=calm)
    assert fresh_app._run.shamatha_active
    fresh_app._apply_threshold(70)  # the slider settled above the score
    for _ in range(3):
        fed.tick(metrics=calm)
    assert not fresh_app._run.shamatha_active


def test_the_sound_and_the_engine_read_the_ticks_target_and_the_base(fresh_app, monkeypatch):
    # A segment's target reaches the sound through the tick it is scored on; the engine's state keeps the base.
    app_ = fresh_app
    fed = _program(app_, monkeypatch, [{"minutes": 1, "formula": "shamatha_score", "target": 70},
                                       {"minutes": 1, "formula": "shamatha_score", "target": 60}])
    sounded = calls_of(monkeypatch, app_._audio, "update")
    fed.tick()  # the first segment: its target is the base the session started with
    assert sounded[-1][1] == 70 and fed.thresholds[-1] == 70
    app_._session_manager._start_time -= 61  # the next tick is in the second segment, with its own target
    fed.tick()
    assert sounded[-1][1] == 60 and fed.thresholds[-1] == 70
    between = {**tick_metrics(), "shamatha_score": 65.0}  # above the segment's 60, below the base's 70
    for _ in range(3):
        fed.tick(metrics=between)
    assert not app_._run.shamatha_active  # the pill keeps the base, not a segment's target


# ---- one path applies the threshold ----


def test_a_new_threshold_is_the_next_ticks_target_and_the_base(fresh_app, monkeypatch):
    _simple(fresh_app, monkeypatch)
    fresh_app._apply_threshold(85)
    assert _next_target(fresh_app) == 85 and fresh_app._session_manager.threshold == 85  # the one owner, read per tick


def test_a_new_threshold_never_reaches_a_running_program(fresh_app, monkeypatch):
    # A settle that lands late, or the profile's settings reloaded (re-picking the active profile), mid-program.
    fed = _program(fresh_app, monkeypatch)
    fed.tick()
    fresh_app._apply_threshold(85)
    assert _next_target(fresh_app) == 60 and fresh_app._session_manager.threshold == 60  # the segment's stays in force


def test_after_a_program_session_the_slider_applies_again(fresh_app, monkeypatch):
    app_ = fresh_app
    _program(app_, monkeypatch).tick()
    app_._stop_and_save()
    frames()
    app_._apply_threshold(85)
    assert app_._session_manager.threshold == 85


def test_a_slider_drag_is_one_change_at_the_value_it_settles_on(fresh_app, monkeypatch):
    # A drag from 70 to 85 used to put every step in force: ticks scored against 72, 76, 81..., each a step of the line.
    app_ = fresh_app
    _simple(app_, monkeypatch)
    for v in range(71, 86):
        app_._settings_screen.threshold = v
        assert _next_target(app_) == 70  # still the value in force while the slider moves
    _settled(app_)
    assert _next_target(app_) == 85
    assert app_._session_manager.compute_statistics()["score_targets"] == "[70, 85]"
    assert app_._db.get_user_setting(app_._current_user_id, "threshold") == "85"  # written once it settled too


def test_a_session_waiting_for_the_headset_starts_with_the_threshold_set_during_the_wait(wait):  # noqa: F811
    a, stream, tick = wait
    tick(6.0, connected=True)
    a._apply_threshold(85)
    tick(7.0, connected=True, bands=5.0, packet=True)
    assert a._session_manager.state == SessionState.RUNNING
    assert _next_target(a) == 85


# ---- the tick: stored row, mirror, live graph ----


def _points_drawn(app_, monkeypatch) -> list[tuple]:
    """Each point the live graph is given from here on, as (threshold, scored series)."""
    drawn, add = [], app_._live_screen.graph.add_point
    monkeypatch.setattr(app_._live_screen.graph, "add_point",
                        lambda m, **kw: (drawn.append((kw.get("threshold"), kw.get("scored"))), add(m, **kw))[1])
    return drawn


def test_each_ticks_row_and_mirror_point_record_its_target(fresh_app, monkeypatch):
    app_ = fresh_app
    fed = _simple(app_, monkeypatch)
    drawn = _points_drawn(app_, monkeypatch)
    for i in range(3):
        if i == 2:
            app_._apply_threshold(85)
        fed.tick(metrics=tick_metrics(seed=80.0))
    assert [(r["score_key"], r["score_value"], r["score_target"]) for r in app_._recorder._buffer] == [
        ("shamatha_score", 80.0, 70), ("shamatha_score", 80.0, 70), ("shamatha_score", 80.0, 85)]
    assert [(m["score_target"], m["score_key"]) for m in app_._shown.mirror.metrics] == [
        (70, "shamatha_score"), (70, "shamatha_score"), (85, "shamatha_score")]
    assert drawn == [(70, "shamatha_score"), (70, "shamatha_score"), (85, "shamatha_score")]


def test_each_ticks_screen_update_shows_the_score_as_of_that_tick(fresh_app, monkeypatch):
    """The score is taken with the tick, not when the main thread gets to it (#113)."""
    app_ = fresh_app
    fed = _simple(app_, monkeypatch)
    shown = calls_of(monkeypatch, app_._live_screen, "update_stats")
    for _ in range(3):
        fed.tick(metrics=tick_metrics(seed=80.0), shown=False)  # the main thread held
    frames()
    assert [score.time_above for (score,) in shown] == [0.5, 1.0, 1.5]


def test_a_programs_ticks_carry_each_segments_scored_series_to_the_graph_and_the_mirror(fresh_app, monkeypatch):
    """The live line's colouring per point (#113): a tick past the boundary is scored, drawn and mirrored on the next
    segment's series."""
    app_ = fresh_app
    fed = _program(app_, monkeypatch, [{"minutes": 1, "target": 70, "formula": "shamatha_score"},
                                       {"minutes": 1, "target": 60, "formula": "meditation_score"}])
    drawn = _points_drawn(app_, monkeypatch)
    fed.tick(metrics=tick_metrics(seed=80.0))
    app_._session_manager._start_time -= 61  # the next tick is past the first segment's minute
    fed.tick(metrics={**tick_metrics(seed=80.0), "meditation_score": 55.0})
    keys = ["shamatha_score", "meditation_score"]
    assert [m["score_key"] for m in app_._shown.mirror.metrics] == keys
    assert [scored for _threshold, scored in drawn] == keys


def test_a_tick_the_session_paused_under_is_not_recorded(fresh_app, monkeypatch):
    # The pause lands between the tick's RUNNING check and its scoring: the tick isn't part of the session, so it
    # leaves no row and no graph point (it used to be stored, unscored).
    app_ = fresh_app
    fed = _simple(app_, monkeypatch)
    real_add = app_._session_manager.add_metric

    def pause_first(metric):
        app_._session_manager.pause()
        return real_add(metric)

    monkeypatch.setattr(app_._session_manager, "add_metric", pause_first)
    app_._on_marker()
    fed.tick()
    assert app_._recorder._buffer == [] and len(app_._shown.mirror.metrics) == 0
    assert app_._live_screen.graph.total_points == 0
    assert app_._run.pending_marker  # it goes on the next tick that is recorded


def test_the_live_graph_reloaded_from_the_mirror_steps_its_line(fresh_app, monkeypatch):
    # After a screen lock the graph is refilled from the mirror: the steps come back with the data.
    app_ = fresh_app
    fed = _simple(app_, monkeypatch)
    for i in range(4):
        if i == 2:
            app_._apply_threshold(85)
        fed.tick(metrics=tick_metrics(seed=80.0))
    app_._live_screen.graph.set_threshold_steps(None)
    app_._shown.mirror.reload_into(app_._live_screen)
    assert app_._live_screen.graph._threshold_steps == [(0, 70), (2, 85)]


# ---- the graph ----


def _graph() -> ScrollableGraphWidget:
    return ScrollableGraphWidget(colors={"shamatha_score": (1, 0, 0, 1)}, scales={"shamatha_score": 100.0})


def test_points_with_a_threshold_step_the_line_where_it_changes():
    g = _graph()
    targets = [70, 70, 85, 85, 72]
    for t in targets:
        g.add_point({"shamatha_score": 60.0}, threshold=t)
    assert g._threshold_steps == target_steps(targets) == [(0, 70), (2, 85), (4, 72)]


def test_points_without_a_threshold_leave_the_line_as_set():
    g = _graph()
    g.set_threshold(70.0)
    g.add_point({"shamatha_score": 60.0})
    assert g._threshold_steps is None and g._threshold_value == 70.0


# ---- the session detail ----


def _rows(targets) -> list[dict]:
    return [{"timestamp": i * 0.5, "shamatha_score": 60.0, "score_key": "shamatha_score", "score_value": 60.0,
             "score_target": t} for i, t in enumerate(targets)]


def test_the_detail_data_steps_the_line_from_the_ticks():
    assert detail_graph_data(_rows([70, 70, 85]), {})["threshold_steps"] == [(0, 70), (2, 85)]
    assert detail_graph_data(_rows([None, None]), {})["threshold_steps"] is None  # saved before targets were recorded


def test_the_detail_draws_a_sessions_threshold_steps(app):  # noqa: F811
    a, workers = app
    sid = a._db.checkpoint_session(None, {"duration": 2, "threshold_used": 70, "score_metric_key": "shamatha_score",
                                          "score_metric_name": "Shamatha", "avg_score": 60.0,
                                          "score_targets": "[70, 85]"},
                                   _rows([70, 70, 85, 85]), user_id=a._current_user_id, session_name="s")
    _select(a, sid)
    workers.pop()()
    _frames(3)
    graph = a._diary_screen._metrics_graph
    assert graph._threshold_steps == [(0, 70), (2, 85)]
    assert ("Threshold", "70 › 85") in [(t.text, v.text) for t, v in a._diary_screen._detail_rows]


def test_a_session_saved_before_the_targets_keeps_its_line(app):  # noqa: F811
    a, workers = app
    _select(a, a.sessions["A"])  # rows without targets, threshold_used 70
    workers.pop()()
    _frames(3)
    graph = a._diary_screen._metrics_graph
    assert graph._threshold_steps is None and graph._threshold_value == 70.0


# ---- a session's start and its ending ----


@pytest.mark.parametrize("program, first_target", [(False, 70), (True, 60)])
def test_a_session_start_puts_its_threshold_in_force_and_clears_the_last_sessions_steps(program, first_target,
                                                                                        fresh_app, monkeypatch):
    # Both kinds step their line from the ticks: a program no longer draws its segments upfront. The start applies its
    # own threshold, whatever the last session left in force.
    app_ = fresh_app
    graph = app_._live_screen.graph
    reload_with(app_, threshold="70")
    app_._session_manager.set_threshold(33)  # what the last session left
    graph.set_threshold_steps([(0, 50)])  # and its steps
    if program:
        program_mode(app_, SEGMENTS)
    FedSession(app_, monkeypatch)
    assert graph._threshold_steps is None and graph._threshold_value == float(first_target)
    assert app_._session_manager.threshold == first_target
    assert app_._session_manager.state == SessionState.RUNNING
    assert _next_target(app_) == first_target


def test_an_old_session_opened_after_a_new_one_does_not_keep_its_steps(app):  # noqa: F811
    a, workers = app
    sid = a._db.checkpoint_session(None, {"duration": 2, "threshold_used": 70, "score_targets": "[70, 85]"},
                                   _rows([70, 85]), user_id=a._current_user_id, session_name="s")
    _select(a, sid)
    workers.pop()()
    _frames(3)
    a._detail.on_diary_back()
    _select(a, a.sessions["A"])
    workers.pop()()
    _frames(3)
    assert a._diary_screen._metrics_graph._threshold_steps is None


def test_a_settle_runs_the_latest_function_given_for_its_input(fresh_app):
    ran = []
    fresh_app._after_settle("x", lambda: ran.append(1))
    fresh_app._after_settle("x", lambda: ran.append(2))
    assert ran == []
    _settled(fresh_app)
    assert ran == [2]


def test_a_touch_on_the_locked_controls_says_why_while_the_program_runs(fresh_app, monkeypatch):
    _program(fresh_app, monkeypatch)
    assert fresh_app._refuse_program_threshold() is True
    (popup,) = popups()
    assert (popup.title, popup_message(popup)) == (
        "Session in progress", "This program sets its own targets. Stop the current session before changing the "
                               "threshold.")


def test_a_touch_after_the_program_ended_is_not_refused(fresh_app, monkeypatch):
    # The timer ended it on the tick thread; the unlock is still queued for the main thread.
    fed = _program(fresh_app, monkeypatch)
    fed.end_by_timer_on_next_tick()
    fed.tick(shown=False)
    assert fresh_app._session_manager.state == SessionState.FINISHED
    assert fresh_app._refuse_program_threshold() is False and popups() == []


@pytest.mark.parametrize("program", [False, True])
def test_a_program_session_locks_the_threshold_controls_and_its_end_unlocks_them(program, fresh_app, monkeypatch):
    app_ = fresh_app
    (_program if program else _simple)(app_, monkeypatch)
    lock = app_._settings_screen._threshold_lock
    assert (lock == app_._refuse_program_threshold) if program else (lock is None)
    app_._stop_and_save()  # every ending
    frames()
    assert app_._settings_screen._threshold_lock is None


def test_the_locked_controls_take_no_touch_and_each_touch_says_why():
    # During a program: a drag, a -/+ click or a preset used to move the slider; several of them could change the
    # threshold with one easily missed message. Now nothing moves, and every touch says why.
    screen = SettingsScreen()
    EventLoop.ensure_window()
    Window.add_widget(screen)
    try:
        next(x for x in screen.walk() if type(x).__name__ == "_AccordionSection"
             and x._header.text == "Threshold").open()
        for _ in range(8):
            EventLoop.idle()
        slider_row, presets = screen._threshold_controls
        minus, slider, _label, plus = reversed(slider_row.children)
        preset = presets.children[0]

        def tap(widget, dx=0.0):
            x, y = widget.to_window(widget.center_x + dx, widget.center_y)
            touch = UnitTestTouch(x, y)
            touch.touch_down()
            touch.touch_up()
            for _ in range(2):
                EventLoop.idle()

        screen.threshold = 70
        refused = []
        screen.lock_threshold(lambda: refused.append(1) or True)
        for widget, dx in ((minus, 0), (plus, 0), (slider, slider.width / 3), (preset, 0)):
            tap(widget, dx)
        assert screen.threshold == 70 and len(refused) == 4
        assert slider_row.opacity == presets.opacity == 0.5
        wheel = SimpleNamespace(is_mouse_scrolling=True, pos=slider.center)  # a mouse wheel steps a slider
        assert screen._on_threshold_controls_touch(slider_row, wheel) is True and len(refused) == 5
        screen.lock_threshold(lambda: False)  # the program has just ended: the touch goes through
        tap(plus)
        assert screen.threshold == 75
        screen.lock_threshold(None)
        tap(plus)
        assert screen.threshold == 80 and slider_row.opacity == 1.0
    finally:
        Window.remove_widget(screen)


def test_a_slider_move_just_before_starting_a_program_is_not_applied_during_it(fresh_app, monkeypatch):
    # The settle window ended after Start: the program refused the pending value and said "Saved for your next
    # session" about a change made before it started.
    app_ = fresh_app
    reload_with(app_, threshold="70")
    program_mode(app_, SEGMENTS)
    app_._settings_screen.threshold = 80  # its apply is still pending
    FedSession(app_, monkeypatch)
    _settled(app_)
    assert app_._session_manager.threshold == 60 and popups() == []  # the slider's pending apply, cancelled by Start


def test_a_running_session_ignores_another_start():
    sm = SessionManager()
    sm.start(threshold=70)
    sm.start(threshold=40)
    assert sm.add_metric({"shamatha_score": 60.0})["score_target"] == 70


def test_a_program_start_that_fails_in_its_setup_leaves_the_controls_unlocked(fresh_app, monkeypatch):
    app_ = fresh_app
    program_mode(app_, SEGMENTS)

    def failing(*_args):
        raise RuntimeError("bad custom sound file")

    monkeypatch.setattr(app_._program_run, "begin", failing)
    with pytest.raises(RuntimeError):
        app_._on_start()
    assert app_._settings_screen._threshold_lock is None


def test_a_session_start_holds_the_phone_awake(fresh_app, monkeypatch):
    holds = calls_of(monkeypatch, fresh_app._keep_awake, "hold")
    _simple(fresh_app, monkeypatch)
    assert len(holds) == 1  # the wake lock, the screen-on flag, the foreground service


# ---- the last session's graphs, while idle ----


def _ended(app_, monkeypatch, fed_session=_simple) -> None:
    """A session of three ticks, ended, its card closed: its graphs are still on screen."""
    fed = fed_session(app_, monkeypatch)
    for _ in range(3):
        fed.tick()
    app_._stop_and_save()
    frames()
    app_._shown.on_ok()
    assert app_._live_screen.graph.total_points == 3


def _live_points(app_) -> list[int]:
    screen = app_._live_screen
    return [screen.graph.total_points, screen.raw_graph.total_points, screen.band_graph.total_points]


def test_moving_the_slider_while_idle_clears_the_last_sessions_graphs(fresh_app, monkeypatch):
    app_ = fresh_app
    _ended(app_, monkeypatch)
    app_._settings_screen.threshold = 85
    mirror = app_._shown.mirror
    assert _live_points(app_) == [0, 0, 0] and app_._live_screen.graph._threshold_steps is None
    assert not mirror.metrics and not mirror.bands and not mirror.waveform
    _settled(app_)  # the settled value
    assert app_._live_screen.graph._threshold_value == 85.0 and app_._session_manager.threshold == 85


def test_reapplying_the_settings_threshold_keeps_the_graphs(fresh_app, monkeypatch):
    # After a program, the threshold in force is a segment's target (60) while Settings shows 70: re-picking the
    # profile reloads its settings and applies 70, which is no change of the Settings threshold.
    app_ = fresh_app
    _ended(app_, monkeypatch, _program)
    assert app_._session_manager.threshold == 60
    app_._activate_user(app_._current_user_id)
    _settled(app_)
    assert app_._live_screen.graph.total_points == 3 and app_._session_manager.threshold == 70


def test_nothing_to_clear_before_any_session(fresh_app, monkeypatch):
    cleared = calls_of(monkeypatch, fresh_app._live_screen.graph, "clear_data")
    fresh_app._settings_screen.threshold = 85
    assert cleared == []


def test_moving_the_slider_during_a_simple_session_keeps_its_graphs(fresh_app, monkeypatch):
    app_ = fresh_app
    fed = _simple(app_, monkeypatch)
    for _ in range(3):
        fed.tick()
    steps = app_._live_screen.graph._threshold_steps
    app_._settings_screen.threshold = 85
    assert app_._live_screen.graph.total_points == 3 and app_._live_screen.graph._threshold_steps == steps
