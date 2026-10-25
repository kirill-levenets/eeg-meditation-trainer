"""A profile pick, a session start or an idle threshold change leaves the Session screen showing no earlier session."""
from dataclasses import replace
from unittest.mock import MagicMock

import app.ui.app_manager as am
from app.session.manager import LiveScore, SessionManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.live_mirror import LiveMirror
from app.ui.live_session import LiveSessionScreen
from tests._recorder import make_recorder

METRICS = {"shamatha_score": 71, "distraction": 22, "sinking": 9, "native_attention": 55, "native_meditation": 63}
SCORE = LiveScore(value=71, target=60, streak=12, average=64.4, segmented=False, time_above=120, longest_streak=48)


def _texts(screen) -> list[str]:
    return [label.text for label in screen._stat_labels]


def _finished_screen() -> LiveSessionScreen:
    screen = LiveSessionScreen()
    screen.update_stats(SCORE)
    screen.set_start_time(1_760_000_000.0)
    screen.update_timer("05:00")
    screen.update_state("FINISHED")
    screen.graph.add_point(METRICS)
    return screen


def test_clear_readout_shows_what_a_fresh_screen_shows():
    fresh = LiveSessionScreen()
    screen = _finished_screen()
    assert _texts(screen) != _texts(fresh)
    screen.clear_readout()
    assert _texts(screen) == _texts(fresh)
    assert screen._timer_label.text == fresh._timer_label.text == "00:00"
    assert screen._state_label.text == fresh._state_label.text == "IDLE"
    assert tuple(screen._state_label.color) == tuple(fresh._state_label.color)
    screen.update_timer("00:01")
    assert screen._timer_label.text == "00:01"  # no start time of the last session in front of it


def _choose_avg(monkeypatch, screen) -> None:
    monkeypatch.setattr("app.ui.live_session.App.get_running_app", MagicMock)  # the choice is saved with the profile
    screen._stats_toggle.buttons["aggregate"].dispatch("on_release")


def test_the_avg_switch_shows_the_last_sessions_numbers(monkeypatch):
    screen = _finished_screen()
    _choose_avg(monkeypatch, screen)
    assert "64" in _texts(screen)


def test_the_avg_switch_after_a_clear_shows_no_sessions_numbers(monkeypatch):
    screen = _finished_screen()
    screen.clear_readout()
    _choose_avg(monkeypatch, screen)
    assert "64" not in _texts(screen)


def test_clear_live_display_empties_the_graphs_their_mirrors_and_the_readout():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = _finished_screen()
    app._mirror = LiveMirror()
    app._mirror.record(METRICS, {"score_target": 70, "score_key": "shamatha_score"}, {"alpha1": 1.0, "raw_eeg_waveform": [1.0]})
    app._clear_live_display()
    mirror = app._mirror
    assert (list(mirror.metrics), list(mirror.bands), list(mirror.waveform), mirror.last_metrics) == ([], [], [], {})
    assert app._live_screen.graph.total_points == 0
    assert app._live_screen._timer_label.text == "00:00"
    assert _texts(app._live_screen) == _texts(LiveSessionScreen())


def _owner_app(active, shown) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._load_user_settings = MagicMock()
    app._mark_history_dirty = MagicMock()
    app._current_user_id = active
    app._live_display_uid = shown
    app._drop_shown_session = MagicMock()
    return app


def test_picking_another_profile_drops_the_shown_session_before_the_switch():
    app = _owner_app(active=1, shown=1)
    seen = []
    app._drop_shown_session.side_effect = lambda keep_notes: seen.append((keep_notes, app._current_user_id))
    app._activate_user(2)
    assert seen == [(True, 1)]
    assert app._current_user_id == 2


def test_re_picking_the_shown_profile_keeps_its_session_even_mid_session():
    app = _owner_app(active=1, shown=1)
    app._activate_user(1)
    app._drop_shown_session.assert_not_called()
    app._load_user_settings.assert_called_once_with(1)


def test_a_cold_start_shows_nothing_to_drop():
    app = _owner_app(active=None, shown=None)
    app._activate_user(1)
    app._drop_shown_session.assert_not_called()


def _screen_app(card) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = MagicMock()
    app._live_screen.summary_session_id = card
    app._audio = MagicMock()
    app._flush_summary_notes = MagicMock()
    app._clear_live_display = MagicMock()
    app._live_display_uid = 1
    return app


def test_dropping_the_shown_session_closes_its_open_card_saving_the_notes():
    app = _screen_app(card=7)
    app._drop_shown_session(keep_notes=True)
    app._flush_summary_notes.assert_called_once()
    app._audio.stop_timer_bell.assert_called_once()
    app._live_screen.hide_summary.assert_called_once()
    app._clear_live_display.assert_called_once()
    assert app._live_display_uid is None


def test_dropping_with_no_card_open_leaves_a_ringing_bell_alone():
    app = _screen_app(card=None)
    app._drop_shown_session(keep_notes=True)
    app._audio.stop_timer_bell.assert_not_called()
    app._flush_summary_notes.assert_not_called()
    app._clear_live_display.assert_called_once()
    assert app._live_display_uid is None


def test_a_deleted_sessions_card_closes_unsaved_but_its_bell_stops():
    app = _screen_app(card=7)
    app._drop_shown_session(keep_notes=False)
    app._flush_summary_notes.assert_not_called()
    app._audio.stop_timer_bell.assert_called_once()
    app._live_screen.hide_summary.assert_called_once()


def test_an_idle_threshold_clear_keeps_the_owner_of_an_open_card():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = MagicMock()
    app._mirror = LiveMirror()
    app._mirror.metrics.append(METRICS)
    app._live_display_uid = 1
    app._clear_live_display()
    assert app._live_display_uid == 1  # a later switch to another profile still closes the card


def _deleting_app(shown) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._db.get_all_users.return_value = [{"id": 2}]
    app._current_user_id = 2
    app._live_display_uid = shown
    for name in ("_session_pipeline_live", "_mark_history_dirty", "_refresh_profile", "_program_settings",
                 "_open_user_gate", "_drop_shown_session"):
        setattr(app, name, MagicMock(return_value=False))
    return app


def test_deleting_the_shown_profile_drops_its_session_without_saving_notes():
    app = _deleting_app(shown=3)
    app._on_user_delete(3)
    app._drop_shown_session.assert_called_once_with(keep_notes=False)


def test_deleting_another_profile_leaves_the_shown_session():
    app = _deleting_app(shown=2)
    app._on_user_delete(3)
    app._drop_shown_session.assert_not_called()


def test_the_live_title_is_the_scored_series_name_on_the_graph_kept_until_the_readout_clears():
    screen = _finished_screen()
    screen.graph.set_series_name("custom_formula", "Alpha calm")
    screen.set_training_series("custom_formula")
    assert screen._stat_title_labels[0].text == "Alpha calm"
    screen.set_training_series(None)  # the session ended: the legend's mark goes, its numbers stay with their name
    assert screen._stat_title_labels[0].text == "Alpha calm"
    screen.clear_readout()
    assert screen._stat_title_labels[0].text == "Score"


def test_the_end_of_a_session_shows_its_numbers_before_its_scoring_is_reset():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = LiveSessionScreen()
    app._session_manager = sm = SessionManager()
    sm.start(threshold=50)
    sm.set_active_goal("shamatha_score")
    for value in (60, 70, 40):
        sm.add_metric({"shamatha_score": value})
    app._undo_session_setup = sm.reset  # what the real one does to the scoring
    app._mirror = LiveMirror()
    for name in ("_mark_history_dirty", "_settings_screen"):
        setattr(app, name, MagicMock())
    app._finalize_stop_ui({}, None)
    app._live_screen.set_stats_mode("aggregate")
    assert _texts(app._live_screen) == ["57", "1s", "1s"]


def test_a_profiles_stats_view_redraws_the_strip_not_just_the_button():
    screen = LiveSessionScreen()
    screen.set_stats_mode("aggregate")
    assert screen._stat_title_labels[0].text == "Average"


def test_the_end_of_a_session_locked_since_its_first_minute_shows_its_whole_numbers():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._live_screen = _finished_screen()  # its readout as of the first minute
    app._session_manager = MagicMock()
    app._session_manager.live_score.return_value = replace(SCORE, average=81.5)  # the timer ran out while locked
    app._mirror = LiveMirror()
    app._mirror.last_metrics = METRICS
    for name in ("_undo_session_setup", "_mark_history_dirty", "_settings_screen"):
        setattr(app, name, MagicMock())
    app._finalize_stop_ui({"duration": 1800}, None)
    app._live_screen.set_stats_mode("aggregate")
    assert "82" in _texts(app._live_screen)


def test_a_start_that_never_connected_leaves_no_owner():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    for name in ("_ticker", "_release_wake_lock", "_stop_session_keep_alive_service"):
        setattr(app, name, MagicMock())
    app._real_stream = MagicMock()
    app._live_display_uid = 1
    app._abort_bt_wait()
    assert app._live_display_uid is None


def test_deleting_the_shown_session_in_history_drops_it_from_the_session_screen(monkeypatch):
    monkeypatch.setattr(am.threading, "Thread", lambda target, **k: MagicMock(start=target))
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._history_screen = MagicMock()
    app._session_manager = MagicMock(state=am.SessionState.IDLE)
    app._live_screen = MagicMock(summary_session_id=None)  # its card was closed with OK; its graphs still show
    app._recorder = make_recorder(app)
    app._recorder.session_id = 9
    app._on_main = lambda fn: fn()
    app._drop_shown_session = MagicMock()
    for name in ("_refresh_history", "show_loading", "hide_loading", "_session_pipeline_live"):
        setattr(app, name, MagicMock(return_value=False))
    app._delete_sessions([7, 9])
    app._drop_shown_session.assert_called_once_with(keep_notes=False)


def test_idle_looks_the_same_however_it_is_reached():
    fresh = LiveSessionScreen()
    cancelled = LiveSessionScreen()
    cancelled.update_state("Running")
    cancelled.update_state("IDLE")  # a start cancelled before any tick
    assert tuple(cancelled._state_label.color) == tuple(fresh._state_label.color)
