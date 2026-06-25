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
