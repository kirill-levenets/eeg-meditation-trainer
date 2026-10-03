"""Session detail notes are never lost: Save acknowledges, leaving the detail saves an edit, nothing else writes (#40)."""

from unittest.mock import MagicMock

import pytest
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager

from app.ui.app_manager import EEGMeditationApp
from app.ui.diary_screen import DiaryScreen
from app.ui.history_screen import HistoryScreen

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

    diary.set_save_notes_callback(save)
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


def _app() -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._db.update_session_notes.return_value = True
    app._toast = MagicMock()
    app._history_screen = MagicMock()
    app._live_screen = MagicMock()
    app._live_screen.summary_session_id = None
    app._summary_saved_notes = ""
    app._save_user_settings = MagicMock()
    app._restoring = False
    app._is_paused = False
    return app


def test_an_unrated_session_stays_unrated_when_only_its_notes_change():
    app = _app()
    _sm, diary, _saves = _detail(dict(SESSION, mood_rating=0))  # the slider shows 3
    diary.set_save_notes_callback(app._on_save_notes)
    diary._notes_input.text = "notes only"
    diary.flush_notes()
    app._db.update_session_notes.assert_called_once_with(7, notes="notes only", tags=None, mood_rating=None)


def test_save_rates_an_unrated_session_as_shown():
    app = _app()
    _sm, diary, _saves = _detail(dict(SESSION, mood_rating=0))  # the slider shows 3
    diary.set_save_notes_callback(app._on_save_notes)
    diary._on_save_pressed()
    app._db.update_session_notes.assert_called_once_with(7, notes="calm start", tags="morning", mood_rating=3)
    app._toast.assert_called_once_with("Notes saved")


def test_a_failed_save_on_leave_is_not_retried_when_the_app_pauses_later(monkeypatch):
    # Leaving already tried and reported it; retrying on every pause repeated the error, e.g. for a deleted session.
    import app.ui.app_manager as am
    reported = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    app = _app()
    app._db.update_session_notes.return_value = False
    sm, diary, _saves = _detail()
    diary.set_save_notes_callback(app._on_save_notes)
    app._diary_screen = diary
    app._sm = sm
    diary._notes_input.text = "edited"
    sm.current = "history"
    assert app._db.update_session_notes.call_count == 1
    app.on_pause()
    assert app._db.update_session_notes.call_count == 1
    assert reported == ["notes_save_failed"]


def test_app_pause_on_the_detail_saves_an_edit_and_acknowledges_it():
    app = _app()
    _sm, diary, _saves = _detail()
    diary.set_save_notes_callback(app._on_save_notes)
    app._diary_screen = diary
    app._sm = _sm
    diary._notes_input.text = "typed before the phone locked"
    assert app.on_pause() is True
    app._db.update_session_notes.assert_called_once_with(7, notes="typed before the phone locked",
                                                         tags=None, mood_rating=None)
    app._toast.assert_called_once_with("Notes saved")


def test_a_notes_save_updates_history_in_place_without_a_reload():
    app = _app()
    history = HistoryScreen()
    history.load_sessions([dict(SESSION), dict(SESSION, id=8)])
    app._history_screen = history
    app._history_dirty = False
    assert app._save_session_notes(7, notes="new notes", tags="t", mood=2) is True
    assert app._history_dirty is False  # a reload would start the list from the top
    row = next(s for s in history._sessions if s["id"] == 7)
    assert (row["notes"], row["tags"], row["mood_rating"]) == ("new notes", "t", 2)
    other = next(s for s in history._sessions if s["id"] == 8)
    assert other["notes"] == "calm start"


def test_a_notes_only_save_keeps_the_sessions_tags_and_mood_in_history():
    app = _app()
    history = HistoryScreen()
    history.load_sessions([dict(SESSION)])
    app._history_screen = history
    assert app._save_session_notes(7, notes="from the session-end card") is True
    row = history._sessions[0]
    assert (row["notes"], row["tags"], row["mood_rating"]) == ("from the session-end card", "morning", 4)


def test_a_notes_save_for_a_session_history_has_not_loaded_is_harmless():
    app = _app()
    history = HistoryScreen()
    history.load_sessions([dict(SESSION)])
    app._history_screen = history
    assert app._save_session_notes(99, notes="x") is True
    assert [s["id"] for s in history._sessions] == [7]
