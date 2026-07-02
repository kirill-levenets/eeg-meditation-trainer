"""The startup user gate: the app must resolve a CONCRETE user or prompt —
it must never continue usable with no resolved user (the #29 root cause).

`resolve_startup_user(db)` returns the uid to restore, or None meaning "you
must show the blocking user-select gate". The old code gated the setup UI on
`get_all_users()` emptiness, which let "users exist but last_user_id doesn't
resolve" (reinstall / restored DB / deleted active profile / corrupt setting)
slip through into a usable-but-unset state.
"""
import os
import shutil
import tempfile
from unittest.mock import MagicMock

import pytest

from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp, resolve_startup_user, sessions_for_view

_TMP_DIRS: list[str] = []


def _fresh() -> DatabaseManager:
    d = tempfile.mkdtemp()
    _TMP_DIRS.append(d)
    return DatabaseManager(db_path=os.path.join(d, "t.db"))


@pytest.fixture(autouse=True)
def _cleanup_tmp_dirs():
    yield
    while _TMP_DIRS:
        shutil.rmtree(_TMP_DIRS.pop(), ignore_errors=True)


def test_resolves_uid_when_last_user_is_valid():
    db = _fresh()
    uid = db.create_user("Kirill")
    db.set_setting("last_user_id", str(uid))
    assert resolve_startup_user(db) == uid


def test_none_on_empty_db():
    assert resolve_startup_user(_fresh()) is None


def test_none_when_users_exist_but_no_last_user_setting():
    db = _fresh()
    db.create_user("Kirill")  # user exists, but last_user_id never set
    assert resolve_startup_user(db) is None


def test_none_when_last_user_points_to_deleted_user():
    db = _fresh()
    db.create_user("Kirill")
    db.set_setting("last_user_id", "999")  # stale id, no such user
    assert resolve_startup_user(db) is None


def test_none_when_last_user_setting_is_corrupt():
    db = _fresh()
    db.create_user("Kirill")
    db.set_setting("last_user_id", "not-an-int")
    assert resolve_startup_user(db) is None


def test_none_when_last_user_is_zero_or_negative():
    # '0'/'-1' are not valid uids — reject explicitly, don't rely on get_user(0).
    db = _fresh()
    db.create_user("Kirill")
    for bad in ("0", "-1"):
        db.set_setting("last_user_id", bad)
        assert resolve_startup_user(db) is None


# --- history view scoping: no cross-profile leak when the user is unset ---

def _two_users_with_sessions(db) -> tuple[int, int]:
    a = db.create_user("A")
    b = db.create_user("B")
    for uid in (a, a, b):
        db._conn.execute(
            "INSERT INTO sessions (user_id, date_time, duration) VALUES (?, '2026-07-01', 60)",
            (uid,),
        )
    db._conn.commit()
    return a, b


def test_view_shows_only_the_current_users_sessions():
    db = _fresh()
    a, _b = _two_users_with_sessions(db)
    rows = sessions_for_view(db, a, show_all=False)
    assert len(rows) == 2 and all(r["user_id"] == a for r in rows)


def test_all_users_view_shows_every_session():
    db = _fresh()
    _two_users_with_sessions(db)
    assert len(sessions_for_view(db, None, show_all=True)) == 3


def test_unset_user_shows_nothing_never_leaks_all_profiles():
    db = _fresh()
    _two_users_with_sessions(db)
    assert sessions_for_view(db, None, show_all=False) == []


# --- gate enforcement: an unresolved user disables the app until selection ---

def test_on_pause_skips_settings_flush_during_restore():
    # #1: flushing in-memory settings during the restore relaunch window would
    # clobber the freshly-restored DB.
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._restoring = True
    app._save_user_settings = MagicMock()
    assert EEGMeditationApp.on_pause(app) is True
    app._save_user_settings.assert_not_called()


def test_on_pause_flushes_settings_normally():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._restoring = False
    app._save_user_settings = MagicMock()
    EEGMeditationApp.on_pause(app)
    app._save_user_settings.assert_called_once()


def test_deleting_active_profile_mid_session_discards_it_and_regates():
    # #2/#3: the running session is discarded (not saved as an orphan), and the
    # app re-enters the gate instead of running with no user.
    from app.session.manager import SessionState
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = 5
    app._view_all_users = False
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._discard_running_session = MagicMock()
    app._db = MagicMock()
    app._db.get_all_users.return_value = []       # last profile removed
    app._refresh_profile = MagicMock()
    app._open_user_gate = MagicMock()
    EEGMeditationApp._on_user_delete(app, 5)
    app._discard_running_session.assert_called_once()  # discarded, not saved-then-orphaned
    assert app._current_user_id is None
    app._open_user_gate.assert_called_once()            # re-gate


def test_deleting_last_profile_in_all_users_view_regates():
    # #4: current is None (All-Users), deleting the last profile must still gate.
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = None
    app._view_all_users = True
    app._session_manager = MagicMock()
    app._db = MagicMock()
    app._db.get_all_users.return_value = []
    app._refresh_profile = MagicMock()
    app._open_user_gate = MagicMock()
    EEGMeditationApp._on_user_delete(app, 9)
    app._open_user_gate.assert_called_once()
    assert app._view_all_users is False


def test_reopen_gate_when_selection_left_no_user():
    # #5: a failed pick/create at the gate must not strand the app (nav disabled, no popup).
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = None
    app._view_all_users = False
    app._refresh_profile = MagicMock()
    app._open_user_gate = MagicMock()
    EEGMeditationApp._reopen_gate_if_unresolved(app)
    app._open_user_gate.assert_called_once()


def test_reopen_gate_noop_when_user_resolved():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = 3
    app._view_all_users = False
    app._open_user_gate = MagicMock()
    EEGMeditationApp._reopen_gate_if_unresolved(app)
    app._open_user_gate.assert_not_called()


def test_discard_running_session_deletes_partial_row_and_resets_ui():
    # #1/#5/#12: the 60s flush may already have written a session row under the
    # doomed profile — discard must delete it and reuse the shared UI teardown.
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._stop_tick_thread = MagicMock()
    app._session_manager = MagicMock()
    app._eeg_stream = MagicMock()
    app._audio = MagicMock()
    app._db = MagicMock()
    app._current_session_id = 42     # partial flush happened
    app._metrics_buffer = [{"t": 1}]
    app._finalize_stop_ui = MagicMock()
    EEGMeditationApp._discard_running_session(app)
    app._db.delete_session.assert_called_once_with(42)   # orphan removed
    assert app._current_session_id is None
    assert app._metrics_buffer == []
    app._finalize_stop_ui.assert_called_once_with(None, None)  # shared teardown


def test_restore_refused_while_session_running():
    # #3: a restore closes the DB and relaunches — a running session would be
    # silently dropped. The entry point must refuse with an explanation.
    from app.session.manager import SessionState
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._info_popup = MagicMock()
    app._is_android = MagicMock()
    EEGMeditationApp._on_restore_pressed(app)
    app._info_popup.assert_called_once()      # explained, not silent
    app._is_android.assert_not_called()        # restore flow never started


def test_on_resume_during_restore_reshows_relaunch_popup():
    # #9: if Android resumed the process post-restore, the DB is shut down —
    # block behind the relaunch popup instead of running on a no-op DB.
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._is_paused = True
    app._restoring = True
    app._show_relaunch_popup = MagicMock()
    app._open_user_gate = MagicMock()
    EEGMeditationApp.on_resume(app)
    app._show_relaunch_popup.assert_called_once()
    app._open_user_gate.assert_not_called()


def test_gate_active_during_schedule_window_before_popup_exists():
    # #5: un-escapable even before the popup is created (nav disabled, no user).
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._bottom_nav = MagicMock()
    app._bottom_nav.disabled = True
    app._current_user_id = None
    app._view_all_users = False
    assert EEGMeditationApp._gate_active(app) is True


def test_gate_not_active_when_user_resolved():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._bottom_nav = MagicMock()
    app._bottom_nav.disabled = False
    app._current_user_id = 3
    app._view_all_users = False
    assert EEGMeditationApp._gate_active(app) is False


def test_gate_back_first_press_warns_second_exits(monkeypatch):
    # #4: a gate with no exit traps a fresh-install user. Double-back must quit.
    import app.ui.app_manager as am
    fake_app_cls = MagicMock()
    monkeypatch.setattr(am, "App", fake_app_cls)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._last_back_time = 0.0
    app._android_toast = MagicMock()
    assert EEGMeditationApp._handle_gate_back(app) is True   # consumed
    app._android_toast.assert_called_once()                   # warned
    fake_app_cls.get_running_app.return_value.stop.assert_not_called()
    assert EEGMeditationApp._handle_gate_back(app) is True   # second press < 2s
    fake_app_cls.get_running_app.return_value.stop.assert_called_once()  # exits


def test_open_user_gate_dedupes_but_always_disables_nav(monkeypatch):
    # #7/#8: never stack two gate popups; nav must be disabled even when deduped.
    import app.ui.app_manager as am
    fake_clock = MagicMock()
    monkeypatch.setattr(am, "Clock", fake_clock)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._bottom_nav = MagicMock()
    app._bottom_nav.disabled = False
    app._gate_popup = MagicMock()   # a gate popup is already open
    app._gate_event = None
    EEGMeditationApp._open_user_gate(app, 0)
    assert app._bottom_nav.disabled is True          # enforced despite dedupe
    fake_clock.schedule_once.assert_not_called()      # no second popup
    app._gate_popup = None
    app._gate_event = MagicMock()   # one already scheduled (pre-popup window)
    EEGMeditationApp._open_user_gate(app, 0)
    fake_clock.schedule_once.assert_not_called()      # still no stacking


def test_open_user_gate_disables_bottom_nav_and_opens_modal():
    app = EEGMeditationApp.__new__(EEGMeditationApp)  # bypass heavy __init__/build
    app._bottom_nav = MagicMock()
    app._show_first_run_popup = MagicMock()
    EEGMeditationApp._open_user_gate(app, 0)
    assert app._bottom_nav.disabled is True  # app not usable until a user is chosen


def test_unresolvable_last_user_routes_to_the_gate():
    # The startup decision that build() acts on: an unresolved user -> gate (None).
    db = _fresh()
    db.create_user("Kirill")
    db.set_setting("last_user_id", "999")  # reinstall / restored-DB shape
    assert resolve_startup_user(db) is None
