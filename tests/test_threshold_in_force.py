"""The Settings threshold is the target in force for a simple session: the sound, the scoring and the SHAMATHA pill
follow it together, from the next tick, and a drag is one change at the value it settles on; a program's segments own
their targets. The live graph steps its threshold line where the ticks' target changes, and so does the session
detail."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch

import app.ui.app_manager as am
from app.config import APP
from app.session.manager import SessionManager, SessionState
from app.session.scoring import target_steps
from app.session.session_program import SessionProgram
from app.ui.app_manager import EEGMeditationApp
from app.ui.diary_screen import detail_graph_data
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.settings_screen import SettingsScreen
from tests.test_bt_wait_reconnect import wait  # noqa: F401  (fixture)
from tests.test_resume_mirror import _drive_tick, _make_tick_app, _metrics, _raw_sample
from tests.test_session_detail_open import _frames, app, db  # noqa: F401  (fixtures)


def _threshold_app(*, program: bool = False, state: SessionState = SessionState.RUNNING) -> EEGMeditationApp:
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._metrics_engine = MagicMock()
    a._audio = MagicMock()
    a._live_screen = MagicMock()
    a._persist_user_setting_later = MagicMock()
    a._loading_settings = False
    a._session_program_active = program
    a._ui_metrics_history, a._ui_band_history, a._ui_raw_waveform = deque(), deque(), deque()
    a._shamatha_threshold = 70
    a._metrics_engine.meditation_threshold = 70
    sm = SessionManager()
    sm.start(threshold=70)
    sm.set_active_goal("shamatha_score", 70 if program else None)
    sm._state = state
    a._session_manager = sm
    return a


def _next_target(a) -> float:
    return a._session_manager.add_metric({"shamatha_score": 60.0})["score_target"]


# ---- one path applies the threshold ----


def test_a_new_threshold_moves_a_simple_sessions_sound_scoring_and_pill_together():
    a = _threshold_app()
    a._apply_threshold(85)
    a._audio.set_threshold.assert_called_with(85)
    assert _next_target(a) == 85
    assert a._shamatha_threshold == 85 and a._metrics_engine.meditation_threshold == 85


def test_a_new_threshold_never_reaches_a_running_program():
    # A settle that lands late, or the profile's settings reloaded (re-picking the active profile), mid-program.
    a = _threshold_app(program=True)
    a._tick_thread = MagicMock()  # the program session is live
    a._apply_threshold(85)
    a._audio.set_threshold.assert_not_called()  # the sound kept the segment's 70 (it used to switch to 85)
    assert _next_target(a) == 70
    assert a._shamatha_threshold == 70 and a._metrics_engine.meditation_threshold == 70


def test_after_a_program_session_the_slider_applies_again():
    a = _threshold_app(program=True, state=SessionState.IDLE)  # _session_program_active stays set after the session
    a._apply_threshold(85)
    a._audio.set_threshold.assert_called_with(85)
    assert a._shamatha_threshold == 85


class _Trigger:
    """A Kivy Clock trigger whose settle window the test ends."""

    def __init__(self, fn, timeout):
        self.fn, self.armed = fn, False

    def cancel(self):
        self.armed = False

    def __call__(self):
        self.armed = True


def test_a_slider_drag_is_one_change_at_the_value_it_settles_on(monkeypatch):
    # A drag from 70 to 85 used to put every step in force: ticks scored against 72, 76, 81..., each a step of the line.
    triggers: list[_Trigger] = []
    monkeypatch.setattr(am, "Clock", SimpleNamespace(create_trigger=lambda fn, t: triggers.append(_Trigger(fn, t))
                                                     or triggers[-1]))
    a = _threshold_app()
    a._settings_screen = MagicMock(threshold=85)
    for v in range(71, 86):
        a._on_threshold_change(v)
        assert _next_target(a) == 70  # still the value in force while the slider moves
    for t in triggers:
        if t.armed:
            t.fn(0)
    a._audio.set_threshold.assert_called_once_with(85)
    assert _next_target(a) == 85
    assert a._session_manager.compute_statistics()["score_targets"] == "[70, 85]"
    a._persist_user_setting_later.assert_called_with("threshold")


def test_a_session_waiting_for_the_headset_starts_with_the_threshold_set_during_the_wait(wait):  # noqa: F811
    a, stream, tick = wait
    a._shamatha_threshold = 70
    a._settings_screen = MagicMock(threshold=70)
    a._metrics_engine = MagicMock()
    a._audio = MagicMock()
    a._persist_user_setting_later = MagicMock()
    a._session_program_active = False
    tick(6.0, connected=True)
    a._apply_threshold(85)
    tick(7.0, connected=True, bands=5.0, packet=True)
    assert a._session_manager.state == SessionState.RUNNING
    assert _next_target(a) == 85


# ---- the tick: stored row, mirror, live graph ----


def _tick_app() -> EEGMeditationApp:
    a = _make_tick_app()
    sm = SessionManager()
    sm.start(threshold=70)
    a._session_manager = sm
    a._session_program_active = False
    a._metrics_engine = MagicMock()
    a._persist_user_setting_later = MagicMock()
    return a


def _ui_updates(a) -> list:
    """Run the UI updates the ticks queued, as the main thread would."""
    for call in a._on_main.call_args_list:
        call.args[0]()
    return a._live_screen.graph.add_point.call_args_list


def test_each_ticks_row_and_mirror_point_record_its_target():
    a = _tick_app()
    for i in range(3):
        if i == 2:
            a._apply_threshold(85)
        _drive_tick(a, _raw_sample(), _metrics(seed=80.0))
    assert [(r["score_key"], r["score_value"], r["score_target"]) for r in a._metrics_buffer] == [
        ("shamatha_score", 80.0, 70), ("shamatha_score", 80.0, 70), ("shamatha_score", 80.0, 85)]
    assert [m["score_target"] for m in a._ui_metrics_history] == [70, 70, 85]
    assert [c.kwargs["threshold"] for c in _ui_updates(a)] == [70, 70, 85]


def test_a_tick_the_session_paused_under_is_not_recorded():
    # The pause lands between the tick's RUNNING check and its scoring: the tick isn't part of the session, so it
    # leaves no row and no graph point (it used to be stored, unscored).
    a = _tick_app()
    real_add = a._session_manager.add_metric

    def pause_first(metric):
        a._session_manager.pause()
        return real_add(metric)

    a._session_manager.add_metric = pause_first
    a._pending_marker = True
    _drive_tick(a, _raw_sample(), _metrics())
    assert a._metrics_buffer == [] and len(a._ui_metrics_history) == 0
    a._on_main.assert_not_called()
    assert a._pending_marker  # it goes on the next tick that is recorded


def test_the_live_graph_reloaded_from_the_mirror_steps_its_line():
    # After a screen lock the graph is refilled from the mirror: the steps come back with the data.
    a = _tick_app()
    for i in range(4):
        if i == 2:
            a._apply_threshold(85)
        _drive_tick(a, _raw_sample(), _metrics(seed=80.0))
    a._reload_live_graphs_from_mirror()
    a._live_screen.graph.set_threshold_steps.assert_called_with([(0, 70), (2, 85)])


# ---- the graph ----


def _graph() -> ScrollableGraphWidget:
    return ScrollableGraphWidget(colors={"shamatha_score": (1, 0, 0, 1)}, scales={"shamatha_score": 100.0})


def test_points_with_a_threshold_step_the_line_where_it_changes():
    g = _graph()
    targets = [70, 70, 85, 85, 72]
    for t in targets:
        g.add_point({"shamatha_score": 60.0}, threshold=t)
    assert g._threshold_steps == target_steps(targets) == [(0, 70), (2, 85), (4, 72)]
    assert g.threshold_value_at(1) == 70 and g.threshold_value_at(3) == 85


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
    a._on_session_select(sid)
    workers.pop()()
    _frames(3)
    graph = a._diary_screen._metrics_graph
    assert graph._threshold_steps == [(0, 70), (2, 85)]
    assert ("Threshold", "70 › 85") in [(t.text, v.text) for t, v in a._diary_screen._detail_rows]


def test_a_session_saved_before_the_targets_keeps_its_line(app):  # noqa: F811
    a, workers = app
    a._on_session_select(a.sessions["A"])  # rows without targets, threshold_used 70
    workers.pop()()
    _frames(3)
    graph = a._diary_screen._metrics_graph
    assert graph._threshold_steps is None and graph._threshold_value == 70.0


def _start(program: bool, monkeypatch, prepare=None, **before) -> EEGMeditationApp:
    """Run the real session start (mock headset) with everything around it stubbed."""
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    a = _threshold_app(state=SessionState.IDLE)
    a._session_manager.reset()
    a._settings_screen = MagicMock(threshold=70, timer_enabled=False, timer_minutes=20)
    prog = SessionProgram([{"minutes": 5, "formula": "shamatha_score", "target": 60},
                           {"minutes": 5, "formula": "meditation_score", "target": 80}])
    a._build_session_program = lambda: prog
    a._timer_mode = "program" if program else "simple"
    a._timer_state = MagicMock()
    for name in ("_show_program_series", "_warn_missing_sound_files", "_acquire_wake_lock",
                 "_start_session_keep_alive_service", "_start_tick_thread"):
        setattr(a, name, MagicMock())
    a._global_feedback_id = lambda: "noise"
    a._source_spec = lambda sid: ("noise", "")
    a._feedback_plan = lambda p, gid: ({gid: ("noise", "")}, ["noise", "noise"], gid)
    a._reward_id = lambda: ""
    a._eeg_stream = MagicMock()
    a._ui_metrics_history, a._ui_band_history, a._ui_raw_waveform = deque(), deque(), deque()
    a._live_screen.graph.set_threshold_steps([(0, 50)])  # the last session's steps
    for name, value in before.items():
        setattr(a, name, value)
    if prepare is not None:
        prepare(a)
    a._start_session_common()
    return a


@pytest.mark.parametrize("program, first_target", [(False, 70), (True, 60)])
def test_a_session_start_clears_the_last_sessions_steps(program, first_target, monkeypatch):
    # Both kinds step their line from the ticks: a program no longer draws its segments upfront.
    a = _start(program, monkeypatch)
    graph = a._live_screen.graph
    assert graph.set_threshold_steps.call_args_list[-1].args == (None,)
    graph.set_threshold.assert_called_with(float(first_target), "shamatha_score")
    a._audio.set_threshold.assert_called_with(first_target)
    assert a._shamatha_threshold == first_target
    assert a._session_manager.state == SessionState.RUNNING
    assert _next_target(a) == first_target


def test_an_old_session_opened_after_a_new_one_does_not_keep_its_steps(app):  # noqa: F811
    a, workers = app
    sid = a._db.checkpoint_session(None, {"duration": 2, "threshold_used": 70, "score_targets": "[70, 85]"},
                                   _rows([70, 85]), user_id=a._current_user_id, session_name="s")
    a._on_session_select(sid)
    workers.pop()()
    _frames(3)
    a._on_diary_back()
    a._on_session_select(a.sessions["A"])
    workers.pop()()
    _frames(3)
    assert a._diary_screen._metrics_graph._threshold_steps is None


def test_a_settle_runs_the_latest_function_given_for_its_input(monkeypatch):
    triggers: list[_Trigger] = []
    monkeypatch.setattr(am, "Clock", SimpleNamespace(create_trigger=lambda fn, t: triggers.append(_Trigger(fn, t))
                                                     or triggers[-1]))
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    ran = []
    a._after_settle("x", lambda: ran.append(1))
    a._after_settle("x", lambda: ran.append(2))
    assert len(triggers) == 1
    triggers[0].fn(0)
    assert ran == [2]


def test_a_touch_on_the_locked_controls_says_why_while_the_program_runs():
    a = _threshold_app(program=True)
    a._tick_thread = MagicMock()
    a._info_popup = MagicMock()
    assert a._refuse_program_threshold() is True
    assert a._info_popup.call_args.args == (
        "Session in progress", "This program sets its own targets. Stop the current session before changing the "
                               "threshold.")


def test_a_touch_after_the_program_ended_is_not_refused():
    # The timer ended it on the tick thread; the unlock is still queued for the main thread.
    a = _threshold_app(program=True, state=SessionState.FINISHED)
    a._info_popup = MagicMock()
    assert a._refuse_program_threshold() is False
    a._info_popup.assert_not_called()


def test_a_session_start_applies_its_threshold_whatever_the_last_one_left_running(monkeypatch):
    a = _start(True, monkeypatch, _tick_thread=MagicMock())  # the last session's tick thread hasn't exited yet
    a._audio.set_threshold.assert_called_with(60)


@pytest.mark.parametrize("program", [False, True])
def test_a_program_session_locks_the_threshold_controls_and_its_end_unlocks_them(program, monkeypatch):
    a = _start(program, monkeypatch)
    a._settings_screen.lock_threshold.assert_called_with(a._refuse_program_threshold if program else None)
    a._settings_screen.lock_threshold.reset_mock()
    for name in ("_restore_program_series", "_release_wake_lock", "_stop_session_keep_alive_service"):
        setattr(a, name, MagicMock())
    a._start_attempt = 1
    a._undo_session_setup()  # every ending
    a._settings_screen.lock_threshold.assert_called_with(None)


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


def test_a_slider_move_just_before_starting_a_program_is_not_applied_during_it(monkeypatch):
    # The settle window ended after Start: the program refused the pending value and said "Saved for your next
    # session" about a change made before it started.
    triggers: list[_Trigger] = []
    monkeypatch.setattr(am, "Clock", SimpleNamespace(create_trigger=lambda fn, t: triggers.append(_Trigger(fn, t))
                                                     or triggers[-1]))
    a = _start(True, monkeypatch, prepare=lambda app_: app_._on_threshold_change(80))
    assert len(triggers) == 1 and not triggers[0].armed  # the slider's pending apply, cancelled by Start


def test_a_running_session_ignores_another_start():
    sm = SessionManager()
    sm.start(threshold=70)
    sm.start(threshold=40)
    assert sm.add_metric({"shamatha_score": 60.0})["score_target"] == 70


def test_a_program_start_that_fails_in_its_setup_leaves_the_controls_unlocked(monkeypatch):
    started = {}

    def prepare(app_):
        app_._show_program_series.side_effect = RuntimeError("bad custom sound file")
        started["app"] = app_

    with pytest.raises(RuntimeError):
        _start(True, monkeypatch, prepare=prepare)
    started["app"]._settings_screen.lock_threshold.assert_not_called()


def _idle_app() -> EEGMeditationApp:
    a = _threshold_app(state=SessionState.FINISHED)  # the last session ended; its graphs are still on screen
    a._ui_metrics_history, a._ui_band_history, a._ui_raw_waveform = deque([{}]), deque([{}]), deque([0.0])
    a._after_settle = MagicMock()
    return a


def test_moving_the_slider_while_idle_clears_the_last_sessions_graphs():
    a = _idle_app()
    a._on_threshold_change(85)  # Kivy calls it only when the slider's value changes
    for graph in (a._live_screen.graph, a._live_screen.raw_graph, a._live_screen.band_graph):
        graph.clear_data.assert_called_once()
    a._live_screen.graph.set_threshold_steps.assert_called_with(None)
    assert not a._ui_metrics_history and not a._ui_band_history and not a._ui_raw_waveform
    a._apply_threshold(85)  # the settled value
    a._live_screen.graph.set_threshold.assert_called_with(85.0, "shamatha_score")


def test_reapplying_the_settings_threshold_keeps_the_graphs():
    # After a program, the threshold in force is a segment's target (85) while Settings shows 70: re-picking the
    # profile reloads its settings and applies 70, which is no change of the Settings threshold.
    a = _idle_app()
    a._session_manager.set_threshold(85)
    a._apply_threshold(70)
    a._live_screen.graph.clear_data.assert_not_called()


def test_nothing_to_clear_before_any_session():
    a = _idle_app()
    a._ui_metrics_history.clear()
    a._on_threshold_change(85)
    a._live_screen.graph.clear_data.assert_not_called()


def test_moving_the_slider_during_a_simple_session_keeps_its_graphs():
    a = _threshold_app()
    a._after_settle = MagicMock()
    a._ui_metrics_history.append({})
    a._on_threshold_change(85)
    a._live_screen.graph.clear_data.assert_not_called()
    a._live_screen.graph.set_threshold_steps.assert_not_called()
