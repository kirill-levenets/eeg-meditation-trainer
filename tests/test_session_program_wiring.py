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
