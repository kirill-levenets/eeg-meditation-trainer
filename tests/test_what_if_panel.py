"""The session detail's what-if panel: a threshold slider, -/+ and Reset over the time above threshold and longest streak
the session's ticks give at it — one control for a simple session, one per segment for a program. It starts as recorded,
the graph's line follows it, and nothing is written."""

import json

from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch

import app.ui.app_manager as am
from app.session.what_if import ScoredTicks, Segment
from app.settings.registry import BOOL, Setting, SettingsStore
from app.ui.theme import Icons
from app.ui.widgets.what_if import WhatIfPanel
from tests.test_session_detail_open import app, db  # noqa: F401  (fixtures)

VALUES = [60, 72, 75, 80, 50, 90, 91, 92, 40, 88, 95, 96, 97, 30, 99]
NOTE = "Recorded at 70 · nothing is saved"


def _ticks(targets=None) -> ScoredTicks:
    targets = targets or [70] * len(VALUES)
    return ScoredTicks(list(VALUES), list(targets), [Segment("shamatha_score", targets[0], 0, len(VALUES))])


def _frames(n: int = 2) -> None:
    for _ in range(n):
        EventLoop.idle()


def _results(panel: WhatIfPanel) -> tuple[str, str]:
    return panel._time_above.text, panel._streak.text


def _panel(lines: list, ticks: ScoredTicks | None = None, note: str = NOTE, titles=None) -> WhatIfPanel:
    p = WhatIfPanel(on_threshold=lines.append)
    p.set_session(ticks or _ticks(), note, titles)
    _frames()
    return p


def _control(p: WhatIfPanel, i: int = 0):
    return p._seg_controls[i]


def test_it_starts_as_recorded():
    lines = []
    p = _panel(lines)
    c = _control(p)
    assert c.slider.value == 70 and c.value_label.text == "70" and len(p._seg_controls) == 1
    assert p._note.text == NOTE
    assert _results(p) == ("5s", "2s")  # >= 70: 11 ticks (5.5 s), the longest run 88 95 96 97 (2 s)
    assert p._btn_reset.disabled and lines == []


def test_moving_the_slider_rescores_and_moves_the_graphs_line():
    lines = []
    p = _panel(lines)
    _control(p).slider.value = 90
    _frames()
    assert _control(p).value_label.text == "90" and _results(p) == ("3s", "1s")  # 7 ticks (3.5 s), runs of 3 (1.5 s)
    assert lines[-1] == [(0, 90)] and not p._btn_reset.disabled


def test_minus_and_plus_step_by_five():
    lines = []
    p = _panel(lines)
    _control(p).step(+5)
    _frames()
    assert _control(p).slider.value == 75 and lines[-1] == [(0, 75)]
    _control(p).step(-10)
    _frames()
    assert _control(p).slider.value == 65


def test_reset_goes_back_to_as_recorded():
    lines = []
    p = _panel(lines)
    _control(p).slider.value = 90
    _frames()
    p.reset()
    _frames()
    assert _control(p).slider.value == 70 and _results(p) == ("5s", "2s")
    assert lines[-1] is None  # the graph shows the recorded line again
    assert p._btn_reset.disabled


def test_a_session_whose_threshold_moved_starts_as_recorded_and_moves_as_one():
    lines = []
    p = _panel(lines, _ticks([70] * 7 + [90] * 8), note="Recorded at 70 › 90 · nothing is saved")
    assert _results(p) == ("5s", "1s")  # its own targets: 5 ticks at 70, 5 at 90; runs of 3
    _control(p).slider.value = 80
    _frames()
    assert _results(p) == ("4s", "2s")  # 80 for every tick: 9 ticks, the longest run 4
    assert lines[-1] == [(0, 80)]


def test_a_new_session_starts_as_recorded_again():
    lines = []
    p = _panel(lines)
    _control(p).slider.value = 90
    _frames()
    p.set_session(_ticks(), NOTE)
    _frames()
    assert _control(p).slider.value == 70 and _results(p) == ("5s", "2s") and p._btn_reset.disabled


def test_a_session_it_cant_replay_says_so():
    p = WhatIfPanel(on_threshold=[].append)
    p.set_session(None, NOTE, unavailable="This session can't be replayed.")
    assert p._controls.parent is None and p._message.parent is p  # detached, not hidden in place
    assert p._message.text == "This session can't be replayed." and p._btn_reset.disabled


def test_loading_and_failure_say_so_in_place_of_the_controls():
    p = WhatIfPanel(on_threshold=[].append)
    p.show_loading()
    assert p._controls.parent is None and p._message.text == "Loading…"
    p.show_load_failed()
    assert p._message.text.startswith("Couldn't load")
    p.set_session(_ticks(), NOTE)
    assert p._controls.parent is p and p._message.parent is None


def test_a_late_value_from_the_last_sessions_control_is_ignored():
    lines = []
    p = _panel(lines)
    old = _control(p)
    p.show_loading()
    assert p._seg_controls == [] and old.parent is None
    old.slider.value = 120  # e.g. a -/+ release delivered after the detail moved on
    _frames()
    assert lines == [] and p._btn_reset.disabled


def test_reset_does_nothing_while_the_next_session_loads():
    # Reset sits in the header, which stays: it must not put the last session's line on the next one's graph.
    lines = []
    p = _panel(lines)
    _control(p).slider.value = 90
    _frames()
    p.show_loading()
    assert p._btn_reset.disabled and p._controls.parent is None  # the last session's "Recorded at" goes with it
    calls = len(lines)
    p.reset()
    assert len(lines) == calls


def test_the_slider_reaches_every_value_and_the_recorded_target():
    p = WhatIfPanel(on_threshold=[].append)
    p.set_session(ScoredTicks([-40.0, 10.0, 250.0], [-20.0] * 3, [Segment("custom_formula", -20.0, 0, 3)]), NOTE)
    s = _control(p).slider
    assert s.min == -40 and s.max == 250 and s.value == -20


def test_the_slider_reaches_a_target_the_threshold_was_moved_to():
    p = WhatIfPanel(on_threshold=[].append)
    p.set_session(ScoredTicks([10.0] * 4, [70.0, 70.0, 195.0, -30.0], [Segment("custom_formula", 70.0, 0, 4)]), NOTE)
    s = _control(p).slider
    assert s.min == -30 and s.max == 195 and s.value == 70


# ---- a program: one control per segment ----

# Segment 1 (Shamatha, target 90) ends 90 91 92; segment 2 (Calm, target 95) starts 95 96 97: one run across them.
PROGRAM_VALUES = [50.0] * 5 + [90.0, 91.0, 92.0] + [95.0, 96.0, 97.0] + [20.0] * 5
TITLES = ["1 · Shamatha · recorded 90", "2 · Calm · recorded 95"]


def _program_ticks() -> ScoredTicks:
    return ScoredTicks(list(PROGRAM_VALUES), [90.0] * 8 + [95.0] * 8,
                       [Segment("shamatha_score", 90, 0, 8), Segment("program_formula", 95, 8, 16, "Calm")])


def test_a_program_has_a_control_per_segment_each_with_its_title_and_stats():
    lines = []
    p = _panel(lines, _program_ticks(), note="Each segment starts at its recorded target · nothing is saved",
               titles=TITLES)
    assert [c.title.text for c in p._seg_controls] == TITLES
    assert [c.slider.value for c in p._seg_controls] == [90, 95]
    assert [c.stats.text for c in p._seg_controls] == ["Above 1s · Streak 1s"] * 2  # 1.5 s each, whole seconds
    assert _results(p) == ("3s", "3s")  # the streak carries across the boundary: six ticks
    assert p._btn_reset.disabled and lines == []


def test_moving_one_segment_changes_it_the_totals_and_its_part_of_the_line():
    lines = []
    p = _panel(lines, _program_ticks(), titles=TITLES)
    _control(p, 1).slider.value = 97
    _frames()
    assert _control(p, 0).stats.text == "Above 1s · Streak 1s"  # as recorded
    assert _control(p, 1).stats.text == "Above 0s · Streak 0s"  # only 97: 0.5 s
    assert _results(p) == ("2s", "1s")  # 90 91 92 + 97; the run 90 91 92
    assert lines[-1] == [(0, 90), (8, 97)]
    p.reset()
    _frames()
    assert [c.slider.value for c in p._seg_controls] == [90, 95] and _results(p) == ("3s", "3s")
    assert lines[-1] is None


def test_a_simple_session_has_no_segment_title_or_stats():
    p = _panel([])
    assert _control(p).title is None and _control(p).stats is None and p._total_title.parent is None


def test_a_programs_totals_are_titled_whole_session_and_go_with_it():
    p = _panel([], _program_ticks(), titles=TITLES)
    box = p._controls.children[::-1]  # top to bottom
    assert box.index(p._total_title) == box.index(p._results) - 1
    p.set_session(_ticks(), NOTE)
    assert p._total_title.parent is None


# ---- in the session detail ----


def _scored_rows(values, targets, key="shamatha_score") -> list[dict]:
    return [{"timestamp": i * 0.5, "shamatha_score": float(v), "score_key": key, "score_value": float(v),
             "score_target": t} for i, (v, t) in enumerate(zip(values, targets))]


def _open(a, workers, sid) -> None:
    a._on_session_select(sid)
    workers.pop()()
    _frames(6)


def test_the_detail_opens_its_session_as_recorded_and_the_line_follows_the_slider(app):  # noqa: F811
    a, workers = app
    targets = [70] * 7 + [90] * 8
    sid = a._db.checkpoint_session(None, {"duration": 7, "threshold_used": 70, "score_metric_key": "shamatha_score",
                                          "score_metric_name": "Shamatha", "avg_score": 75.0, "score_targets": "[70, 90]",
                                          "time_above_threshold": 5, "longest_streak": 1},
                                   _scored_rows(VALUES, targets), user_id=a._current_user_id, session_name="s")
    _open(a, workers, sid)
    d = a._diary_screen
    panel, graph = d._what_if, d._metrics_graph
    assert panel._controls.parent is panel and panel._note.text == "Recorded at 70 › 90 · nothing is saved"
    assert _results(panel) == ("5s", "1s")  # the recorded numbers, from its own ticks
    assert graph._threshold_steps == [(0, 70), (7, 90)]
    _control(panel).slider.value = 80
    _frames()
    assert graph._threshold_steps == [(0, 80)]
    panel.reset()
    assert graph._threshold_steps == [(0, 70), (7, 90)]
    row = a._db.get_session(sid)
    assert (row["time_above_threshold"], row["longest_streak"], row["threshold_used"]) == (5, 1, 70)  # untouched


def test_an_older_session_is_scored_on_its_stored_column(app):  # noqa: F811
    a, workers = app
    _open(a, workers, a.sessions["A"])  # rows without a per-tick record, scored on shamatha at 70
    panel = a._diary_screen._what_if
    assert panel._controls.parent is panel and _control(panel).slider.value == 70


def test_a_program_session_opens_with_a_control_per_segment(app):  # noqa: F811
    a, workers = app
    program = [{"minutes": 1, "target": 90, "formula": "shamatha_score"},
               {"minutes": 1, "target": 60, "formula": "meditation_score"}]
    values = [50.0] * 117 + [90.0, 91.0, 92.0] + [80.0] * 120
    rows = [{"timestamp": i * 0.5, "shamatha_score": values[i] if i < 120 else 0.0,
             "meditation_score": values[i] if i >= 120 else 0.0} for i in range(240)]
    sid = a._db.checkpoint_session(None, {"duration": 120, "threshold_used": 90, "score_metric_key": "program",
                                          "score_metric_name": "Program", "time_above_threshold": 61,
                                          "longest_streak": 61}, rows, user_id=a._current_user_id,
                                   session_name="p", session_program=json.dumps(program))
    _open(a, workers, sid)
    d = a._diary_screen
    panel, graph = d._what_if, d._metrics_graph
    assert panel._controls.parent is panel
    assert [c.title.text for c in panel._seg_controls] == ["1 · Shamatha · recorded 90", "2 · Meditation · recorded 60"]
    assert _results(panel) == ("1m 01s", "1m 01s")  # 90 91 92, then all 120 at 80 >= 60: one run of 123 ticks
    recorded = graph._threshold_steps
    assert recorded == [(0, 90.0), (120, 60.0)]
    _control(panel, 1).slider.value = 85
    _frames()
    assert graph._threshold_steps == [(0, 90.0), (120, 85)] and _results(panel) == ("1s", "1s")
    panel.reset()
    assert graph._threshold_steps == recorded


def test_another_session_opens_as_recorded_again(app):  # noqa: F811
    a, workers = app
    _open(a, workers, a.sessions["A"])
    _control(a._diary_screen._what_if).slider.value = 120
    _frames()
    a._on_diary_back()
    _open(a, workers, a.sessions["B"])
    panel = a._diary_screen._what_if
    assert _control(panel).slider.value == 70 and panel._btn_reset.disabled


def test_the_next_session_shows_loading_until_its_data_arrives(app):  # noqa: F811
    a, workers = app
    _open(a, workers, a.sessions["A"])
    a._on_diary_back()
    a._on_session_select(a.sessions["B"])  # its worker hasn't run yet
    panel = a._diary_screen._what_if
    assert panel._controls.parent is None and panel._message.text == "Loading…"  # not A's what-if


def test_a_formula_the_replay_couldnt_rebuild_says_so(app):  # noqa: F811
    a, workers = app
    sid = a._db.checkpoint_session(None, {"duration": 7, "threshold_used": 150, "score_metric_key": "custom_formula_3",
                                          "score_metric_name": "Gone"},
                                   [{"timestamp": i * 0.5, "shamatha_score": 60.0} for i in range(10)],
                                   user_id=a._current_user_id, session_name="f")
    _open(a, workers, sid)
    panel = a._diary_screen._what_if
    assert panel._controls.parent is None and "can't be replayed" in panel._message.text


def test_a_what_if_that_fails_fails_alone(app, monkeypatch):  # noqa: F811
    a, workers = app
    monkeypatch.setattr(am, "scored_ticks", lambda *_a: (_ for _ in ()).throw(KeyError("score_value")))
    _open(a, workers, a.sessions["A"])
    d = a._diary_screen
    assert d._what_if._message.text.startswith("Couldn't load")
    assert max(len(v) for v in d._metrics_graph._data.values()) == 40  # the graphs still filled


def _program_session(a, program, rows) -> int:
    return a._db.checkpoint_session(None, {"duration": len(rows) // 2, "threshold_used": program[0]["target"],
                                           "score_metric_key": "program", "score_metric_name": "Program"},
                                    rows, user_id=a._current_user_id, session_name="p",
                                    session_program=json.dumps(program))


def test_an_older_programs_formula_is_replayed_for_its_segment(app):  # noqa: F811
    a, workers = app
    program = [{"minutes": 1, "target": 90, "formula": "shamatha_score"},
               {"minutes": 1, "target": 60, "formula": {"name": "Steady", "formula": "80"}}]
    sid = _program_session(a, program, [{"timestamp": i * 0.5, "shamatha_score": 50.0} for i in range(240)])
    _open(a, workers, sid)
    panel = a._diary_screen._what_if
    assert [c.title.text for c in panel._seg_controls] == ["1 · Shamatha · recorded 90", "2 · Steady · recorded 60"]
    assert [c.stats.text for c in panel._seg_controls] == ["Above 0s · Streak 0s", "Above 1m 00s · Streak 1m 00s"]


def test_a_program_whose_ticks_stored_their_scoring_replays_no_formula(app, monkeypatch):  # noqa: F811
    a, workers = app
    program = [{"minutes": 1, "target": 60, "formula": {"name": "Steady", "formula": "80"}}]
    rows = _scored_rows([80.0] * 120, [60.0] * 120, key="program_formula")
    sid = _program_session(a, program, rows)
    replays = []
    monkeypatch.setattr(a._db, "recompute_formula_series", lambda *args: replays.append(args) or {})
    _open(a, workers, sid)
    panel = a._diary_screen._what_if
    assert replays == [] and _results(panel) == ("1m 00s", "1m 00s")


# ---- folding the panel away ----


def _tap(widget) -> None:
    x, y = widget.to_window(widget.center_x, widget.center_y)
    touch = UnitTestTouch(x, y)
    touch.touch_down()
    touch.touch_up()
    _frames(3)


def test_the_chevron_sits_right_after_the_title():
    p = _panel([])
    p.size = (360, 400)
    _frames(3)
    title, chevron = p._title, p._btn_collapse
    assert title.width == title.texture_size[0] and 0 <= chevron.x - title.right <= 8  # not pushed to the far side
    assert p._btn_reset.right == p.right


def test_folding_detaches_the_body_and_unfolding_brings_back_what_it_shows():
    lines = []
    p = _panel(lines)
    states = []
    p.set_collapse_callback(states.append)
    p.toggle_collapsed()
    assert p.collapsed and p._controls.parent is None and p._message.parent is None and states == [True]
    assert p._btn_collapse._icon_label.text == Icons.CHEVRON_RIGHT
    p.show_loading()  # the next session, while folded
    assert p._message.parent is None
    p.set_session(_ticks(), NOTE)
    assert p._controls.parent is None
    p.toggle_collapsed()
    assert not p.collapsed and p._controls.parent is p and p._message.parent is None and states == [True, False]
    assert p._btn_collapse._icon_label.text == Icons.CHEVRON_DOWN


def test_reset_stays_in_reach_while_folded():
    lines = []
    p = _panel(lines)
    _control(p).slider.value = 90
    _frames()
    p.set_collapsed(True)
    assert p._btn_reset.parent is not None and not p._btn_reset.disabled
    p.reset()
    assert lines[-1] is None and p._btn_reset.disabled


def test_a_tap_on_the_chevron_folds_it():
    p = _panel([])
    Window.add_widget(p)
    try:
        p.pos, p.size = (0, 0), (360, 400)
        _frames(3)
        _tap(p._btn_collapse)
        assert p.collapsed
    finally:
        Window.remove_widget(p)


def test_the_folded_panel_is_saved_per_profile(app):  # noqa: F811
    a, _workers = app
    store, me = a._db, a._current_user_id
    other = store.create_user("other")
    panel = a._diary_screen.what_if
    a._loading_settings = False
    # As _build_settings_store declares it, and as build() wires the chevron.
    a._settings_store = SettingsStore(store, [Setting("what_if_collapsed", False, BOOL[0], BOOL[1],
                                                      lambda: panel.collapsed, panel.set_collapsed)])
    panel.set_collapse_callback(lambda _c: a._persist_user_setting("what_if_collapsed"))
    panel.toggle_collapsed()  # "me" folds it
    assert store.get_user_setting(me, "what_if_collapsed") == "True"
    a._settings_store.load(other)
    assert not panel.collapsed  # the other profile's own state
    a._settings_store.load(me)
    assert panel.collapsed
