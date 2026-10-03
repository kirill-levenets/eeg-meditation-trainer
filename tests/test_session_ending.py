"""Every session ending saves; the end card adds notes or deletes with confirmation; notes are never silently lost (#39)."""

import os
import tempfile
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.uix.popup import Popup

from app.session.manager import SessionState
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp

SID = 42


def _app() -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._db.update_session_notes.return_value = True
    app._audio = MagicMock()
    app._live_screen = MagicMock()
    app._live_screen.summary_session_id = SID
    app._live_screen.summary_notes = ""
    app._summary_saved_notes = ""
    app._toast = MagicMock()
    app._history_screen = MagicMock()
    app._refresh_history = MagicMock()
    return app


def _notes_writes(app):
    return [c.kwargs.get("notes") for c in app._db.update_session_notes.call_args_list]


# --- Stop: one confirmed path, the same save as every other ending ---------------------------------------------

def test_user_stop_confirms_then_takes_the_shared_save_path():
    app = _app()
    app._session_manager = MagicMock(state=SessionState.RUNNING)
    app._waiting_for_bt = False
    app._stop_tick_thread = MagicMock()
    app._stop_and_save = MagicMock()
    app._confirm_action = MagicMock()
    app._on_stop()
    title, _msg, ok_text, on_ok = app._confirm_action.call_args.args[:4]
    assert (title, ok_text) == ("Stop session?", "Stop")
    assert app._confirm_action.call_args.kwargs["on_cancel"] == app._cancel_stop
    app._stop_and_save.assert_not_called()
    on_ok()
    app._stop_and_save.assert_called_once_with(reason="user")
    assert not hasattr(EEGMeditationApp, "_finish_stop")


def test_user_stop_restores_program_series_and_clears_the_training_marker():
    app = _app()
    app._stop_tick_thread = MagicMock()
    app._persist_session_data = MagicMock(return_value={"duration": 30})
    app._current_session_id = SID
    for name in ("_reload_live_graphs_from_mirror", "_restore_program_series", "_release_wake_lock",
                 "_stop_session_keep_alive_service"):
        setattr(app, name, MagicMock())
    app._timer_state = MagicMock()
    app._session_manager = MagicMock()
    app._stop_and_save(reason="user")
    app._persist_session_data.assert_called_once_with("user")
    app._restore_program_series.assert_called_once()
    app._live_screen.set_training_series.assert_called_with(None)
    app._live_screen.show_summary.assert_called_once_with(SID, {"duration": 30})


# --- Delete: only after confirmation, through the shared delete -------------------------------------------------

def test_card_delete_without_confirmation_deletes_nothing():
    app = _app()
    app._confirm_action = MagicMock()
    app._on_summary_delete()
    app._db.delete_session.assert_not_called()
    app._live_screen.hide_summary.assert_not_called()


def test_card_delete_confirmed_removes_the_session_and_stops_the_gong():
    app = _app()
    app._confirm_action = MagicMock()
    app._on_summary_delete()
    app._confirm_action.call_args.args[3]()  # the user confirms
    app._db.delete_session.assert_called_once_with(SID)
    app._audio.stop_timer_bell.assert_called_once()
    app._live_screen.hide_summary.assert_called_once()
    app._history_screen.remove_sessions.assert_called_once_with([SID])
    app._refresh_history.assert_not_called()  # the row goes in place; no full-screen rebuild spinner


def test_history_row_delete_removes_its_row_in_place():
    app = _app()
    app._on_delete_session(SID)
    app._db.delete_session.assert_called_once_with(SID)
    app._history_screen.remove_sessions.assert_called_once_with([SID])
    app._refresh_history.assert_not_called()


# --- Notes: typed notes are kept; empty or untouched notes write nothing ---------------------------------------

def test_typed_notes_are_saved_on_ok():
    app = _app()
    app._live_screen.summary_notes = "calm, then sleepy"
    app._on_summary_ok()
    assert _notes_writes(app) == ["calm, then sleepy"]
    app._toast.assert_called_once_with("Notes saved")
    app._audio.stop_timer_bell.assert_called_once()
    app._live_screen.hide_summary.assert_called_once()


def test_saved_then_edited_notes_persist_the_edit_on_ok():
    app = _app()
    app._live_screen.summary_notes = "first"
    app._on_summary_save_notes()
    app._live_screen.hide_summary.assert_not_called()  # Save notes keeps the card open
    app._live_screen.summary_notes = "first, then more"
    app._on_summary_ok()
    assert _notes_writes(app) == ["first", "first, then more"]


@pytest.mark.parametrize("typed,saved", [("", ""), ("same", "same")])
def test_empty_or_unchanged_notes_write_nothing_on_ok(typed, saved):
    app = _app()
    app._live_screen.summary_notes = typed
    app._summary_saved_notes = saved
    app._on_summary_ok()
    app._db.update_session_notes.assert_not_called()
    app._toast.assert_not_called()


def test_saved_notes_cleared_before_ok_are_cleared_in_the_db():
    app = _app()
    app._live_screen.summary_notes = "abc"
    app._on_summary_save_notes()
    app._live_screen.summary_notes = ""
    app._on_summary_ok()
    assert _notes_writes(app) == ["abc", ""]


def _leaving_app(notes: str, restoring: bool = False):
    app = _app()
    app._is_paused = False
    app._restoring = restoring
    app._save_user_settings = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.IDLE
    app._live_screen.summary_notes = notes
    return app


def test_app_pause_with_the_card_open_flushes_typed_notes():
    app = _leaving_app("written before the phone locked")
    assert app.on_pause() is True
    assert _notes_writes(app) == ["written before the phone locked"]
    app._save_user_settings.assert_called_once()


def test_app_exit_with_the_card_open_flushes_typed_notes_before_the_db_closes():
    app = _leaving_app("written before closing the window")
    app._db.close.side_effect = lambda: app._db.update_session_notes.assert_called()
    app.on_stop()
    assert _notes_writes(app) == ["written before closing the window"]
    app._db.close.assert_called_once()


@pytest.mark.parametrize("hook", ["on_pause", "on_stop"])
def test_leaving_during_a_restore_writes_no_notes(hook):
    app = _leaving_app("typed", restoring=True)
    getattr(app, hook)()
    app._db.update_session_notes.assert_not_called()
    app._save_user_settings.assert_not_called()


def test_a_failed_notes_save_is_reported_not_toasted(monkeypatch):
    import app.ui.app_manager as am
    app = _app()
    app._db.update_session_notes.return_value = False
    reported = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    app._live_screen.summary_notes = "lost?"
    app._on_summary_ok()
    assert reported == ["notes_save_failed"]
    app._toast.assert_not_called()
    assert app._summary_saved_notes == ""


# --- The confirm dialog: Cancel, tap-outside and back all count as cancel --------------------------------------

def _open_confirm(on_ok, on_cancel):
    from kivy.core.window import Window
    EventLoop.ensure_window()
    EEGMeditationApp.__new__(EEGMeditationApp)._confirm_action("Stop session?", "msg", "Stop", on_ok, on_cancel=on_cancel)
    for _ in range(3):
        EventLoop.idle()
    return next(w for w in Window.children if isinstance(w, Popup))


def test_closing_the_confirm_without_ok_runs_on_cancel_once():
    on_ok, on_cancel = MagicMock(), MagicMock()
    popup = _open_confirm(on_ok, on_cancel)
    popup.dismiss()  # tap outside / Android back / Cancel all end here
    for _ in range(3):
        EventLoop.idle()
    on_cancel.assert_called_once()
    on_ok.assert_not_called()


def test_ok_on_the_confirm_does_not_run_on_cancel():
    from app.ui.theme import StyledButton
    on_ok, on_cancel = MagicMock(), MagicMock()
    popup = _open_confirm(on_ok, on_cancel)
    ok = next(w for w in popup.walk() if isinstance(w, StyledButton) and w.text == "Stop")
    ok.dispatch("on_release")
    for _ in range(3):
        EventLoop.idle()
    on_ok.assert_called_once()
    on_cancel.assert_not_called()


def _tap(btn):
    btn.dispatch("on_release")
    for _ in range(3):
        EventLoop.idle()


def test_a_second_ok_during_the_fade_out_does_not_run_the_action_again():
    from app.ui.theme import StyledButton
    on_ok, on_cancel = MagicMock(), MagicMock()
    popup = _open_confirm(on_ok, on_cancel)
    ok = next(w for w in popup.walk() if isinstance(w, StyledButton) and w.text == "Stop")
    ok.dispatch("on_release")
    ok.dispatch("on_release")  # Kivy still delivers taps while the popup fades out
    on_ok.assert_called_once()
    on_cancel.assert_not_called()


def test_ok_right_after_cancel_does_not_run_the_action():
    from app.ui.theme import StyledButton
    on_ok, on_cancel = MagicMock(), MagicMock()
    popup = _open_confirm(on_ok, on_cancel)
    buttons = {w.text: w for w in popup.walk() if isinstance(w, StyledButton)}
    buttons["Cancel"].dispatch("on_release")
    buttons["Stop"].dispatch("on_release")
    on_cancel.assert_called_once()
    on_ok.assert_not_called()


def test_cancelling_stop_restarts_the_tick_only_for_a_running_session():
    app = _app()
    app._start_tick_thread = MagicMock()
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._cancel_stop()
    app._start_tick_thread.assert_called_once()
    app._session_manager.state = SessionState.PAUSED
    app._cancel_stop()
    app._start_tick_thread.assert_called_once()


# --- Storage: a notes save touches only the fields it is given -------------------------------------------------

def test_notes_update_keeps_the_fields_it_is_not_given():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(db_path=path)
    try:
        uid = db.create_user("t")
        sid = db.save_session({"duration": 60, "avg_meditation": 50, "avg_shamatha": 50}, user_id=uid)
        assert db.update_session_notes(sid, notes="n1", tags="calm", mood_rating=4) is True
        assert db.update_session_notes(sid, notes="n2") is True
        row = db.get_session(sid)
        assert (row["notes"], row["tags"], row["mood_rating"]) == ("n2", "calm", 4)
        assert db.update_session_notes(sid + 999, notes="x") is False
        assert db.update_session_notes(sid) is False
    finally:
        db.close()
        os.remove(path)


def test_save_notes_on_already_saved_text_confirms_without_writing():
    app = _app()
    app._live_screen.summary_notes = "kept"
    app._summary_saved_notes = "kept"
    app._on_summary_save_notes()
    app._db.update_session_notes.assert_not_called()
    app._toast.assert_called_once_with("Notes saved")
