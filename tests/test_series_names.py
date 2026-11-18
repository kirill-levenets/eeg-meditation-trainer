"""Each graph keeps its own series names: a session opened in History names its own lines, never the Session screen's,
and a program's labels go when it ends."""

import pytest

from app.metrics.formula_slots import FormulaSlots
from app.metrics.series_names import SERIES_NAMES
from app.session.session_program import SessionProgram, runnable_plan
from app.ui.diary_screen import DiaryScreen
from app.ui.graph_series import show_program_series
from app.ui.live_session import LiveSessionScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from tests._app import frames_until, program_mode, reload_with, start_connecting
from tests._picker import picker_rows

PAST_NAMES = {"custom_formula": "Old beta", "custom_formula_2": "Custom 2", "custom_formula_3": "Custom 3"}


DEEP = {"minutes": 5, "target": 60, "formula": {"name": "Deep", "formula": "alpha1"}}


@pytest.fixture
def app(fresh_app):
    """The app; the profile named its first formula slot "Calm alpha"."""
    reload_with(fresh_app, {"active_formulas": [{"name": "Calm alpha", "formula": ""}]})
    return fresh_app


def _program_rows(app, monkeypatch) -> list[str]:
    return [row for row in picker_rows(app, monkeypatch) if row.startswith("Program")]


def test_opening_a_past_session_leaves_the_session_screens_names(app):
    app._diary_screen.set_session_formulas({}, PAST_NAMES)
    assert app._live_screen.graph.series_name("custom_formula") == "Calm alpha"
    assert app._diary_screen._metrics_graph.series_name("custom_formula") == "Old beta"


def test_the_detail_starts_from_the_defaults_not_the_session_screens_names(app):
    assert app._live_screen.graph.series_name("custom_formula") == "Calm alpha"  # built in the same process
    assert DiaryScreen()._metrics_graph.series_name("custom_formula") == "Custom 1"
    assert SERIES_NAMES["custom_formula"] == "Custom 1"


def test_the_idle_preview_shows_shamatha_for_a_formula_that_cant_run(app):
    program_mode(app, [{"minutes": 5, "target": 60, "formula": {"name": "Broken", "formula": "alpha1 +"}}])
    assert app._live_screen.graph.visible_keys() == ["shamatha_score"]  # what the start will drive; no line for "Broken"


def test_a_programs_labels_go_when_it_ends(app):
    graph = app._live_screen.graph
    show_program_series(graph, runnable_plan(SessionProgram([DEEP])))
    assert graph.series_name("program_formula") == "Program: Deep"
    app._session.program_run.end()
    assert graph.series_name("program_formula") == "Program"


def test_a_program_of_built_in_metrics_lists_no_program_lines(app, monkeypatch):
    program_mode(app, [{"minutes": 5, "target": 50, "formula": "shamatha_score"},
                       {"minutes": 5, "target": 60, "formula": "meditation_score"}])
    app._on_start()
    assert _program_rows(app, monkeypatch) == []


def test_a_program_lists_only_the_lines_it_computes(app, monkeypatch):
    segments = [DEEP, {"minutes": 5, "target": 60, "formula": "shamatha_score"}]
    assert list(runnable_plan(SessionProgram(segments)).evaluators) == ["program_formula"]
    program_mode(app, segments)
    app._on_start()
    assert _program_rows(app, monkeypatch) == ["Program: Deep"]


def test_the_idle_preview_lists_no_program_line(app, monkeypatch):
    # The preview shows a program's set before Start; its custom line computes nothing until the session runs.
    program_mode(app, [DEEP])
    assert app._live_screen.graph.is_visible("program_formula")
    assert _program_rows(app, monkeypatch) == []


def test_a_program_waiting_for_the_headset_keeps_its_lines_through_the_idle_refresh(app, monkeypatch):
    program_mode(app, [DEEP])
    start_connecting(app, monkeypatch)  # the BT wait: the program has begun, the session connects
    app._program_settings.segments = [{"minutes": 5, "target": 60, "formula": "meditation_score"}]  # edited meanwhile
    app._switch_screen("live_session")  # a Session-tab tap: the idle refresh
    assert app._live_screen.graph.is_visible("program_formula")
    assert _program_rows(app, monkeypatch) == ["Program: Deep"]


def test_no_program_lines_once_the_program_ends(app, monkeypatch):
    program_mode(app, [DEEP])
    app._on_start()
    app._stop_and_save()
    frames_until(lambda: app._session.run is None, 2.0)  # the runner saved it; its Ended event tore the screen down
    assert _program_rows(app, monkeypatch) == []


def test_the_default_names_cant_be_changed_in_place():
    with pytest.raises(TypeError):
        SERIES_NAMES["custom_formula"] = "Renamed"


def test_a_graph_keeps_its_own_copy_of_the_names_it_is_given():
    names = {"a": "Alpha"}
    graph = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0}, names=names)
    graph.set_series_name("a", "Renamed")
    assert names == {"a": "Alpha"} and graph.series_name("a") == "Renamed"


def test_the_session_screens_legend_starts_as_its_graph_shows():
    """set_visible rebuilds the legend only on a change, so the first one must already match the graph."""
    screen = LiveSessionScreen()
    shown = [lbl.text for lbl in reversed(screen._legend.children)]
    assert shown == [screen.graph.series_name(k) for k in screen.graph.series_keys() if screen.graph.is_visible(k)]


def test_a_line_is_named_by_its_formula_slot_else_by_its_default():
    slots = FormulaSlots()
    slots.load([{"name": "Calm", "formula": "alpha1"}])
    assert slots.line_name("custom_formula") == "Calm"
    assert slots.line_name("custom_formula_2") == "Custom 2" == SERIES_NAMES["custom_formula_2"]
    assert slots.line_name("shamatha_score") == "Shamatha"
    assert slots.line_name("an_unknown_score") == ScrollableGraphWidget(colors={}, scales={}).series_name("an_unknown_score")
