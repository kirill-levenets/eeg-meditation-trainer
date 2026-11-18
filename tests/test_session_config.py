"""A session runs on what its Start read (its SessionConfig): a Settings edit or a profile reload during the run applies
to the next session, and only an explicit call changes a running one (an edited formula line)."""
import json

import pytest

from app.eeg.neurosky_stream import NeuroSkyStream
from app.session.manager import SessionState
from tests._app import (
    FedSession,
    HeadsetSession,
    calls_of,
    frames,
    program_mode,
    reload_with,
    tick_metrics,
)

_WINDOW = [{"name": "W", "formula": "avg(alpha1, 4)"}]


def _no_setting_read(key):
    raise AssertionError(f"the running session read the setting {key!r}")


def test_a_session_tick_and_checkpoint_read_no_setting(fresh_app, monkeypatch):
    # A live read is how a profile's reload switched a program's timer off and how the scored metric could move.
    app = fresh_app
    reload_with(app, {"active_formulas": _WINDOW}, audio_metric="custom_formula")
    fed = FedSession(app, monkeypatch)
    monkeypatch.setattr(app._settings_store, "value", _no_setting_read)
    for _ in range(3):
        fed.tick(shown=False)  # the tick thread's part; what it queues for the screen is the screen's
    app._session.recorder.checkpoint()  # the row's score, name and formulas
    assert app._db.get_session(app._session.recorder.session_id)["score_metric_key"] == "custom_formula"


def test_a_session_evaluates_its_own_formula_slots(fresh_app, monkeypatch):
    # The profile's slots are Settings' copy: a writer that changes them doesn't change the running session's lines.
    app = fresh_app
    reload_with(app, {"active_formulas": [{"name": "A", "formula": "alpha1"}]})
    fed = FedSession(app, monkeypatch)
    fed.raw = {**fed.raw, "alpha1": 30.0}
    app._formulas.evaluators[0].set_formula("alpha1 * 10")
    fed.tick()
    assert app._session.recorder._buffer[-1]["custom_formula"] == pytest.approx(30.0)


def test_a_formula_line_edited_mid_session_reaches_the_running_session(fresh_app, monkeypatch):
    # Slot 2 is not the one the sound is set to, so Settings lets it change during the session, and its line follows.
    app = fresh_app
    fed = FedSession(app, monkeypatch)
    fed.raw = {**fed.raw, "alpha1": 30.0}
    app._formula_settings.on_slot_change(1, "Double", "alpha1 * 2")
    fed.tick()
    assert app._session.recorder._buffer[-1]["custom_formula_2"] == pytest.approx(60.0)
    app._formula_settings.on_slot_change(1, "Double", "")  # cleared: the line stops
    fed.tick(metrics=tick_metrics())  # a fresh result: the fed one keeps the last tick's keys
    assert "custom_formula_2" not in app._session.recorder._buffer[-1]


def _saved_visibility(app) -> dict[str, bool]:
    """Each formula line's shown or hidden, as the running session's checkpoint saves it."""
    app._session.recorder.checkpoint()
    record = json.loads(app._db.get_session(app._session.recorder.session_id)["custom_formulas"])
    return {line["name"]: line["visible"] for line in record}


def test_a_session_saves_its_formula_lines_as_the_live_graph_shows_them(fresh_app, monkeypatch):
    # The shown lines are the session's: taken at the Start, whatever it held before, then changed only through
    # set_shown, whoever hides a line.
    app = fresh_app
    graph = app._live_screen.graph
    reload_with(app, {"active_formulas": [{"name": "A", "formula": "alpha1"}, {"name": "B", "formula": "beta1"}],
                      f"graph_series_{graph.graph_id}": ["shamatha_score", "custom_formula"]})
    app._session.shown = frozenset({"custom_formula_2"})  # held from before: a Start doesn't keep it
    fed = FedSession(app, monkeypatch)
    fed.tick()
    assert _saved_visibility(app) == {"A": True, "B": False}
    graph.set_visible("custom_formula", False)  # the series picker, mid-session
    graph.set_visible("custom_formula_2", True)
    fed.tick()
    assert _saved_visibility(app) == {"A": False, "B": True}


def test_a_program_session_saves_the_formula_lines_its_start_left_shown(fresh_app, monkeypatch):
    # A program's Start shows its own lines and hides the Settings formula lines after the session took its config:
    # what it saves is what the graph shows then.
    app = fresh_app
    graph = app._live_screen.graph
    reload_with(app, {"active_formulas": [{"name": "A", "formula": "alpha1"}],
                      f"graph_series_{graph.graph_id}": ["shamatha_score", "custom_formula"]})
    program_mode(app, [{"minutes": 1, "target": 120, "formula": {"name": "AlphaPwr", "formula": "alpha1"}}])
    fed = FedSession(app, monkeypatch)
    assert app._session.shown == set(graph.visible_keys()) and "program_formula" in app._session.shown  # before a tick
    fed.tick()
    assert _saved_visibility(app) == {"A": graph.is_visible("custom_formula")}


def test_a_timer_sound_chosen_mid_session_rings_from_the_next_session(fresh_app, monkeypatch, tmp_path):
    app = fresh_app
    first, later = tmp_path / "first.wav", tmp_path / "later.wav"
    first.write_bytes(b"RIFF")
    later.write_bytes(b"RIFF")
    reload_with(app, timer_enabled="True", timer_minutes="1", timer_sound=str(first))
    rung = calls_of(monkeypatch, app._audio, "play_timer_sound")
    for expected in (first, later):
        fed = FedSession(app, monkeypatch)
        app._sounds.on_timer_sound_change(str(later))  # during the session
        fed.end_by_timer_on_next_tick()
        fed.tick()
        frames()
        app._shown.close(keep_notes=False)
        assert rung[-1][0] == str(expected)


@pytest.mark.parametrize("timer, warned", [("True", True), ("False", False)])
def test_a_missing_gong_is_warned_about_at_start_only_when_the_session_will_ring_it(fresh_app, monkeypatch, tmp_path,
                                                                                    timer, warned):
    app = fresh_app
    reload_with(app, timer_enabled=timer, timer_minutes="5", timer_sound=str(tmp_path / "typo_gong.wav"))
    checked = calls_of(monkeypatch, app._sounds, "warn_missing")
    FedSession(app, monkeypatch)
    assert ("typo_gong.wav" in checked[-1][1]) is warned


def test_a_mock_session_ignores_the_headsets_link(fresh_app, monkeypatch):
    # The link outlives sessions: up, then silent for longer than the stale stop allows, during a mock session.
    app = fresh_app
    fed = FedSession(app, monkeypatch)
    monkeypatch.setattr(NeuroSkyStream, "is_connected", property(lambda _s: True))
    monkeypatch.setattr(NeuroSkyStream, "seconds_since_last_packet",
                        property(lambda _s: app._session.watch.STALE_DATA_THRESHOLD + 1))
    alerts = calls_of(monkeypatch, app._live_screen, "show_alert")
    for _ in range(3):
        fed.tick()
    assert app._session.manager.state == SessionState.RUNNING and alerts == []


@pytest.mark.parametrize("on_headset", [True, False], ids=["headset", "mock"])
def test_an_ending_stops_the_mock_stream_and_keeps_the_headsets_link(fresh_app, monkeypatch, on_headset):
    # A link closed at every ending made the next connect wait on the headset (EBUSY).
    app = fresh_app
    session = HeadsetSession(app, monkeypatch) if on_headset else FedSession(app, monkeypatch)
    real, mock = calls_of(monkeypatch, app._real_stream, "stop"), calls_of(monkeypatch, app._session.mock_stream, "stop")
    session.tick()
    app._stop_and_save()
    frames()
    assert (real, bool(mock)) == ([], not on_headset)


def test_a_timer_sound_path_is_used_without_surrounding_blanks(fresh_app, monkeypatch, tmp_path):
    # A path stored or typed with blanks around it named no file, so the default bell rang instead.
    app = fresh_app
    gong = tmp_path / "gong.wav"
    gong.write_bytes(b"RIFF")
    reload_with(app, timer_enabled="True", timer_minutes="5", timer_sound=f"  {gong} ")
    FedSession(app, monkeypatch)
    assert app._session.config.gong == str(gong)
    app._sounds.on_timer_sound_change(f" {gong}  ")
    assert app._settings_store.value("timer_sound") == str(gong)
