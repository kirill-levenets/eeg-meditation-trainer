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
    def set_session_programs(self, progs, current_name=""):
        self.programs = progs
        self.current_name = current_name

    def refresh_duration_preset(self, enabled, minutes, program_active=False):
        self.preset = (enabled, minutes, program_active)


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
    app._program_formula_ev = None
    app._audio_metric_key = "shamatha_score"

    metrics = {"shamatha_score": 50}
    app._apply_program_tick(metrics, {"alpha1": 80.0})

    assert metrics["program_formula"] == 80.0          # custom formula evaluated + plotted
    assert app._audio_metric_key == "program_formula"  # drives audio/goal
    graph.set_series_name.assert_any_call("program_formula", "AlphaPwr")  # named after formula
    graph.set_visible.assert_any_call("program_formula", True)            # shown on graph
    app._live_screen.set_training_series.assert_called_with("program_formula")  # legend-marked


def test_program_hides_user_custom_slots_for_uniqueness():
    """A custom-formula program hides the user's custom slots (so the same kind
    of line isn't shown twice) and restores them on stop."""
    from app.session.session_program import SessionProgram
    from app.ui.live_session import LiveSessionScreen
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = LiveSessionScreen()
    graph = app._live_screen.graph
    # User has a custom slot visible (via the picker/combobox).
    graph.set_visible("custom_formula", True)
    graph.set_visible("program_formula", False)

    prog = SessionProgram([{"minutes": 1, "target": 80,
                            "formula": {"name": "Alpha", "formula": "alpha1"}}])
    app._show_program_series(prog)
    assert graph.is_visible("program_formula") is True   # program's custom line shown
    assert graph.is_visible("custom_formula") is False    # user slot hidden (no duplicate)

    app._restore_program_series()
    assert graph.is_visible("program_formula") is False   # transient line cleared
    assert graph.is_visible("custom_formula") is True      # user slot restored


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
