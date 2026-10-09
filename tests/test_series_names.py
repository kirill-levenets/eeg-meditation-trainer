"""Each graph keeps its own series names: a session opened in History names its own lines, never the Session screen's,
and a program's labels go when it ends."""

import pytest

import app.ui.app_manager as am
from app.session.session_program import SessionProgram, program_evaluators
from app.ui.app_manager import EEGMeditationApp
from app.ui.diary_screen import DiaryScreen
from app.ui.live_session import SERIES_NAMES, LiveSessionScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget

PAST_NAMES = {"custom_formula": "Old beta", "custom_formula_2": "Custom 2", "custom_formula_3": "Custom 3"}


@pytest.fixture
def app() -> EEGMeditationApp:
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._live_screen = LiveSessionScreen()
    a._diary_screen = DiaryScreen()
    a._formula_names = ["Calm alpha", "Custom 2", "Custom 3"]
    a._push_formula_names_to_graph()  # the profile's slot names, as loading its settings does
    return a


def test_opening_a_past_session_leaves_the_session_screens_names(app):
    app._diary_screen.set_session_formulas({}, PAST_NAMES)
    assert app._live_screen.graph.series_name("custom_formula") == "Calm alpha"
    assert app._diary_screen._metrics_graph.series_name("custom_formula") == "Old beta"


def test_the_detail_starts_from_the_defaults_not_the_session_screens_names(app):
    assert app._diary_screen._metrics_graph.series_name("custom_formula") == "Custom 1"
    assert SERIES_NAMES["custom_formula"] == "Custom 1"


def test_a_programs_labels_go_when_it_ends(app):
    graph = app._live_screen.graph
    app._apply_program_visibility(SessionProgram([{"minutes": 5, "target": 60,
                                                   "formula": {"name": "Deep", "formula": "alpha1"}}]))
    assert graph.series_name("program_formula") == "Program: Deep"
    app._restore_program_series()
    assert graph.series_name("program_formula") == "Program"


def _picker_rows(app, monkeypatch) -> list[str]:
    """The series picker's row labels for the live graph, as it would open now."""
    shown = []

    class _Popup:
        def bind(self, **_kw):
            pass

        def open(self):
            pass

    def capture(_title, rows, footer=None, **_kw):
        # A row is its toggle, or a box with the toggle first (a formula slot's, with Choose…).
        shown.extend(getattr(row, "text", None) or row.children[-1].text for row in rows)
        return _Popup()

    monkeypatch.setattr(am, "make_scroll_popup", capture)
    app._present_series_picker(app._live_screen.graph)
    return shown


def _run_program(app, segments) -> None:
    prog = SessionProgram(segments)
    app._show_program_series(prog)  # as a program session's start does
    app._session_program_active = True


def test_a_program_of_built_in_metrics_lists_no_program_lines(app, monkeypatch):
    _run_program(app, [{"minutes": 5, "target": 50, "formula": "shamatha_score"},
                       {"minutes": 5, "target": 60, "formula": "meditation_score"}])
    assert not [row for row in _picker_rows(app, monkeypatch) if row.startswith("Program")]


def test_a_program_lists_only_the_lines_it_computes(app, monkeypatch):
    segments = [{"minutes": 5, "target": 60, "formula": {"name": "Deep", "formula": "alpha1"}},
                {"minutes": 5, "target": 60, "formula": "shamatha_score"}]
    assert list(program_evaluators(SessionProgram(segments))) == ["program_formula"]
    _run_program(app, segments)
    assert [row for row in _picker_rows(app, monkeypatch) if row.startswith("Program")] == ["Program: Deep"]


def test_no_program_lines_once_the_program_ends(app, monkeypatch):
    _run_program(app, [{"minutes": 5, "target": 60, "formula": {"name": "Deep", "formula": "alpha1"}}])
    app._restore_program_series()
    assert not [row for row in _picker_rows(app, monkeypatch) if row.startswith("Program")]


def test_the_default_names_cant_be_changed_in_place():
    with pytest.raises(TypeError):
        SERIES_NAMES["custom_formula"] = "Renamed"


def test_a_graph_keeps_its_own_copy_of_the_names_it_is_given():
    names = {"a": "Alpha"}
    graph = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0}, names=names)
    graph.set_series_name("a", "Renamed")
    assert names == {"a": "Alpha"} and graph.series_name("a") == "Renamed"
