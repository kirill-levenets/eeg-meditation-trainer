"""Every session ending saves; the end card adds notes or deletes with confirmation; notes are never silently lost (#39)."""

import os
import tempfile

import pytest
from kivy.base import EventLoop
from kivy.uix.popup import Popup

import app.ui.app_manager as am
import app.ui.history_flow as history_flow
from app.config import APP
from app.session.manager import SessionState
from app.storage.database import DatabaseManager
from app.ui.theme import StyledButton
from tests._app import (
    calls_of,
    frames,
    frames_until,
    open_history,
    popup_titles,
    popups,
    program_mode,
    start_ticked_by_hand,
    tap,
)


def _sessions(app) -> list[dict]:
    return app._db.get_all_sessions(app._current_user_id)


def _stored(app, sid) -> tuple | None:
    row = app._db.get_session(sid)
    ticks = app._db._conn.execute("SELECT COUNT(*) FROM metrics WHERE session_id = ?", (sid,)).fetchone()[0]
    return (row["duration"], ticks) if row else None


@pytest.fixture
def card(fresh_app, monkeypatch):
    """The app with a session just ended, its end card open: `app.sid` is the session, `app.toasts` what the app
    acknowledged, `app.notes_writes` each notes text written."""
    app = fresh_app
    start_ticked_by_hand(app, ticks=4)
    app._stop_and_save(reason="timer")
    frames()
    app.sid = app._live_screen.summary_session_id
    assert app.sid is not None
    app.toasts, app.notes_writes = [], []
    monkeypatch.setattr(am, "show_toast", app.toasts.append)
    write = app._db.update_session_notes
    monkeypatch.setattr(app._db, "update_session_notes",
                        lambda sid, **fields: (app.notes_writes.append(fields.get("notes")), write(sid, **fields))[1])
    return app


def _type(app, notes: str) -> None:
    app._live_screen._summary_notes.text = notes


def _card_open(app) -> bool:
    return app._live_screen.summary_session_id is not None


# --- Stop: one confirmed path, the same save as every other ending ---------------------------------------------

def test_user_stop_confirms_then_takes_the_shared_save_path(fresh_app):
    app = fresh_app
    start_ticked_by_hand(app, ticks=4)
    app._on_stop()
    (confirm,) = popups()
    assert confirm.title == "Stop session?" and _sessions(app) == []
    assert app._session.manager.state == SessionState.RUNNING  # nothing ends before the answer
    tap(confirm.content, "Stop")
    frames()
    (saved,) = _sessions(app)
    assert _stored(app, saved["id"])[1] == 4 and _card_open(app)


def test_user_stop_derives_the_idle_series_and_clears_the_training_marker(fresh_app, monkeypatch):
    app = fresh_app
    program_mode(app, [{"minutes": 5, "target": 60, "formula": {"name": "Deep", "formula": "alpha1"}}])
    start_ticked_by_hand(app, ticks=2)
    program_mode(app, [])  # the editor emptied meanwhile: what the idle graph is derived from after the ending
    marks = calls_of(monkeypatch, app._live_screen, "set_training_series")
    assert app._session.program_run.active and app._live_screen.graph.is_visible("program_formula")
    app._stop_and_save(reason="user")
    frames()
    assert not app._session.program_run.active and marks[-1] == (None,)
    assert not app._live_screen.graph.is_visible("program_formula")  # the live graph's idle series derived again
    assert _card_open(app)


# --- A Stop confirmed after the session already ended another way keeps it ------------------------------------

@pytest.mark.parametrize("ended_by", ["headset off", "timer"])
def test_a_stop_confirmed_after_the_session_ended_another_way_keeps_it(fresh_app, ended_by):
    # A slow phone handled the Stop tap late: the session had ended meanwhile (the headset switched off, or the timer),
    # and its stop had saved it. v1.4.0's confirm then found no stats and took its Discard branch, deleting the session.
    app = fresh_app
    start_ticked_by_hand(app, ticks=240)
    app._session.manager._start_time -= 120  # two minutes in
    app._session.checkpoint_or_report()
    sid = app._session.recorder.session_id
    app._on_stop()  # the user's Stop tap, handled while the session still runs: its dialog opens
    (confirm,) = popups()
    if ended_by == "headset off":  # the stale-data stop queued behind the tap
        app._stop_and_save(reason="stale_data")
    else:  # the tick thread saved the timed session; its UI teardown runs on the main thread
        app._finalize_stop_ui(app._session.persist("timer"), sid)
    saved = _stored(app, sid)
    assert saved is not None and saved[0] >= 119 and saved[1] == 240
    tap(confirm.content, "Stop")  # the user confirms the Stop
    frames()
    assert _stored(app, sid) == saved and len(_sessions(app)) == 1  # still there, unchanged


# --- Delete: only after confirmation, through the shared delete -------------------------------------------------

def _gone(app, sid) -> None:
    """Until the delete's worker and its main-thread half have both run."""
    frames_until(lambda: app._db.get_session(sid) is None and app._history_screen.session_by_id(sid) is None)
    frames()


def test_card_delete_without_confirmation_deletes_nothing(card):
    card._shown.on_delete()
    assert popup_titles() == ["Delete session"]
    assert card._db.get_session(card.sid) is not None and _card_open(card)


def test_card_delete_confirmed_removes_the_session_and_stops_the_gong(card, monkeypatch):
    open_history(card, card.sid)
    card._switch_screen("live_session")
    bells = calls_of(monkeypatch, card._audio, "stop_timer_bell")
    reloads = calls_of(monkeypatch, card._history_screen, "load_sessions")
    card._shown.on_delete()
    (confirm,) = popups()
    tap(confirm.content, "Delete")  # the user confirms
    _gone(card, card.sid)
    assert card._db.get_session(card.sid) is None and bells and not _card_open(card)
    assert card._history_screen.session_by_id(card.sid) is None and reloads == []  # the row goes in place: no rebuild


def test_history_row_delete_removes_its_row_in_place(card, monkeypatch):
    open_history(card, card.sid)
    reloads = calls_of(monkeypatch, card._history_screen, "load_sessions")
    card._history.delete_sessions([card.sid])
    _gone(card, card.sid)
    assert card._history_screen.session_by_id(card.sid) is None and reloads == []


# --- Notes: typed notes are kept; empty or untouched notes write nothing ---------------------------------------

def test_typed_notes_are_saved_on_ok(card, monkeypatch):
    bells = calls_of(monkeypatch, card._audio, "stop_timer_bell")
    _type(card, "calm, then sleepy")
    card._shown.on_ok()
    assert card.notes_writes == ["calm, then sleepy"] and card._db.get_session(card.sid)["notes"] == "calm, then sleepy"
    assert card.toasts == ["Notes saved"] and bells and not _card_open(card)


def test_saved_then_edited_notes_persist_the_edit_on_ok(card):
    _type(card, "first")
    card._shown.on_save_notes()
    assert _card_open(card)  # Save notes keeps the card open
    _type(card, "first, then more")
    card._shown.on_ok()
    assert card.notes_writes == ["first", "first, then more"]


def test_empty_notes_write_nothing_on_ok(card):
    card._shown.on_ok()
    assert card.notes_writes == [] and card.toasts == []


def test_unchanged_notes_write_nothing_more_on_ok(card):
    _type(card, "same")
    card._shown.on_save_notes()
    card._shown.on_ok()
    assert card.notes_writes == ["same"] and card.toasts == ["Notes saved"]


def test_saved_notes_cleared_before_ok_are_cleared_in_the_db(card):
    _type(card, "abc")
    card._shown.on_save_notes()
    _type(card, "")
    card._shown.on_ok()
    assert card.notes_writes == ["abc", ""]


def test_save_notes_on_already_saved_text_confirms_without_writing(card):
    _type(card, "kept")
    card._shown.on_save_notes()
    card._shown.on_save_notes()
    assert card.notes_writes == ["kept"] and card.toasts == ["Notes saved", "Notes saved"]


def test_app_pause_with_the_card_open_flushes_typed_notes(card):
    card._settings_screen.threshold = 62  # changed, not yet written: the pause saves the settings too
    _type(card, "written before the phone locked")
    assert card.on_pause() is True
    assert card.notes_writes == ["written before the phone locked"]
    assert card._db.get_user_setting(card._current_user_id, "threshold") == "62"


def _ended_in_its_own_app(build_app):
    """A private app (the test closes or restores it) with a session just ended, its end card open: (app, sid)."""
    app = build_app()
    start_ticked_by_hand(app, ticks=4)
    app._stop_and_save(reason="timer")
    frames()
    return app, app._live_screen.summary_session_id


def _notes_on_disk(sid) -> str | None:
    db = DatabaseManager(db_path=APP.DB_PATH)
    try:
        return db.get_session(sid)["notes"]
    finally:
        db.close()


def test_app_exit_with_the_card_open_flushes_typed_notes_before_the_db_closes(build_app):
    app, sid = _ended_in_its_own_app(build_app)
    _type(app, "written before closing the window")
    app.on_stop()
    assert _notes_on_disk(sid) == "written before closing the window"


@pytest.mark.parametrize("hook", ["on_pause", "on_stop"])
def test_leaving_during_a_restore_writes_no_notes(build_app, hook):
    app, sid = _ended_in_its_own_app(build_app)
    app._settings_screen.threshold = 62
    _type(app, "typed")
    app._on_db_replaced()
    getattr(app, hook)()
    if hook == "on_pause":
        app._db.close()
    assert not _notes_on_disk(sid)
    db = DatabaseManager(db_path=APP.DB_PATH)
    try:
        assert db.get_user_setting(app._current_user_id, "threshold") != "62"  # nor the settings
    finally:
        db.close()


def test_a_failed_notes_save_is_reported_not_toasted(card, monkeypatch):
    reported = []
    monkeypatch.setattr(history_flow, "report_soft_error", lambda label, detail, **k: reported.append(label))
    monkeypatch.setattr(card._db, "update_session_notes", lambda sid, **fields: False)
    _type(card, "lost?")
    card._shown.on_ok()
    assert reported == ["notes_save_failed"] and card.toasts == []
    assert card._shown._saved_notes == ""


# --- The confirm dialog: Cancel, tap-outside and back all count as cancel --------------------------------------

@pytest.fixture
def confirm(fresh_app):
    """(popup, answers): the app's confirm, open; `answers` records "ok" and "cancel" as they run."""
    answers: list = []
    fresh_app._confirm_action("Stop session?", "msg", "Stop", lambda: answers.append("ok"),
                              on_cancel=lambda: answers.append("cancel"))
    for _ in range(3):
        EventLoop.idle()
    (popup,) = [w for w in EventLoop.window.children if isinstance(w, Popup)]
    return popup, answers


def _buttons(popup) -> dict:
    return {w.text: w for w in popup.walk(restrict=True) if isinstance(w, StyledButton)}


def test_closing_the_confirm_without_ok_runs_on_cancel_once(confirm):
    popup, answers = confirm
    popup.dismiss()  # tap outside / Android back / Cancel all end here
    for _ in range(3):
        EventLoop.idle()
    assert answers == ["cancel"]


def test_ok_on_the_confirm_does_not_run_on_cancel(confirm):
    popup, answers = confirm
    _buttons(popup)["Stop"].dispatch("on_release")
    for _ in range(3):
        EventLoop.idle()
    assert answers == ["ok"]


def test_a_second_ok_during_the_fade_out_does_not_run_the_action_again(confirm):
    popup, answers = confirm
    ok = _buttons(popup)["Stop"]
    ok.dispatch("on_release")
    ok.dispatch("on_release")  # Kivy still delivers taps while the popup fades out
    assert answers == ["ok"]


def test_ok_right_after_cancel_does_not_run_the_action(confirm):
    popup, answers = confirm
    buttons = _buttons(popup)
    buttons["Cancel"].dispatch("on_release")
    buttons["Stop"].dispatch("on_release")
    assert answers == ["cancel"]


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
