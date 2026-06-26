from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp


def _app(db, uid):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._current_user_id = uid
    app._session_program_segments = []
    app._session_program_name = ""
    app._timer_mode = "simple"
    return app


def test_program_persist_roundtrip(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "sp_wire.db"))
    uid = db.create_user("u")

    app = _app(db, uid)
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._session_program_segments = segs
    app._session_program_name = "Ramp"
    app._timer_mode = "program"
    app._persist_session_program(uid)

    # A fresh AppManager on the same DB restores the persisted program + name + mode.
    fresh = _app(db, uid)
    fresh._load_session_program(uid)
    assert fresh._session_program_segments == segs
    assert fresh._session_program_name == "Ramp"
    assert fresh._timer_mode == "program"
    db.close()


def test_program_transition_fires_once_per_boundary():
    from app.session.session_program import SessionProgram
    p = SessionProgram([{"minutes": 1, "target": 50, "formula": "shamatha_score"},
                        {"minutes": 1, "target": 70, "formula": "meditation_score"}])
    fn = EEGMeditationApp._program_transition
    assert fn(-1, 0.0, p) == (0, p.segments[0], True)     # initial entry
    assert fn(0, 10.0, p) == (0, p.segments[0], False)    # same segment, no cross
    assert fn(0, 60.0, p) == (1, p.segments[1], True)     # crossed into segment 1
    assert fn(1, 120.0, p) == (1, p.segments[1], False)   # past end, clamps, no re-cross


def test_session_program_json_records_snapshot_not_live_editor():
    import json

    from app.session.session_program import SessionProgram
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    snapshot = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._active_program = SessionProgram(snapshot)
    app._session_program_active = True
    # A mid-session edit to the live editor must NOT change what's recorded.
    app._session_program_segments = [{"minutes": 99, "target": 1, "formula": "meditation_score"}]
    assert json.loads(app._session_program_json()) == snapshot
    # A simple session records nothing.
    app._session_program_active = False
    assert app._session_program_json() == ""


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
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = DatabaseManager(db_path=str(tmp_path / "u.db"))
    app._current_user_id = app._db.create_user("u")
    app._settings_screen = _StubSettings()
    app._live_screen = _StubLive()
    app._session_program_segments = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._session_program_name = ""
    app._timer_mode = "program"

    # New name -> added directly (no confirm popup path).
    app._on_program_save("Ramp")
    progs = app._db.get_saved_programs(app._current_user_id)
    assert [p["name"] for p in progs] == ["Ramp"]

    # Same name, edited segments -> overwrite (simulate the confirmed action).
    app._session_program_segments = [{"minutes": 5, "target": 90, "formula": "meditation_score"}]
    app._save_program(0, "Ramp")
    progs = app._db.get_saved_programs(app._current_user_id)
    assert len(progs) == 1 and progs[0]["segments"][0]["target"] == 90  # no duplicate

    # Load -> sets segments + mode + reflects the name back into the editor.
    app._timer_mode = "simple"
    app._load_program(0, "Ramp")
    assert app._timer_mode == "program"
    assert app._session_program_segments[0]["target"] == 90
    assert app._settings_screen.name == "Ramp"

    # Delete -> removed.
    app._delete_program(0)
    assert app._db.get_saved_programs(app._current_user_id) == []
    app._db.close()


def test_program_custom_formula_plots_and_marks():
    from unittest.mock import MagicMock

    from app.session.session_program import SessionProgram
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._on_main = lambda fn, *a: fn()  # run UI updates synchronously
    app._audio = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.elapsed_seconds = 0
    app._metrics_engine = MagicMock()
    app._metrics_engine.derive_bands.return_value = {}
    app._metrics_engine.compute_sqrt_relative_bands.return_value = {}
    graph = MagicMock()
    app._live_screen = MagicMock()
    app._live_screen.graph = graph
    app._timer_mode = "program"
    app._active_program = SessionProgram(
        [{"minutes": 1, "target": 120, "formula": {"name": "AlphaPwr", "formula": "alpha1"}}])
    app._program_seg_idx = -1
    app._program_formula_evs = {}
    app._program_segment_keys = []
    app._audio_metric_key = "shamatha_score"

    metrics = {"shamatha_score": 50}
    app._apply_program_tick(metrics, {"alpha1": 80.0})

    assert metrics["program_formula"] == 80.0          # custom formula evaluated + plotted
    assert app._program_audio_key == "program_formula"   # transient program drive
    assert app._audio_metric_key == "shamatha_score"     # user's baseline left untouched
    graph.set_series_name.assert_any_call("program_formula", "Program: AlphaPwr")  # "Program: <formula>"
    graph.set_visible.assert_any_call("program_formula", True)            # shown on graph
    app._live_screen.set_training_series.assert_called_with("program_formula")  # legend-marked


def test_program_shows_exactly_its_metric_set_whole_session():
    """A program shows EXACTLY its metric set for the whole session — built-in
    series + one program-formula line for its custom formula, shown throughout (not
    per-segment). Unrelated user selections are hidden during the program and
    restored on stop; only the legend marker moves as segments cross."""
    from app.session.session_program import SessionProgram
    from app.ui.live_session import LiveSessionScreen
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._program_prev_visibility = {}
    app._program_formula_evs = {}
    app._program_segment_keys = []
    app._session_program_active = True
    app._live_screen = LiveSessionScreen()
    graph = app._live_screen.graph
    # User had a custom slot + shamatha on; an unrelated metric off.
    graph.set_visible("custom_formula", True)
    graph.set_visible("shamatha_score", True)
    graph.set_visible("program_formula", False)

    prog = SessionProgram([
        {"minutes": 1, "target": 50, "formula": "shamatha_score"},
        {"minutes": 1, "target": 80, "formula": {"name": "Alpha", "formula": "alpha1"}},
    ])
    app._show_program_series(prog)
    # Exactly the program's set, shown the whole program:
    assert graph.is_visible("shamatha_score") is True      # built-in program metric
    assert graph.is_visible("program_formula") is True     # custom line shown all program
    assert graph.is_visible("custom_formula") is False     # user slot hidden (not in program)
    assert graph.series_name("program_formula") == "Program: Alpha"

    # A built-in segment KEEPS the program line visible — only the marker moves.
    app._apply_program_segment_ui(50, "shamatha_score", None)
    assert graph.is_visible("program_formula") is True
    # The custom segment relabels and keeps it visible.
    app._apply_program_segment_ui(80, "program_formula", "Program: Alpha")
    assert graph.is_visible("program_formula") is True
    assert graph.series_name("program_formula") == "Program: Alpha"

    app._restore_program_series()
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
    app._on_main = lambda fn, *a: fn()
    app._audio = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.elapsed_seconds = 0
    app._metrics_engine = MagicMock()
    app._metrics_engine.derive_bands.return_value = {}
    app._metrics_engine.compute_sqrt_relative_bands.return_value = {}
    app._program_prev_visibility = {}
    app._program_formula_evs = {}
    app._program_segment_keys = []
    app._session_program_active = True
    app._audio_metric_key = "shamatha_score"
    app._live_screen = LiveSessionScreen()
    g = app._live_screen.graph

    prog = SessionProgram([
        {"minutes": 1, "target": 50, "formula": "shamatha_score"},
        {"minutes": 1, "target": 75, "formula": {"name": "A", "formula": "alpha1"}},
        {"minutes": 1, "target": 90, "formula": {"name": "B", "formula": "beta1"}},
    ])
    app._active_program = prog
    app._show_program_series(prog)

    # Three distinct lines, all visible the whole program.
    assert set(g.visible_keys()) == {"shamatha_score", "program_formula", "program_formula_2"}
    assert g.series_name("program_formula") == "Program: A"
    assert g.series_name("program_formula_2") == "Program: B"

    # Both custom lines are evaluated every tick into their own series.
    app._program_seg_idx = -1
    metrics = {"shamatha_score": 50}
    app._apply_program_tick(metrics, {"alpha1": 11.0, "beta1": 22.0})
    assert metrics["program_formula"] == 11.0
    assert metrics["program_formula_2"] == 22.0


def test_idle_program_preview_shows_program_set(tmp_path):
    """In program mode with a loaded program, the live graph previews EXACTLY the
    program's metric set before any session starts; switching to simple mode restores
    the user's saved selection (and a program's visible set is never persisted over it)."""
    from unittest.mock import MagicMock

    from app.metrics.custom_formula import CustomFormulaEvaluator
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
    app._formula_slots = [CustomFormulaEvaluator() for _ in range(3)]
    app._timer_mode = "program"
    app._session_program_segments = [
        {"minutes": 1, "target": 50, "formula": "shamatha_score"},
        {"minutes": 1, "target": 80, "formula": {"name": "Alpha", "formula": "alpha1"}},
    ]
    g = app._live_screen.graph

    app._refresh_live_program_series()  # idle preview
    assert set(g.visible_keys()) == {"shamatha_score", "program_formula"}
    assert g.series_name("program_formula") == "Program: Alpha"

    # A program governs the live graph -> its set must not be persisted as the manual one.
    app._persist_graph_series(g)
    assert db.get_user_json_setting(uid, "graph_series_live_metrics") == ["shamatha_score"]

    # Back to simple mode -> the saved selection (shamatha only) is restored.
    app._timer_mode = "simple"
    app._refresh_live_program_series()
    assert set(g.visible_keys()) == {"shamatha_score"}
    db.close()


def test_diary_rebuilds_stepped_threshold():
    import json

    from app.ui.diary_screen import DiaryScreen
    screen = DiaryScreen()
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"},
            {"minutes": 10, "target": 70, "formula": "meditation_score"}]
    screen.set_program(json.dumps(segs))   # parses + pushes steps to the metrics graph
    assert screen._metrics_graph.threshold_value_at(0) == 50.0
    assert screen._metrics_graph.threshold_value_at(2400) == 70.0
    screen.set_program("")                  # clears the stepped line for non-program sessions
    assert screen._metrics_graph.threshold_value_at(0) is None


def test_program_unsaved_changes_detection(tmp_path):
    from app.storage.database import DatabaseManager
    db = DatabaseManager(db_path=str(tmp_path / "unsaved.db"))
    uid = db.create_user("u")
    db.add_saved_program(uid, "Ramp", [{"minutes": 10, "target": 50, "formula": "shamatha_score"}])
    app = _app(db, uid)

    app._session_program_segments = []           # nothing loaded
    app._session_program_name = ""
    assert app._program_has_unsaved_changes() is False

    app._session_program_segments = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._session_program_name = "Ramp"           # clean load, matches saved
    assert app._program_has_unsaved_changes() is False

    app._session_program_segments = [{"minutes": 20, "target": 50, "formula": "shamatha_score"}]
    assert app._program_has_unsaved_changes() is True   # edited

    app._session_program_name = ""               # unnamed but non-empty
    assert app._program_has_unsaved_changes() is True
    db.close()
