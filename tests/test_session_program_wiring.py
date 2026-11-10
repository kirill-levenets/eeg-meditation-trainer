from unittest.mock import MagicMock

import pytest

from app.session.session_program import SessionProgram
from app.storage.database import DatabaseManager
from app.ui.live_session import LiveSessionScreen
from app.ui.program_run import ProgramRun
from tests._app import (
    FedSession,
    calls_of,
    frames,
    popups,
    program_mode,
    reload_with,
    start_connecting,
    start_ticked_by_hand,
)
from tests._program_run import make_run
from tests._program_settings import make_programs


def _program_settings(db, uid, **kw):
    return make_programs(db, uid, **kw)


def test_program_persist_roundtrip(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "sp_wire.db"))
    uid = db.create_user("u")

    programs = _program_settings(db, uid)
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    programs.segments = segs
    programs.name = "Ramp"
    programs.mode = "program"
    programs.persist(uid)

    # A fresh profile load on the same DB restores the persisted program + name + mode.
    fresh = _program_settings(db, uid)
    fresh.load(uid)
    assert fresh.segments == segs
    assert fresh.name == "Ramp"
    assert fresh.mode == "program"
    db.close()


def test_program_transition_fires_once_per_boundary():
    from app.session.session_program import SessionProgram
    p = SessionProgram([{"minutes": 1, "target": 50, "formula": "shamatha_score"},
                        {"minutes": 1, "target": 70, "formula": "meditation_score"}])
    fn = ProgramRun.transition
    assert fn(-1, 0.0, p) == (0, p.segments[0], True)     # initial entry
    assert fn(0, 10.0, p) == (0, p.segments[0], False)    # same segment, no cross
    assert fn(0, 60.0, p) == (1, p.segments[1], True)     # crossed into segment 1
    assert fn(1, 120.0, p) == (1, p.segments[1], False)   # past end, clamps, no re-cross


def test_session_program_json_records_the_program_it_began_with():
    import json

    snapshot = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    # What the session records is the run's own program: a mid-session edit in Settings changes the editor, not this.
    assert json.loads(make_run(program=SessionProgram(snapshot)).segments_json()) == snapshot
    # A simple session records nothing.
    assert make_run().segments_json() == ""


class _StubSettings:
    timer_enabled = False
    timer_minutes = 20

    def set_saved_programs(self, progs):
        self.saved = progs

    def load_program(self, segs, mode):
        self.loaded = (segs, mode)

    def set_program_name(self, name):
        self.name = name

    def set_program_mode(self, mode):
        self.mode = mode

    def confirm_program_saved(self):
        self.confirmed = True


class _StubLive:
    def __init__(self):
        from unittest.mock import MagicMock
        self.graph = MagicMock()
        self.graph.series_keys.return_value = []  # empty catalog -> preview is a no-op
        self.graph.is_visible.return_value = False

    def set_session_programs(self, progs, current_name=""):
        self.programs = progs
        self.current_name = current_name

    def refresh_duration_preset(self, enabled, minutes, program_active=False):
        self.preset = (enabled, minutes, program_active)

    def set_training_series(self, key):
        self.training = key


def test_saved_program_unique_upsert_load_delete(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "u.db"))
    uid = db.create_user("u")
    settings = _StubSettings()
    programs = _program_settings(db, uid, timer_section=settings, live_screen=_StubLive())
    programs.segments = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    programs.mode = "program"

    # New name -> added directly (no confirm popup path).
    programs.on_save("Ramp")
    progs = db.get_saved_programs(uid)
    assert [p["name"] for p in progs] == ["Ramp"]

    # Same name, edited segments -> overwrite (simulate the confirmed action).
    programs.segments = [{"minutes": 5, "target": 90, "formula": "meditation_score"}]
    programs._save(0, "Ramp")
    progs = db.get_saved_programs(uid)
    assert len(progs) == 1 and progs[0]["segments"][0]["target"] == 90  # no duplicate

    # Load -> sets segments + mode + reflects the name back into the editor.
    programs.mode = "simple"
    programs._load(0, "Ramp")
    assert programs.mode == "program"
    assert programs.segments[0]["target"] == 90
    assert settings.name == "Ramp"

    # Delete -> removed.
    programs._delete(0)
    assert db.get_saved_programs(uid) == []
    db.close()


def test_program_custom_formula_plots_and_marks(fresh_app, monkeypatch):
    app = fresh_app
    program_mode(app, [{"minutes": 1, "target": 120, "formula": {"name": "AlphaPwr", "formula": "alpha1"}}])
    fed = FedSession(app, monkeypatch)
    marks = calls_of(monkeypatch, app._live_screen, "set_training_series")
    metrics = {"shamatha_score": 50}
    fed.tick({**fed.raw, "alpha1": 80.0}, metrics)
    graph = app._live_screen.graph
    assert metrics["program_formula"] == 80.0  # custom formula evaluated + plotted
    assert app._program_run.audio_key == "program_formula"  # transient program drive
    assert app._settings_store.value("audio_metric") == "shamatha_score"  # user's baseline left untouched
    assert graph.series_name("program_formula") == "Program: AlphaPwr"  # "Program: <formula>"
    assert graph.is_visible("program_formula")  # shown on graph
    assert marks[-1] == ("program_formula",)  # legend-marked


def test_a_segment_whose_formula_cant_run_drives_and_shows_shamatha(fresh_app, monkeypatch):
    # Its segments sound, show and are scored on Shamatha, never on a key nothing computes (0: constant max noise).
    app = fresh_app
    program_mode(app, [{"minutes": 1, "target": 120, "formula": {"name": "Broken", "formula": "alpha1 +"}},
                       {"minutes": 1, "target": 80, "formula": {"name": "AlphaPwr", "formula": "alpha1"}}])
    fed = FedSession(app, monkeypatch)
    marks = calls_of(monkeypatch, app._live_screen, "set_training_series")
    metrics = {"shamatha_score": 50}
    fed.tick({**fed.raw, "alpha1": 80.0}, metrics)
    graph, score = app._live_screen.graph, app._session_manager.live_score()
    assert app._program_run.audio_key == "shamatha_score"
    assert metrics.get(app._audio_metric.drive_key(), 0) == 50  # what the tick sounds: shamatha, not 0
    assert (score.value, score.target) == (50, 120)  # scored on what it sounds
    assert marks[-1] == ("shamatha_score",)
    assert [p.title for p in popups()] == ["Formula error in this program"]  # the session's start says which
    assert (graph.is_visible("shamatha_score"), graph.is_visible("program_formula"),
            graph.is_visible("program_formula_2")) == (True, False, True)
    assert metrics["program_formula_2"] == 80.0  # the segment whose formula runs keeps its own line


@pytest.mark.parametrize("formulas, listed", [
    ([{"name": "Broken", "formula": "alpha1 +"}], '"Broken"'),
    ([{"name": "A", "formula": "alpha1 +"}, {"name": "B", "formula": "*"}], '"A", "B"'),  # no plural to get wrong
    ([{"name": "Calm", "formula": "alpha1 * 2"}], None),
])
def test_a_program_start_names_the_formulas_that_cant_run_in_a_popup(formulas, listed):
    # A toast is gone in two seconds and was clipped at the larger text sizes; a meditator may not be looking.
    info = MagicMock()
    run = make_run(info=info)
    run.begin(SessionProgram([{"minutes": 1, "target": 50, "formula": f} for f in formulas]), [], "P")
    if listed is None:
        info.assert_not_called()
    else:
        info.assert_called_once_with("Formula error in this program", f"Can't run {listed}: Shamatha is used instead."
                                     "\nSettings › Timer / Program edits the program.")


def test_the_start_popup_waits_for_the_next_frame():
    # The start finishes its setup first, whatever the popup does.
    queued, info = [], MagicMock()
    run = make_run(on_main=queued.append, info=info)
    run.begin(SessionProgram([{"minutes": 1, "target": 50, "formula": {"name": "Broken", "formula": "*"}}]), [], "P")
    info.assert_not_called()
    assert len(queued) == 1
    queued[0]()
    assert info.call_args.args[0] == "Formula error in this program"


def test_program_shows_exactly_its_metric_set_whole_session():
    """A program shows EXACTLY its metric set for the whole session — built-in
    series + one program-formula line for its custom formula, shown throughout (not
    per-segment). Unrelated user selections are hidden during the program and
    restored on stop; only the legend marker moves as segments cross."""
    graph = LiveSessionScreen().graph
    run = make_run(live_screen=MagicMock(graph=graph))
    # User had a custom slot + shamatha on; an unrelated metric off.
    graph.set_visible("custom_formula", True)
    graph.set_visible("shamatha_score", True)
    graph.set_visible("program_formula", False)

    prog = SessionProgram([
        {"minutes": 1, "target": 50, "formula": "shamatha_score"},
        {"minutes": 1, "target": 80, "formula": {"name": "Alpha", "formula": "alpha1"}},
    ])
    run.begin(prog, [], "")
    # Exactly the program's set, shown the whole program:
    assert graph.is_visible("shamatha_score") is True      # built-in program metric
    assert graph.is_visible("program_formula") is True     # custom line shown all program
    assert graph.is_visible("custom_formula") is False     # user slot hidden (not in program)
    assert graph.series_name("program_formula") == "Program: Alpha"

    # A built-in segment KEEPS the program line visible — only the marker moves.
    run._segment_ui("shamatha_score", None)
    assert graph.is_visible("program_formula") is True
    # The custom segment relabels and keeps it visible.
    run._segment_ui("program_formula", "Program: Alpha")
    assert graph.is_visible("program_formula") is True
    assert graph.series_name("program_formula") == "Program: Alpha"

    run.end()
    assert graph.is_visible("program_formula") is False  # not lingering as a user selection; the ending re-derives the rest
    assert graph.program_keys == frozenset()


def test_program_with_two_distinct_customs_shows_three_lines():
    """A program with two DIFFERENT custom formulas plots each on its own line
    (program_formula + program_formula_2), so a 3-distinct-metric program shows 3
    lines — not one shared 'Program' line. The per-tick eval fills each line."""
    g = LiveSessionScreen().graph
    run = make_run(session_manager=MagicMock(elapsed_seconds=0), live_screen=MagicMock(graph=g))

    prog = SessionProgram([
        {"minutes": 1, "target": 50, "formula": "shamatha_score"},
        {"minutes": 1, "target": 75, "formula": {"name": "A", "formula": "alpha1"}},
        {"minutes": 1, "target": 90, "formula": {"name": "B", "formula": "beta1"}},
    ])
    run.begin(prog, [], "")

    # Three distinct lines, all visible the whole program.
    assert set(g.visible_keys()) == {"shamatha_score", "program_formula", "program_formula_2"}
    assert g.series_name("program_formula") == "Program: A"
    assert g.series_name("program_formula_2") == "Program: B"

    # Both custom lines are evaluated every tick into their own series.
    metrics = {"shamatha_score": 50}
    run.tick(metrics, {"alpha1": 11.0, "beta1": 22.0})
    assert metrics["program_formula"] == 11.0
    assert metrics["program_formula_2"] == 22.0


def _saved_live_series(app) -> list | None:
    return app._db.get_user_json_setting(app._current_user_id, "graph_series_live_metrics")


def test_idle_program_preview_shows_program_set(fresh_app, monkeypatch):
    """In program mode with a loaded program, the live graph previews EXACTLY the program's metric set before any
    session starts, and an ending derives it again; simple mode restores the user's saved selection. A program's set
    is never persisted over it."""
    app = fresh_app
    reload_with(app, {"graph_series_live_metrics": ["shamatha_score"]})
    g = app._live_screen.graph
    program_mode(app, [{"minutes": 1, "target": 50, "formula": "meditation_score"},  # outside the saved selection
                       {"minutes": 1, "target": 80, "formula": {"name": "Alpha", "formula": "alpha1"}}])
    preview = {"meditation_score", "program_formula"}
    assert set(g.visible_keys()) == preview and g.program_keys == preview  # idle preview
    assert g.series_name("program_formula") == "Program: Alpha"
    app._graph_series.persist(g)  # a program governs the live graph: its set is not the manual one
    assert _saved_live_series(app) == ["shamatha_score"]

    for begun in (False, True):  # a start cancelled while it connects, then a program session that ran
        if begun:
            app._change_setting("use_mock", True)
            start_ticked_by_hand(app, ticks=1)
            app._stop_and_save()
            frames()
            app._shown.on_ok()
        else:
            start_connecting(app, monkeypatch)
            app._on_connect_cancel()
        assert g.program_keys == preview and g.is_visible("meditation_score")  # the idle series derived again
        app._graph_series.persist(g)
        assert _saved_live_series(app) == ["shamatha_score"]

    app._program_settings.on_changed([])  # the program emptied in Settings > Timer: no preview, the saved selection
    assert set(g.visible_keys()) == {"shamatha_score"} and g.program_keys == frozenset()
    app._program_settings.on_changed([{"minutes": 1, "target": 50, "formula": "meditation_score"}])
    assert g.program_keys == {"meditation_score"}

    app._program_settings.on_mode_change("simple")  # back to simple: the saved selection, the user's own again
    assert set(g.visible_keys()) == {"shamatha_score"} and g.program_keys == frozenset()
    g.set_visible("distraction", True)
    app._graph_series.persist(g)
    assert set(_saved_live_series(app)) == {"shamatha_score", "distraction"}


def test_diary_rebuilds_stepped_threshold():
    import json

    from app.ui.diary_screen import DiaryScreen
    screen = DiaryScreen()
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"},
            {"minutes": 10, "target": 70, "formula": "meditation_score"}]
    screen.set_program(json.dumps(segs))   # parses + pushes steps to the metrics graph
    assert screen._metrics_graph.threshold_steps == [(0, 50.0), (1200, 70.0)]
    screen.set_program("")                  # clears the stepped line for non-program sessions
    assert screen._metrics_graph.threshold_steps is None


def test_program_unsaved_changes_detection(tmp_path):
    from app.storage.database import DatabaseManager
    db = DatabaseManager(db_path=str(tmp_path / "unsaved.db"))
    uid = db.create_user("u")
    db.add_saved_program(uid, "Ramp", [{"minutes": 10, "target": 50, "formula": "shamatha_score"}])
    programs = _program_settings(db, uid)

    programs.segments = []           # nothing loaded
    programs.name = ""
    assert programs.has_unsaved_changes() is False

    programs.segments = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    programs.name = "Ramp"           # clean load, matches saved
    assert programs.has_unsaved_changes() is False

    programs.segments = [{"minutes": 20, "target": 50, "formula": "shamatha_score"}]
    assert programs.has_unsaved_changes() is True   # edited

    programs.name = ""               # unnamed but non-empty
    assert programs.has_unsaved_changes() is True
    db.close()


def test_a_running_programs_series_are_not_saved_once_settings_is_switched_to_simple(fresh_app):
    """Settings → Timer can go back to simple during a program session (the edit waits for the next one): the live graph
    still shows the program's set, which closing the series picker must not save as the profile's own selection."""
    app = fresh_app
    reload_with(app, {"graph_series_live_metrics": ["shamatha_score"]})
    program_mode(app, [{"minutes": 1, "target": 50, "formula": "meditation_score"}])
    start_ticked_by_hand(app)
    app._program_settings.on_mode_change("simple")  # switched back mid-session
    assert app._live_screen.graph.visible_keys() == ["meditation_score"]
    app._graph_series.persist(app._live_screen.graph)
    assert _saved_live_series(app) == ["shamatha_score"]
