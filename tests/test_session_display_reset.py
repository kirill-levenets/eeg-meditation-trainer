"""A profile pick, a session start or an idle threshold change leaves the Session screen showing no earlier session."""
from unittest.mock import MagicMock

import pytest

from app.session.manager import LiveScore
from app.ui.live_session import LiveSessionScreen
from tests._app import (
    FedSession,
    calls_of,
    frames,
    frames_until,
    reload_with,
    start_connecting,
    start_ticked_by_hand,
)

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


@pytest.fixture
def shown(fresh_app, monkeypatch):
    """The app showing a session that just ended, its end card open: `app.me` its profile, `app.sid` the session,
    `app.notes_writes` each notes text written, `app.bells` each stop of the end gong."""
    app = fresh_app
    start_ticked_by_hand(app, ticks=3)
    app._stop_and_save(reason="timer")
    frames()
    app.me, app.sid = app._current_user_id, app._live_screen.summary_session_id
    assert app.sid is not None and app._shown.owner == app.me
    app.notes_writes = []
    write = app._db.update_session_notes
    monkeypatch.setattr(app._db, "update_session_notes",
                        lambda sid, **fields: (app.notes_writes.append(fields.get("notes")), write(sid, **fields))[1])
    app.bells = calls_of(monkeypatch, app._audio, "stop_timer_bell")
    return app


def _card_open(app) -> bool:
    return app._live_screen.summary_session_id is not None


def _display(app) -> dict:
    """What the Session screen and its mirror hold of a session."""
    mirror, screen = app._shown.mirror, app._live_screen
    return {"mirror": (list(mirror.metrics), list(mirror.bands), list(mirror.waveform), mirror.last_metrics, mirror.marks),
            "points": screen.graph.total_points, "timer": screen._timer_label.text, "stats": _texts(screen)}


def _fresh_display(app) -> dict:
    """What they hold on a screen that has shown no session, in the profile's stats view."""
    fresh = LiveSessionScreen()
    fresh.set_stats_mode(app._live_screen._stats_mode)
    return {"mirror": ([], [], [], {}, []), "points": 0, "timer": "00:00", "stats": _texts(fresh)}


def test_clear_live_display_empties_the_graphs_their_mirrors_and_the_readout(shown):
    assert shown._live_screen.graph.total_points == 3 and _display(shown) != _fresh_display(shown)
    shown._shown.clear()
    assert _display(shown) == _fresh_display(shown)


def _other_profile(app) -> int:
    other = app._db.create_user("other")
    app._db.set_user_setting(other, "use_mock", "True")
    app._profiles.refresh()
    return other


def _drops(app, monkeypatch) -> list:
    """Each drop of the shown session from here on, as (keep_notes, the active profile then)."""
    seen, drop = [], app._shown.drop
    monkeypatch.setattr(app._shown, "drop",
                        lambda keep_notes: (seen.append((keep_notes, app._current_user_id)), drop(keep_notes))[1])
    return seen


def test_picking_another_profile_drops_the_shown_session_before_the_switch(shown, monkeypatch):
    other = _other_profile(shown)
    shown._live_screen._summary_notes.text = "typed on the card"
    seen = _drops(shown, monkeypatch)
    shown._profiles.on_switch(other)
    assert seen == [(True, shown.me)] and shown._current_user_id == other
    assert shown.notes_writes == ["typed on the card"] and not _card_open(shown)
    assert _display(shown) == _fresh_display(shown)


def test_re_picking_the_shown_profile_keeps_its_session_even_mid_session(fresh_app, monkeypatch):
    app = fresh_app
    start_ticked_by_hand(app, ticks=3)
    app._db.set_user_setting(app._current_user_id, "line_width", "2.5")
    seen = _drops(app, monkeypatch)
    app._activate_user(app._current_user_id)
    assert seen == [] and len(app._shown.mirror.metrics) == 3 and app._live_screen.graph.total_points == 3
    assert app._settings_store.value("line_width") == 2.5  # its settings were loaded again


def test_a_cold_start_shows_nothing_to_drop(fresh_app, monkeypatch):
    app = fresh_app
    assert app._shown.owner is None
    seen = _drops(app, monkeypatch)
    app._activate_user(app._current_user_id)
    assert seen == []


def test_dropping_the_shown_session_closes_its_open_card_saving_the_notes(shown):
    shown._live_screen._summary_notes.text = "typed on the card"
    shown._shown.drop(keep_notes=True)
    assert shown.notes_writes == ["typed on the card"] and len(shown.bells) == 1
    assert not _card_open(shown) and shown._shown.owner is None
    assert _display(shown) == _fresh_display(shown)


def test_dropping_with_no_card_open_leaves_a_ringing_bell_alone(shown):
    shown._shown.on_ok()  # the card closed; the session's graphs still show
    shown.bells.clear()
    shown._shown.drop(keep_notes=True)
    assert shown.bells == [] and shown.notes_writes == []
    assert _display(shown) == _fresh_display(shown) and shown._shown.owner is None


def test_a_deleted_sessions_card_closes_unsaved_but_its_bell_stops(shown):
    shown._live_screen._summary_notes.text = "typed on the card"
    shown._shown.drop(keep_notes=False)
    assert shown.notes_writes == [] and len(shown.bells) == 1 and not _card_open(shown)


def test_an_idle_threshold_clear_keeps_the_owner_of_an_open_card(shown):
    shown._settings_screen.threshold = shown._settings_screen.threshold - 5  # an idle slider move clears the display
    assert shown._live_screen.graph.total_points == 0 and _card_open(shown)
    assert shown._shown.owner == shown.me  # a later switch to another profile still closes the card


def test_deleting_the_shown_profile_drops_its_session_without_saving_notes(shown, monkeypatch):
    shown._live_screen._summary_notes.text = "typed on the card"
    seen = _drops(shown, monkeypatch)
    shown._profiles.on_delete(shown.me)
    assert [keep for keep, _user in seen] == [False] and shown.notes_writes == [] and not _card_open(shown)


def test_deleting_another_profile_leaves_the_shown_session(shown, monkeypatch):
    other = _other_profile(shown)
    seen = _drops(shown, monkeypatch)
    shown._profiles.on_delete(other)
    assert seen == [] and _card_open(shown) and shown._shown.owner == shown.me


def test_the_live_title_is_the_scored_series_name_on_the_graph_kept_until_the_readout_clears():
    screen = _finished_screen()
    screen.graph.set_series_name("custom_formula", "Alpha calm")
    screen.set_training_series("custom_formula")
    assert screen._stat_title_labels[0].text == "Alpha calm"
    screen.set_training_series(None)  # the session ended: the legend's mark goes, its numbers stay with their name
    assert screen._stat_title_labels[0].text == "Alpha calm"
    screen.clear_readout()
    assert screen._stat_title_labels[0].text == "Score"


def _scored_session(app, monkeypatch) -> FedSession:
    reload_with(app, threshold="50")
    return FedSession(app, monkeypatch)


def test_the_end_of_a_session_shows_its_numbers_before_its_scoring_is_reset(fresh_app, monkeypatch):
    app = fresh_app
    fed = _scored_session(app, monkeypatch)
    for value in (60, 70, 40):
        fed.tick(metrics={"shamatha_score": value})
    app._stop_and_save()
    frames()
    app._live_screen.set_stats_mode("aggregate")
    assert _texts(app._live_screen) == ["57", "1s", "1s"]


def test_a_profiles_stats_view_redraws_the_strip_not_just_the_button():
    screen = LiveSessionScreen()
    screen.set_stats_mode("aggregate")
    assert screen._stat_title_labels[0].text == "Average"


def test_the_end_of_a_session_locked_since_its_first_minute_shows_its_whole_numbers(fresh_app, monkeypatch):
    app = fresh_app
    fed = _scored_session(app, monkeypatch)
    app._live_screen.set_stats_mode("aggregate")
    fed.tick(metrics={"shamatha_score": 60})  # its readout as of the lock
    assert _texts(app._live_screen)[0] == "60"
    app.on_pause()
    for _ in range(3):
        fed.tick(metrics={"shamatha_score": 80})
    app._stop_and_save(reason="timer")  # the timer ran out while locked
    frames()
    assert _texts(app._live_screen)[0] == "75"


def test_a_start_that_never_connected_leaves_no_owner(fresh_app, monkeypatch):
    app = fresh_app
    start_connecting(app, monkeypatch)
    assert app._shown.owner == app._current_user_id
    app._on_connect_cancel()
    assert app._shown.owner is None


def test_deleting_the_shown_session_in_history_drops_it_from_the_session_screen(shown):
    shown._shown.on_ok()  # its card was closed with OK; its graphs still show
    assert shown._live_screen.graph.total_points == 3
    shown._history.delete_sessions([shown.sid])
    frames_until(lambda: shown._shown.owner is None)  # the delete's worker, then its main-thread half
    assert shown._db.get_session(shown.sid) is None and _display(shown) == _fresh_display(shown)


def test_idle_looks_the_same_however_it_is_reached():
    fresh = LiveSessionScreen()
    cancelled = LiveSessionScreen()
    cancelled.update_state("Running")
    cancelled.update_state("IDLE")  # a start cancelled before any tick
    assert tuple(cancelled._state_label.color) == tuple(fresh._state_label.color)
