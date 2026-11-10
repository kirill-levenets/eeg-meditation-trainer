"""Session detail notes are never lost: Save acknowledges, leaving the detail saves an edit, nothing else writes (#40)."""

import pytest
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager

import app.ui.app_manager as am
import app.ui.history_flow as history_flow
from app.ui.diary_screen import DiaryScreen
from app.ui.hooks import wire
from tests._app import open_detail, open_history, saved_session

SESSION = {"id": 7, "date_time": "2026-09-20T10:00:00", "duration": 600, "avg_shamatha": 55,
           "notes": "calm start", "tags": "morning", "mood_rating": 4}


def _detail(session: dict = SESSION, saved: bool = True):
    """The diary on screen in a ScreenManager, showing `session`; returns (manager, diary, saves)."""
    sm = ScreenManager(transition=NoTransition())
    diary = DiaryScreen()
    sm.add_widget(Screen(name="history"))
    sm.add_widget(diary)
    saves = []

    def save(sid, notes=None, tags=None, mood=None):
        saves.append((sid, notes, tags, mood))
        return saved

    wire(diary, on_save_notes=save)
    diary.show_session_detail(dict(session))
    sm.current = "diary"
    return sm, diary, saves


# ---- the screen ----


def test_leaving_the_detail_saves_an_edit():
    sm, diary, saves = _detail()
    diary._notes_input.text = "calm start, then drowsy"
    sm.current = "history"  # Back, a bottom-nav tab and Android back all leave the screen this way
    assert saves == [(7, "calm start, then drowsy", None, None)]  # only what changed


@pytest.mark.parametrize("mood_rating", [4, 0])  # 0: unrated, shown as the slider's middle (3)
def test_leaving_without_an_edit_writes_nothing(mood_rating):
    sm, _diary, saves = _detail(dict(SESSION, mood_rating=mood_rating))
    sm.current = "history"
    assert saves == []


@pytest.mark.parametrize("edit, sent", [("tags", (7, None, "evening", None)), ("mood", (7, None, None, 2))])
def test_a_tag_or_mood_edit_alone_is_saved_on_leave(edit, sent):
    sm, diary, saves = _detail()
    if edit == "tags":
        diary._tags_input.text = "evening"
    else:
        diary._mood_slider.value = 2
    sm.current = "history"
    assert saves == [sent]


def test_save_then_leave_writes_once():
    sm, diary, saves = _detail()
    diary._notes_input.text = "edited"
    diary._on_save_pressed()
    sm.current = "history"
    assert saves == [(7, "edited", "morning", 4)]  # Save sends what the screen shows


def test_a_failed_save_stays_pending_and_is_tried_again_on_leave():
    sm, diary, saves = _detail(saved=False)
    diary._notes_input.text = "edited"
    diary._on_save_pressed()
    sm.current = "history"
    assert [s[1] for s in saves] == ["edited", "edited"]


def test_flush_saves_an_edit_once():
    _sm, diary, saves = _detail()
    diary._notes_input.text = "edited"
    diary.flush_notes()
    diary.flush_notes()
    assert len(saves) == 1


# ---- the app ----


@pytest.fixture
def app(fresh_app, monkeypatch):
    """The app; `app.toasts` records what it acknowledged."""
    fresh_app.toasts = []
    monkeypatch.setattr(am, "show_toast", fresh_app.toasts.append)
    return fresh_app


def _noted_session(app, mood: int = 4) -> int:
    """A saved session with notes, tags and a mood (0: unrated, the slider shows 3)."""
    sid = saved_session(app)
    app._db.update_session_notes(sid, notes="calm start", tags="morning", mood_rating=mood)
    return sid


def _stored(app, sid: int) -> tuple:
    row = app._db.get_session(sid)
    return row["notes"], row["tags"], row["mood_rating"]


def test_an_unrated_session_stays_unrated_when_only_its_notes_change(app):
    sid = _noted_session(app, mood=0)
    open_detail(app, sid)
    app._diary_screen._notes_input.text = "notes only"
    app._diary_screen.flush_notes()
    assert _stored(app, sid) == ("notes only", "morning", 0)


def test_save_rates_an_unrated_session_as_shown(app):
    sid = _noted_session(app, mood=0)
    open_detail(app, sid)
    app._diary_screen._on_save_pressed()
    assert _stored(app, sid) == ("calm start", "morning", 3)
    assert app.toasts == ["Notes saved"]


def test_a_failed_save_on_leave_is_not_retried_when_the_app_pauses_later(app, monkeypatch):
    # Leaving already tried and reported it; retrying on every pause repeated the error, e.g. for a deleted session.
    reported, tries = [], []
    monkeypatch.setattr(history_flow, "report_soft_error", lambda label, detail, **k: reported.append(label))
    open_detail(app, _noted_session(app))
    monkeypatch.setattr(app._db, "update_session_notes", lambda *a, **k: tries.append(k) or False)
    app._diary_screen._notes_input.text = "edited"
    app._switch_screen("history")
    assert len(tries) == 1
    app.on_pause()
    assert len(tries) == 1
    assert reported == ["notes_save_failed"]


def test_app_pause_on_the_detail_saves_an_edit_and_acknowledges_it(app):
    sid = _noted_session(app)
    open_detail(app, sid)
    app._diary_screen._notes_input.text = "typed before the phone locked"
    assert app.on_pause() is True
    assert _stored(app, sid) == ("typed before the phone locked", "morning", 4)
    assert app.toasts == ["Notes saved"]


def _listed(app, sid: int) -> tuple:
    row = app._history_screen.session_by_id(sid)
    return row["notes"], row["tags"], row["mood_rating"]


def test_a_notes_save_updates_history_in_place_without_a_reload(app):
    first, second = _noted_session(app), _noted_session(app)
    open_history(app, second)
    assert app._history._history_dirty is False
    assert app._history.save_notes(first, notes="new notes", tags="t", mood=2) is True
    assert app._history._history_dirty is False  # a reload would start the list from the top
    assert _listed(app, first) == ("new notes", "t", 2)
    assert _listed(app, second) == ("calm start", "morning", 4)


def test_a_notes_only_save_keeps_the_sessions_tags_and_mood_in_history(app):
    sid = _noted_session(app)
    open_history(app, sid)
    assert app._history.save_notes(sid, notes="from the session-end card") is True
    assert _listed(app, sid) == ("from the session-end card", "morning", 4)


def test_a_notes_save_for_a_session_history_has_not_loaded_is_harmless(app):
    listed = _noted_session(app)
    open_history(app, listed)
    later = app._db.checkpoint_session(None, {"duration": 2}, [], user_id=app._current_user_id, session_name="later")
    assert app._history.save_notes(later, notes="x") is True
    assert [s["id"] for s in app._history_screen._sessions] == [listed]
    assert app._db.get_session(later)["notes"] == "x"
