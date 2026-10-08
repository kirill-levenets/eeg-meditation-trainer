"""The session detail's what-if panel: a threshold slider, -/+ and Reset over the time above threshold and longest streak
the session's ticks give at it. It starts as recorded, the graph's line follows it, and nothing is written."""

from kivy.base import EventLoop

import app.ui.app_manager as am
from app.session.what_if import ScoredTicks
from app.ui.widgets.what_if import WhatIfPanel
from tests.test_session_detail_open import app, db  # noqa: F401  (fixtures)

VALUES = [60, 72, 75, 80, 50, 90, 91, 92, 40, 88, 95, 96, 97, 30, 99]


def _ticks(targets=None) -> ScoredTicks:
    targets = targets or [70] * len(VALUES)
    return ScoredTicks(list(VALUES), ["shamatha_score"] * len(VALUES), targets)


def _frames(n: int = 2) -> None:
    for _ in range(n):
        EventLoop.idle()


def _results(panel: WhatIfPanel) -> tuple[str, str]:
    return panel._time_above.text, panel._streak.text


def _panel(lines: list, ticks: ScoredTicks | None = None, recorded: str = "70") -> WhatIfPanel:
    p = WhatIfPanel(on_threshold=lines.append)
    p.set_session(ticks or _ticks(), recorded_target=70, recorded_text=recorded)
    _frames()
    return p


def test_it_starts_as_recorded():
    lines = []
    p = _panel(lines)
    assert p._slider.value == 70 and p._value_label.text == "70"
    assert p._recorded_label.text == "Recorded at 70 · nothing is saved"
    assert _results(p) == ("5s", "2s")  # >= 70: 11 ticks (5.5 s), the longest run 88 95 96 97 (2 s)
    assert p._btn_reset.disabled and lines == []


def test_moving_the_slider_rescores_and_moves_the_graphs_line():
    lines = []
    p = _panel(lines)
    p._slider.value = 90
    _frames()
    assert p._value_label.text == "90" and _results(p) == ("3s", "1s")  # 7 ticks (3.5 s), runs of 3 (1.5 s)
    assert lines[-1] == 90 and not p._btn_reset.disabled


def test_minus_and_plus_step_by_five():
    lines = []
    p = _panel(lines)
    p._step(+5)
    _frames()
    assert p._slider.value == 75 and lines[-1] == 75
    p._step(-10)
    _frames()
    assert p._slider.value == 65


def test_reset_goes_back_to_as_recorded():
    lines = []
    p = _panel(lines)
    p._slider.value = 90
    _frames()
    p.reset()
    _frames()
    assert p._slider.value == 70 and _results(p) == ("5s", "2s")
    assert lines[-1] is None  # the graph shows the recorded line again
    assert p._btn_reset.disabled


def test_a_session_whose_threshold_moved_starts_as_recorded_and_moves_as_one():
    lines = []
    p = _panel(lines, _ticks([70] * 7 + [90] * 8), recorded="70 › 90")
    assert p._recorded_label.text == "Recorded at 70 › 90 · nothing is saved"
    assert _results(p) == ("5s", "1s")  # its own targets: 5 ticks at 70, 5 at 90; runs of 3
    p._slider.value = 80
    _frames()
    assert _results(p) == ("4s", "2s")  # 80 for every tick: 9 ticks, the longest run 4


def test_a_new_session_starts_as_recorded_again():
    lines = []
    p = _panel(lines)
    p._slider.value = 90
    _frames()
    p.set_session(_ticks(), recorded_target=70, recorded_text="70")
    _frames()
    assert p._slider.value == 70 and _results(p) == ("5s", "2s") and p._btn_reset.disabled


def test_a_program_session_says_it_isnt_available_yet():
    p = WhatIfPanel(on_threshold=[].append)
    p.set_session(None, recorded_target=70, recorded_text="Per segment", unavailable="Not for programs yet.")
    assert p._controls.parent is None and p._message.parent is p  # detached, not hidden in place
    assert p._message.text == "Not for programs yet." and p._btn_reset.disabled


def test_loading_and_failure_say_so_in_place_of_the_controls():
    p = WhatIfPanel(on_threshold=[].append)
    p.show_loading()
    assert p._controls.parent is None and p._message.text == "Loading…"
    p.show_load_failed()
    assert p._message.text.startswith("Couldn't load")
    p.set_session(_ticks(), recorded_target=70, recorded_text="70")
    assert p._controls.parent is p and p._message.parent is None


# ---- in the session detail ----


def _scored_rows(values, targets) -> list[dict]:
    return [{"timestamp": i * 0.5, "shamatha_score": float(v), "score_key": "shamatha_score", "score_value": float(v),
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
    assert panel._controls.parent is panel and panel._recorded_label.text.startswith("Recorded at 70 › 90")
    assert _results(panel) == ("5s", "1s")  # the recorded numbers, from its own ticks
    assert graph._threshold_steps == [(0, 70), (7, 90)]
    panel._slider.value = 80
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
    assert panel._controls.parent is panel and panel._slider.value == 70


def test_a_program_session_shows_the_message(app):  # noqa: F811
    a, workers = app
    sid = a._db.checkpoint_session(None, {"duration": 7, "threshold_used": 70, "score_metric_key": "program"},
                                   _scored_rows(VALUES, [70] * len(VALUES)), user_id=a._current_user_id,
                                   session_name="p", session_program='[{"minutes": 1, "target": 70}]')
    _open(a, workers, sid)
    panel = a._diary_screen._what_if
    assert panel._controls.parent is None and "program" in panel._message.text.lower()


def test_another_session_opens_as_recorded_again(app):  # noqa: F811
    a, workers = app
    _open(a, workers, a.sessions["A"])
    a._diary_screen._what_if._slider.value = 120
    _frames()
    a._on_diary_back()
    _open(a, workers, a.sessions["B"])
    panel = a._diary_screen._what_if
    assert panel._slider.value == 70 and panel._btn_reset.disabled


def test_the_next_session_shows_loading_until_its_data_arrives(app):  # noqa: F811
    a, workers = app
    _open(a, workers, a.sessions["A"])
    a._on_diary_back()
    a._on_session_select(a.sessions["B"])  # its worker hasn't run yet
    panel = a._diary_screen._what_if
    assert panel._controls.parent is None and panel._message.text == "Loading…"  # not A's what-if


def test_reset_does_nothing_while_the_next_session_loads():
    # Reset sits in the header, which stays: it must not put the last session's line on the next one's graph.
    lines = []
    p = _panel(lines)
    p._slider.value = 90
    _frames()
    p.show_loading()
    assert p._btn_reset.disabled and p._controls.parent is None  # the last session's "Recorded at" goes with it
    calls = len(lines)
    p.reset()
    assert len(lines) == calls


def test_the_slider_reaches_every_value_and_the_recorded_target():
    p = WhatIfPanel(on_threshold=[].append)
    p.set_session(ScoredTicks([-40.0, 10.0, 250.0], ["custom_formula"] * 3, [-20.0] * 3), recorded_target=-20,
                  recorded_text="-20")
    assert p._slider.min == -40 and p._slider.max == 250 and p._slider.value == -20


def test_a_formula_the_replay_couldnt_rebuild_says_so(app):  # noqa: F811
    a, workers = app
    sid = a._db.checkpoint_session(None, {"duration": 7, "threshold_used": 150, "score_metric_key": "custom_formula_3",
                                          "score_metric_name": "Gone"},
                                   [{"timestamp": i * 0.5, "shamatha_score": 60.0} for i in range(10)],
                                   user_id=a._current_user_id, session_name="f")
    _open(a, workers, sid)
    panel = a._diary_screen._what_if
    assert panel._controls.parent is None and "formula" in panel._message.text


def test_a_what_if_that_fails_fails_alone(app, monkeypatch):  # noqa: F811
    a, workers = app
    monkeypatch.setattr(am, "scored_ticks", lambda *_a: (_ for _ in ()).throw(KeyError("score_value")))
    _open(a, workers, a.sessions["A"])
    d = a._diary_screen
    assert d._what_if._message.text.startswith("Couldn't load")
    assert max(len(v) for v in d._metrics_graph._data.values()) == 40  # the graphs still filled
