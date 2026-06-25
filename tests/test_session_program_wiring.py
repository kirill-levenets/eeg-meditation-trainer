import os
import tempfile

from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp


def _app():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    path = os.path.join(tempfile.gettempdir(), "sp_wire.db")
    if os.path.exists(path):
        os.remove(path)
    app._db = DatabaseManager(db_path=path)
    app._current_user_id = app._db.create_user("u")
    app._session_program_segments = []
    app._timer_mode = "simple"
    return app


def test_program_persist_roundtrip():
    app = _app()
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"}]
    app._session_program_segments = segs
    app._timer_mode = "program"
    app._persist_session_program(app._current_user_id)
    fresh = _app()
    fresh._current_user_id = app._current_user_id
    fresh._db = app._db
    fresh._load_session_program(app._current_user_id)
    assert fresh._session_program_segments == segs
    assert fresh._timer_mode == "program"
    app._db.close()
