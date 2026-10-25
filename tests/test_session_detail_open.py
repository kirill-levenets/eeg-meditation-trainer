"""Tapping a session opens its detail at once (#59): title, stats and notes come from the row History holds, and the
graphs and band totals load on a worker, each section showing "Loading…" until its data arrives, then filling one
section per frame. A late result for a detail the user has left, or replaced with another session, is dropped."""

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager

import app.ui.app_manager as am
from app.metrics.formula_slots import FormulaSlots
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.diary_screen import DiaryScreen
from tests._graph_series import make_graph_series

BANDS = ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2")


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = DatabaseManager(db_path=path)
    yield d
    d.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def _session(db, uid: int, ticks: int, name: str, power: float, formula_name: str = "Calm ratio") -> int:
    rows = [{"timestamp": t * 0.5, "shamatha_score": 60.0 + t % 7, "meditation_score": 40.0,
             **dict.fromkeys(BANDS, power), **{f"{b}_raw": power for b in BANDS}} for t in range(ticks)]
    formulas = json.dumps([{"slot": 0, "name": formula_name, "formula": "alpha1 / beta1 * 100", "visible": True}])
    return db.checkpoint_session(None, {"duration": ticks // 2, "threshold_used": 70,
                                        "score_metric_key": "shamatha_score", "score_metric_name": "Shamatha",
                                        "avg_score": 62.0}, rows, user_id=uid, session_name=name,
                                 custom_formulas=formulas, started_at=1_759_648_500.0)


@pytest.fixture
def app(db, monkeypatch):
    uid = db.create_user("me")
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._db = db
    a._current_user_id = uid
    a._diary_screen = DiaryScreen()
    sm = ScreenManager(transition=NoTransition())
    sm.add_widget(Screen(name="history"))
    sm.add_widget(a._diary_screen)
    sm.current = "history"
    a._sm = sm
    a._bottom_nav = MagicMock()
    a._refresh_history = MagicMock()
    a._history_screen = MagicMock()
    a._history_screen.session_by_id = lambda sid: db.get_session(sid)  # the row History's list holds
    a._formulas = FormulaSlots()
    a._graph_series = make_graph_series(a, graphs=a._detail_graphs)  # the diary's program lines, as build() wires them
    a.show_loading = MagicMock()
    a.hide_loading = MagicMock()
    workers = []
    monkeypatch.setattr(am.threading, "Thread",
                        lambda target, args=(), **k: MagicMock(start=lambda: workers.append(lambda: target(*args))))
    a.sessions = {"A": _session(db, uid, 40, "Morning sit", 100.0),
                  "B": _session(db, uid, 60, "Evening sit", 300.0, formula_name="Drowsy")}
    return a, workers


def _frames(n: int = 1) -> None:
    for _ in range(n):
        EventLoop.idle()


def _open(a, workers, sid) -> None:
    a._on_session_select(sid)
    workers.pop()()
    _frames(6)


def _program_session(a, program, rows) -> int:
    return a._db.checkpoint_session(None, {"duration": len(rows) // 2, "threshold_used": program[0]["target"],
                                           "score_metric_key": "program", "score_metric_name": "Program"},
                                    rows, user_id=a._current_user_id, session_name="p",
                                    session_program=json.dumps(program))


def _filled(graph) -> int:
    return max((len(v) for v in graph._data.values()), default=0)


def _graphs(d: DiaryScreen) -> dict[str, int]:
    return {"metrics": _filled(d._metrics_graph), "raw": _filled(d._raw_eeg_graph), "freq": _filled(d._freq_graph)}


def _shown_in_graph_area(d: DiaryScreen):
    return d._graph_container.children[0]


def test_the_detail_opens_at_once_with_title_stats_and_notes(app):
    a, workers = app
    a._db.update_session_notes(a.sessions["A"], notes="Calm, then sleepy")
    a._on_session_select(a.sessions["A"])
    d = a._diary_screen
    assert a._sm.current == "diary" and workers  # on screen before the worker has read anything
    a.show_loading.assert_not_called()  # no full-screen spinner
    assert d._detail_title.text.endswith("Morning sit")
    assert ("Metric", "Shamatha") in [(t.text, v.text) for t, v in d._detail_rows]
    assert d._notes_input.text == "Calm, then sleepy" and not d._notes_input.disabled
    assert _shown_in_graph_area(d) is d._graph_placeholder and d._graph_placeholder.text == "Loading…"
    assert d._band_placeholder.parent is not None and d._band_totals.parent is None
    assert _graphs(d) == {"metrics": 0, "raw": 0, "freq": 0}


def test_band_totals_then_one_graph_per_frame(app):
    a, workers = app
    a._on_session_select(a.sessions["A"])
    d = a._diary_screen
    workers.pop()()
    _frames()
    assert d._band_totals.parent is not None and d._band_totals._totals["alpha1"] == pytest.approx(100.0 * 40)
    assert _graphs(d) == {"metrics": 40, "raw": 0, "freq": 0}  # the shown tab first
    assert _shown_in_graph_area(d) is d._metrics_graph
    _frames()
    assert _graphs(d)["raw"] > 0 and _graphs(d)["freq"] == 0
    _frames()
    assert _graphs(d)["freq"] == 40


def test_the_scored_formula_series_and_its_name_arrive_with_the_metrics_graph(app):
    a, workers = app
    a._on_session_select(a.sessions["A"])
    workers.pop()()
    _frames(3)
    graph = a._diary_screen._metrics_graph
    assert graph.series_name("custom_formula") == "Calm ratio"
    assert list(graph._data["custom_formula"]) == pytest.approx([100.0] * 40)


def test_the_metric_rows_are_read_once_per_open(app, monkeypatch):
    a, workers = app
    reads = []
    real = a._db.get_session_metrics
    monkeypatch.setattr(a._db, "get_session_metrics", lambda sid: reads.append(sid) or real(sid))
    a._on_session_select(a.sessions["A"])
    workers.pop()()
    assert reads == [a.sessions["A"]]  # the formula replay uses the same rows


def test_back_while_loading_drops_the_late_results(app):
    a, workers = app
    a._on_session_select(a.sessions["A"])
    a._on_diary_back()
    assert a._sm.current == "history"
    workers.pop()()
    _frames(4)
    d = a._diary_screen
    assert _graphs(d) == {"metrics": 0, "raw": 0, "freq": 0}
    assert d._band_totals.parent is None


def test_opening_another_session_while_one_loads_shows_only_the_new_one(app):
    a, workers = app
    a._on_session_select(a.sessions["A"])
    a._on_diary_back()
    a._on_session_select(a.sessions["B"])
    first, second = workers
    second()
    _frames(4)  # B is fully shown
    first()  # then A's slower load lands
    _frames(4)
    d = a._diary_screen
    assert d._detail_title.text.endswith("Evening sit")
    assert _graphs(d) == {"metrics": 60, "raw": _graphs(d)["raw"], "freq": 60}
    assert d._band_totals._totals["alpha1"] == pytest.approx(300.0 * 60)


def test_a_failed_load_says_so_in_each_section(app, monkeypatch):
    a, workers = app
    reported = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    monkeypatch.setattr(a._db, "get_session_metrics", MagicMock(side_effect=sqlite3.OperationalError("disk I/O error")))
    a._on_session_select(a.sessions["A"])
    workers.pop()()
    _frames(2)
    d = a._diary_screen
    assert reported == ["session_detail_load_failed"]
    assert d._graph_placeholder.text.startswith("Couldn't load")
    assert d._notes_input.text == ""  # the fields still work: notes can be written and saved
    d._switch_graph_tab("raw")
    assert _shown_in_graph_area(d) is d._graph_placeholder and d._graph_placeholder.text.startswith("Couldn't load")


def test_a_tab_picked_while_loading_shows_its_placeholder_then_its_graph(app):
    a, workers = app
    a._on_session_select(a.sessions["A"])
    d = a._diary_screen
    d._switch_graph_tab("raw")
    assert _shown_in_graph_area(d) is d._graph_placeholder
    workers.pop()()
    _frames()
    assert _graphs(d)["raw"] > 0 and _graphs(d)["metrics"] == 0  # the shown tab's graph comes first
    assert _shown_in_graph_area(d) is d._raw_eeg_graph
    _frames(2)
    assert _graphs(d)["metrics"] == 40 and _graphs(d)["freq"] == 40


def test_the_legend_names_the_new_sessions_formulas_while_its_graphs_load(app):
    # The names are in the session's row: the legend has them from the first frame, not the last session's.
    a, workers = app
    a._on_session_select(a.sessions["A"])
    workers.pop()()
    _frames(3)
    a._on_diary_back()
    a._on_session_select(a.sessions["B"])
    assert a._diary_screen._metrics_graph.series_name("custom_formula") == "Drowsy"


def test_a_program_sessions_detail_shows_its_lines_and_never_saves_them(app):
    """As the Session screen did while it ran: exactly the program's lines, whatever History's own selection; while
    they show nothing saves over that selection, and a simple session opened next shows it again (#113)."""
    a, workers = app
    d, uid = a._diary_screen, a._current_user_id
    graph = d._metrics_graph
    a._db.set_user_json_setting(uid, "graph_series_diary_metrics", ["shamatha_score"])
    a._graph_series.apply_saved(graph, uid)
    program = [{"minutes": 1, "target": 90, "formula": "shamatha_score"},
               {"minutes": 1, "target": 60, "formula": {"name": "Steady", "formula": "80"}},
               {"minutes": 1, "target": 70, "formula": "meditation_score"}]
    _open(a, workers, _program_session(a, program, [{"timestamp": i * 0.5, "shamatha_score": 50.0} for i in range(360)]))
    assert set(graph.visible_keys()) == {"shamatha_score", "program_formula", "meditation_score"}
    assert graph.series_name("program_formula") == "Program: Steady"
    a._graph_series.persist_all()  # a settings save, a backup or a pause while it shows
    assert a._db.get_user_json_setting(uid, "graph_series_diary_metrics") == ["shamatha_score"]
    assert a._db.get_user_json_setting(uid, "graph_series_diary_freq") is not None  # the other graphs still save
    _open(a, workers, a.sessions["A"])  # a simple session next
    assert graph.visible_keys() == ["shamatha_score"]
