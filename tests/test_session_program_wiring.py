from unittest.mock import MagicMock

import pytest

from app.metrics.formula_slots import FormulaSlots
from app.session.session_program import SessionProgram
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.program_run import ProgramRun
from tests._graph_series import make_graph_series
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


def test_session_program_json_records_snapshot_not_live_editor():
    import json

    from app.session.session_program import SessionProgram
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    snapshot = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._program_run = make_run(program=SessionProgram(snapshot))
    # A mid-session edit to the live editor must NOT change what's recorded.
    app._program_settings = make_programs()
    app._program_settings.segments = [{"minutes": 99, "target": 1, "formula": "meditation_score"}]
    assert json.loads(app._program_run.segments_json()) == snapshot
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


def test_program_custom_formula_plots_and_marks():
    from unittest.mock import MagicMock

    from app.session.session_program import SessionProgram
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._audio = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.elapsed_seconds = 0
    graph = MagicMock()
    app._live_screen = MagicMock()
    app._live_screen.graph = graph
    app._timer_mode = "program"
    app._audio_metric_key = "shamatha_score"
    app._program_run = run = make_run(app)
    run.begin(SessionProgram([{"minutes": 1, "target": 120, "formula": {"name": "AlphaPwr", "formula": "alpha1"}}]),
              [], "")  # what a program session's start does

    metrics = {"shamatha_score": 50}
    run.tick(metrics, {"alpha1": 80.0})

    assert metrics["program_formula"] == 80.0          # custom formula evaluated + plotted
    assert run.audio_key == "program_formula"   # transient program drive
    assert app._audio_metric_key == "shamatha_score"     # user's baseline left untouched
    graph.set_series_name.assert_any_call("program_formula", "Program: AlphaPwr")  # "Program: <formula>"
    graph.set_visible.assert_any_call("program_formula", True)            # shown on graph
    app._live_screen.set_training_series.assert_called_with("program_formula")  # legend-marked


def test_a_segment_whose_formula_cant_run_drives_and_shows_shamatha():
    # Its segments sound, show and are scored on Shamatha, never on a key nothing computes (0: constant max noise).
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._audio = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.elapsed_seconds = 0
    graph = MagicMock()
    graph.series_keys.return_value = ["shamatha_score", "program_formula", "program_formula_2"]
    app._live_screen = MagicMock()
    app._live_screen.graph = graph
    app._formulas = FormulaSlots()
    app._audio_metric_key = "shamatha_score"
    app._program_run = run = make_run(app, info=MagicMock())
    run.begin(SessionProgram([{"minutes": 1, "target": 120, "formula": {"name": "Broken", "formula": "alpha1 +"}},
                              {"minutes": 1, "target": 80, "formula": {"name": "AlphaPwr", "formula": "alpha1"}}]),
              [], "")

    metrics = {"shamatha_score": 50}
    run.tick(metrics, {"alpha1": 80.0})

    assert run.audio_key == "shamatha_score"
    assert metrics.get(app._audio_drive_key(), 0) == 50  # what the tick sounds: shamatha, not 0
    app._session_manager.start_segment.assert_called_with("shamatha_score", 120)  # scored on what it sounds
    app._live_screen.set_training_series.assert_called_with("shamatha_score")
    assert run._info.call_args.args[0] == "Formula error in this program"  # the session's start says which
    shown = {c.args[0]: c.args[1] for c in graph.set_visible.call_args_list}
    assert shown == {"shamatha_score": True, "program_formula": False, "program_formula_2": True}
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
    from app.session.session_program import SessionProgram
    from app.ui.live_session import LiveSessionScreen
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = LiveSessionScreen()
    run = make_run(app)
    graph = app._live_screen.graph
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
    assert graph.is_visible("program_formula") is False    # not lingering as a user selection
    assert graph.is_visible("custom_formula") is True       # user slot restored


def test_program_with_two_distinct_customs_shows_three_lines():
    """A program with two DIFFERENT custom formulas plots each on its own line
    (program_formula + program_formula_2), so a 3-distinct-metric program shows 3
    lines — not one shared 'Program' line. The per-tick eval fills each line."""
    from unittest.mock import MagicMock

    from app.session.session_program import SessionProgram
    from app.ui.live_session import LiveSessionScreen
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._audio = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.elapsed_seconds = 0
    app._audio_metric_key = "shamatha_score"
    app._live_screen = LiveSessionScreen()
    run = make_run(app)
    g = app._live_screen.graph

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


def test_idle_program_preview_shows_program_set(tmp_path):
    """In program mode with a loaded program, the live graph previews EXACTLY the
    program's metric set before any session starts; switching to simple mode restores
    the user's saved selection (and a program's visible set is never persisted over it)."""
    from unittest.mock import MagicMock

    from app.metrics.formula_slots import FormulaSlots
    from app.session.manager import SessionState
    from app.ui.live_session import LiveSessionScreen
    db = DatabaseManager(db_path=str(tmp_path / "preview.db"))
    uid = db.create_user("u")
    db.set_user_json_setting(uid, "graph_series_live_metrics", ["shamatha_score"])

    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._current_user_id = uid
    app._live_screen = LiveSessionScreen()
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.IDLE  # not running
    app._formulas = FormulaSlots()
    app._program_settings = _program_settings(db, uid, live_screen=app._live_screen, session_manager=app._session_manager,
                              show_saved_series=lambda u: app._graph_series.apply_saved(app._live_screen.graph, u))
    app._graph_series = make_graph_series(app)
    app._program_settings.mode = "program"
    app._program_settings.segments = [
        {"minutes": 1, "target": 50, "formula": "shamatha_score"},
        {"minutes": 1, "target": 80, "formula": {"name": "Alpha", "formula": "alpha1"}},
    ]
    g = app._live_screen.graph

    app._program_settings.refresh_live_series()  # idle preview
    assert set(g.visible_keys()) == {"shamatha_score", "program_formula"}
    assert g.series_name("program_formula") == "Program: Alpha"

    # A program governs the live graph -> its set must not be persisted as the manual one.
    app._graph_series.persist(g)
    assert db.get_user_json_setting(uid, "graph_series_live_metrics") == ["shamatha_score"]

    # Back to simple mode -> the saved selection (shamatha only) is restored.
    app._program_settings.mode = "simple"
    app._program_settings.refresh_live_series()
    assert set(g.visible_keys()) == {"shamatha_score"}
    db.close()


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


def test_a_running_programs_series_are_not_saved_once_settings_is_switched_to_simple(tmp_path):
    """Settings → Timer can go back to simple during a program session (the edit waits for the next one): the live graph
    still shows the program's set, which closing the series picker must not save as the profile's own selection."""
    from app.metrics.formula_slots import FormulaSlots
    from app.session.session_program import SessionProgram
    from app.ui.live_session import LiveSessionScreen
    db = DatabaseManager(db_path=str(tmp_path / "running.db"))
    uid = db.create_user("u")
    db.set_user_json_setting(uid, "graph_series_live_metrics", ["shamatha_score"])
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._current_user_id = uid
    app._live_screen = LiveSessionScreen()
    app._formulas = FormulaSlots()
    app._program_run = make_run(app)
    app._program_run.begin(SessionProgram([{"minutes": 1, "target": 50, "formula": "meditation_score"}]), [], "")
    app._program_settings = _program_settings(db, uid)  # mode "simple": switched back mid-session
    app._graph_series = make_graph_series(app)
    app._graph_series.persist(app._live_screen.graph)
    assert db.get_user_json_setting(uid, "graph_series_live_metrics") == ["shamatha_score"]
    db.close()
