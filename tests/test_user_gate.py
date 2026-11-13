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

import pytest
from kivy.core.window import Window

import app.ui.app_manager as am
from app.session.manager import SessionState
from app.session.session_run import Phase
from app.storage.database import DatabaseManager
from app.ui.history_flow import sessions_for_view
from app.ui.settings_screen import SettingsScreen
from app.ui.startup import resolve_startup_user
from app.ui.widgets.user_picker import UserPickerForm
from tests._app import (
    frames,
    frames_until,
    popup_titles,
    runner_alive,
    start_connecting,
    start_ticked_by_hand,
)

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
    rows = sessions_for_view(db, a)
    assert len(rows) == 2 and all(r["user_id"] == a for r in rows)


def test_unset_user_shows_nothing_never_leaks_all_profiles():
    db = _fresh()
    _two_users_with_sessions(db)
    assert sessions_for_view(db, None) == []


# --- gate enforcement: an unresolved user disables the app until selection ---

@pytest.fixture
def gated(build_app):
    """The app at its gate: a profile exists, none was last used."""
    return build_app(lambda db: db.create_user("old"))


def _session_rows(app) -> int:
    return app._db._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def _checkpointed_session(app) -> None:
    """A mock session with two ticks, already written by a checkpoint (the 60 s flush, a pause)."""
    start_ticked_by_hand(app, ticks=2)
    app._session.checkpoint_or_report()
    assert _session_rows(app) == 1


def test_deleting_active_profile_mid_session_discards_it_and_regates(fresh_app):
    # #2/#3: the running session is discarded (not saved as an orphan), and the
    # app re-enters the gate instead of running with no user.
    app = fresh_app
    _checkpointed_session(app)
    app._profiles.on_delete(app._current_user_id)
    frames_until(app._gate.shown)
    assert _session_rows(app) == 0 and app._current_user_id is None  # discarded, not saved-then-orphaned
    assert app._session.manager.state not in (SessionState.RUNNING, SessionState.PAUSED) and app._session.run is None
    assert app._gate.shown() and app._bottom_nav.disabled  # re-gated


def test_deleting_the_last_profile_while_none_is_active_regates(gated):
    # #4: no profile is active and the last one goes: the app must still gate, never be usable with zero profiles.
    frames_until(gated._gate.shown)
    gated._gate._gate_popup.dismiss()  # as if the popup were lost
    old = gated._db.get_all_users()[0]["id"]
    gated._profiles.on_delete(old)
    frames_until(gated._gate.shown)
    assert gated._gate.shown() and gated._gate.active() and gated._db.get_all_users() == []


@pytest.mark.parametrize("current, shown", [(2, "Current: B"), (None, "Current: none"), (9, "Current: none")])
def test_settings_names_the_active_profile_or_none(current, shown):
    # None while the gate is up; an id the list doesn't hold must not leave the previous profile's name showing.
    screen = SettingsScreen()
    screen._profile_current_label.text = "Current: A"
    screen.populate_users([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], current)
    assert screen._profile_current_label.text == shown


def _gate_form(app) -> UserPickerForm:
    frames_until(app._gate.shown)
    return next(w for w in app._gate._gate_popup.walk() if isinstance(w, UserPickerForm))


def test_reopen_gate_when_selection_left_no_user(gated):
    # #5: a failed pick/create at the gate must not strand the app (nav disabled, no popup).
    form = _gate_form(gated)
    form._on_create(" ")  # the gate's own handler, given a name it doesn't take
    assert not gated._gate.shown()
    frames_until(gated._gate.shown)
    assert gated._gate.shown() and gated._current_user_id is None and gated._bottom_nav.disabled


def test_reopen_gate_noop_when_user_resolved(gated):
    form = _gate_form(gated)
    form._name_input.text = "new"
    form._on_create_pressed()
    frames()
    assert gated._current_user_id is not None and not gated._gate.shown() and not gated._bottom_nav.disabled
    assert popup_titles() == []


def test_discard_running_session_deletes_partial_row_and_resets_ui(fresh_app):
    # #1/#5/#12: the 60s flush may already have written a session row under the
    # doomed profile — discard must delete it and reuse the shared UI teardown.
    app = fresh_app
    _checkpointed_session(app)
    app._discard_running_session()
    frames()
    assert _session_rows(app) == 0  # orphan removed
    assert app._session.recorder.session_id is None and app._session.recorder._buffer == []
    assert app._session.run is None and not runner_alive(app)
    assert app._live_screen._btn_stop.disabled and not app._live_screen._btn_start.disabled  # the idle controls
    assert popup_titles() == []  # no end card for a session that is gone


def test_restore_refused_while_session_running(fresh_app):
    # #3: a restore closes the DB and relaunches — a running session would be
    # silently dropped. The entry point must refuse with an explanation.
    app = fresh_app
    app._on_start()
    app._backup_flow.on_restore_pressed()
    assert popup_titles() == ["Session in progress"]  # explained, not silent; the restore flow never started


def test_restore_refused_during_bt_connect_window(fresh_app, monkeypatch):
    # round-4: state is IDLE while connecting, but the tick thread is live and
    # the session auto-starts on connect — must still refuse.
    app = fresh_app
    start_connecting(app, monkeypatch)
    assert app._session.manager.state == SessionState.IDLE and app._session.run.phase is Phase.CONNECTING
    app._backup_flow.on_restore_pressed()
    assert popup_titles() == ["Session in progress"]


def test_delete_active_profile_discards_during_bt_connect(fresh_app, monkeypatch):
    # round-4: same connecting-window gap for the profile-delete discard guard.
    app = fresh_app
    start_connecting(app, monkeypatch)
    app._profiles.on_delete(app._current_user_id)
    frames_until(app._gate.shown)
    assert app._session.run is None and not runner_alive(app)  # connecting session halted
    assert app._current_user_id is None and app._gate.shown()


def test_on_resume_during_restore_reshows_relaunch_popup(build_app):
    # #9: if Android resumed the process post-restore, the DB is shut down —
    # block behind the relaunch popup instead of running on a no-op DB.
    app = build_app()
    app._on_db_replaced()
    app.on_pause()
    app._relaunch_popup.dismiss()  # the process came back without it
    app._relaunch_popup = None
    app.on_resume()
    frames()
    assert popup_titles() == ["Restore complete"] and not app._gate.shown()


def test_a_resume_with_no_profile_reopens_the_gate(gated):
    # The process survived in the background with no active profile: the app is never usable without one.
    frames_until(gated._gate.shown)
    gated._gate._gate_popup.dismiss()  # the popup did not survive with it
    gated.on_pause()
    assert not gated._gate.shown()
    gated.on_resume()
    frames_until(gated._gate.shown)
    assert gated._gate.shown() and gated._bottom_nav.disabled


def test_gate_active_during_schedule_window_before_popup_exists(gated):
    # #5: un-escapable even before the popup is created (nav disabled, no user).
    assert not gated._gate.shown() and gated._gate.active() is True and gated._bottom_nav.disabled
    frames_until(gated._gate.shown)
    assert popup_titles() == ["Select Profile"]  # the modal follows


def test_gate_not_active_when_user_resolved(fresh_app):
    app = fresh_app
    assert app._gate.active() is False and not app._bottom_nav.disabled


def test_gate_back_first_press_warns_second_exits(gated, monkeypatch):
    # #4: a gate with no exit traps a fresh-install user. Double-back must quit.
    toasts, stops = [], []
    monkeypatch.setattr(am, "show_toast", toasts.append)
    monkeypatch.setattr(gated, "stop", lambda: stops.append(True))
    frames_until(gated._gate.shown)  # over the gate's own popup: back must not be left to dismiss it
    assert gated._on_keyboard(Window, 27, 0, None, []) is True  # consumed
    assert toasts == ["Press back again to exit"] and stops == [] and gated._gate.active()  # warned, still gated
    assert gated._on_keyboard(Window, 27, 0, None, []) is True  # second press < 2s
    assert stops == [True]  # exits


def test_open_user_gate_dedupes_but_always_disables_nav(gated):
    # #7/#8: never stack two gate popups; nav must be disabled even when deduped.
    gated._bottom_nav.disabled = False
    gated._gate.open(0)  # one is already scheduled (pre-popup window)
    assert gated._bottom_nav.disabled is True  # enforced despite dedupe
    frames_until(gated._gate.shown)
    frames()
    assert popup_titles() == ["Select Profile"]
    gated._bottom_nav.disabled = False
    gated._gate.open(0)  # a gate popup is already open
    frames()
    assert gated._bottom_nav.disabled is True and popup_titles() == ["Select Profile"]  # no second popup


def test_unresolvable_last_user_routes_to_the_gate():
    # The startup decision that build() acts on: an unresolved user -> gate (None).
    db = _fresh()
    db.create_user("Kirill")
    db.set_setting("last_user_id", "999")  # reinstall / restored-DB shape
    assert resolve_startup_user(db) is None
