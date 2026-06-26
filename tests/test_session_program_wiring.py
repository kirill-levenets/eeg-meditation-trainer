from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp


def _app(db, uid):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._current_user_id = uid
    app._session_program_segments = []
    app._timer_mode = "simple"
    return app


def test_program_persist_roundtrip(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "sp_wire.db"))
    uid = db.create_user("u")

    app = _app(db, uid)
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._session_program_segments = segs
    app._timer_mode = "program"
    app._persist_session_program(uid)

    # A fresh AppManager on the same DB restores the persisted program + mode.
    fresh = _app(db, uid)
    fresh._load_session_program(uid)
    assert fresh._session_program_segments == segs
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
    def set_session_programs(self, progs):
        self.programs = progs

    def refresh_duration_preset(self, enabled, minutes, program_active=False):
        self.preset = (enabled, minutes, program_active)


def test_saved_program_unique_upsert_load_delete(tmp_path):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = DatabaseManager(db_path=str(tmp_path / "u.db"))
    app._current_user_id = app._db.create_user("u")
    app._settings_screen = _StubSettings()
    app._live_screen = _StubLive()
    app._session_program_segments = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
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
