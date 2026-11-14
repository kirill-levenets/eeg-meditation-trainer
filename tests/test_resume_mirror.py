"""Tests for the UI mirror buffers and post-resume graph reload.

The Android screen-lock fix splits live-graph updates into two paths:

- The tick thread mirrors every sample into session-lifetime deques
  (``LiveMirror``: ``metrics`` / ``bands`` / ``waveform``)
  regardless of pause state — no Kivy graphics ops, so it is safe while
  the screen is locked.
- ``_refresh_ui_after_resume`` reloads all three graphs from those
  mirrors in a single ``load_static_data`` batch per graph, instead of
  replaying N per-tick Clock callbacks (which flooded the main loop and
  caused a post-resume black screen / ANR).

These tests run the built app's own session: the ticks are the test's, on the headset sample and the engine result
it gives (``tests/_app.FedSession``), and the lock and unlock are the app's ``on_pause`` and ``on_resume``.
"""
import pytest

from app.eeg.neurosky_stream import NeuroSkyStream
from app.metrics.engine import MetricsEngine
from app.session.live_mirror import LiveMirror
from app.session.manager import SessionState, elapsed_clock
from app.session.recorder import RecordedTick
from app.session.session_run import Phase
from app.ui.live_session import METRICS_COLORS, LiveSessionScreen
from tests._app import (
    FedSession,
    calls_of,
    frames,
    raw_sample,
    reload_with,
    start_connecting,
    tick_metrics,
)

BAND_KEYS = ("alpha", "beta", "gamma", "theta", "delta")


@pytest.fixture
def fed(fresh_app, monkeypatch) -> FedSession:
    return FedSession(fresh_app, monkeypatch)


def _mirror(fed: FedSession):
    return fed.app._shown.mirror


def _points(graph) -> int:
    return max((len(v) for v in graph._data.values()), default=0)


# --- mirror-buffer fill (tick thread) -------------------------------------


def test_tick_appends_to_all_mirror_buffers(fed):
    fed.tick(raw_sample(), tick_metrics())
    mirror = _mirror(fed)
    assert (len(mirror.metrics), len(mirror.bands)) == (1, 1)
    assert len(mirror.waveform) == 3  # waveform of length 3
    assert mirror.last_metrics == tick_metrics()
    assert mirror.last_state == "Shamatha"


def test_tick_band_record_aggregates_paired_bands(fed):
    raw = raw_sample(seed=10.0)
    fed.tick(raw)
    band = _mirror(fed).bands[-1]
    assert band["alpha"] == raw["alpha1"] + raw["alpha2"]
    assert band["beta"] == raw["beta1"] + raw["beta2"]
    assert band["gamma"] == raw["gamma1"] + raw["gamma2"]
    assert band["theta"] == raw["theta"]
    assert band["delta"] == raw["delta"]
    assert set(band) == set(BAND_KEYS)


def test_tick_writes_three_distinct_custom_formula_series(fed):
    """The live tick evaluates each valid slot into its own metric key, with
    distinct values, and skips invalid slots."""
    session = fed.app._session  # its own lines, edited the way Settings edits them mid-session
    session.set_formula(0, "Sum", "alpha + beta")          # 120
    session.set_formula(1, "Ratio", "alpha / (beta + 1)")  # 100/21
    # slot 2 left invalid → must not be written
    metrics = tick_metrics()
    fed.tick({**raw_sample(), "alpha1": 60.0, "alpha2": 40.0, "beta1": 15.0, "beta2": 5.0}, metrics)
    assert metrics["custom_formula"] == pytest.approx(120.0)
    assert metrics["custom_formula_2"] == pytest.approx(100.0 / 21.0)
    assert "custom_formula_3" not in metrics  # invalid slot not written


def test_tick_writes_no_formula_series_when_no_slot_is_valid(fed):
    metrics = tick_metrics()
    fed.tick(metrics=metrics)
    assert not any(k.startswith("custom_formula") for k in metrics)


def test_tick_waveform_fallback_appends_band_sum(fed):
    fed.tick(raw_sample(seed=2.0, with_waveform=False))
    # No raw waveform → one synthetic point equal to the band-record sum.
    mirror = _mirror(fed)
    assert len(mirror.waveform) == 1
    assert mirror.waveform[-1] == sum(mirror.bands[-1].values())


def test_tick_stores_metrics_copy_not_reference(fed):
    metrics = tick_metrics()
    fed.tick(metrics=metrics)
    metrics["shamatha_score"] = 999  # mutate the original after the tick
    assert _mirror(fed).metrics[-1]["shamatha_score"] != 999


def test_mirror_fills_while_paused_but_skips_ui_dispatch(fed):
    graph = fed.app._live_screen.graph
    fed.app.on_pause()  # the screen locks
    fed.tick()
    # The whole point of the fix: data still accrues while the screen is
    # locked, but no per-tick UI work is queued onto the (paused) Clock.
    mirror = _mirror(fed)
    assert (len(mirror.metrics), len(mirror.bands), len(mirror.waveform)) == (1, 1, 3)
    assert _points(graph) == 0


def test_unpaused_tick_dispatches_ui_once(fed):
    fed.tick()
    assert len(_mirror(fed).metrics) == 1
    assert _points(fed.app._live_screen.graph) == 1


# --- resume reload (main thread) ------------------------------------------


def _locked_for(fed: FedSession, ticks: int) -> None:
    """The screen locks, then `ticks` ticks run, each on its own data."""
    fed.app.on_pause()
    for i in range(ticks):
        fed.tick(raw_sample(seed=float(i)), tick_metrics(seed=float(i)))


def _reloads(fed: FedSession, monkeypatch) -> dict[str, list]:
    """Each live graph's batch loads from here on, by graph."""
    screen = fed.app._live_screen
    return {name: calls_of(monkeypatch, graph, "load_static_data")
            for name, graph in (("metrics", screen.graph), ("bands", screen.band_graph), ("raw", screen.raw_graph))}


def _unlock(fed: FedSession) -> None:
    fed.app.on_resume()
    frames()


def test_resume_batch_reloads_each_graph_once(fed, monkeypatch):
    _locked_for(fed, 5)
    loads = _reloads(fed, monkeypatch)
    added = calls_of(monkeypatch, fed.app._live_screen.graph, "add_point")
    _unlock(fed)
    # One batched load per graph — never the per-tick add_point path.
    assert [len(calls) for calls in loads.values()] == [1, 1, 1] and added == []


def test_resume_reload_series_shapes_match_buffers(fed, monkeypatch):
    _locked_for(fed, 5)
    loads = _reloads(fed, monkeypatch)
    _unlock(fed)
    metric_series = loads["metrics"][0][0]
    assert set(metric_series) == set(METRICS_COLORS)
    assert all(len(v) == 5 for v in metric_series.values())
    band_series = loads["bands"][0][0]
    assert set(band_series) == set(BAND_KEYS)
    assert all(len(v) == 5 for v in band_series.values())
    raw_series = loads["raw"][0][0]
    assert set(raw_series) == {"eeg"}
    assert len(raw_series["eeg"]) == 5 * 3  # 5 ticks x 3 samples each


def test_an_ending_reloads_the_full_graph_and_sets_the_duration(fed):
    # Regression: after a session that ended during lock, the live graph held
    # only the pre-lock portion (per-tick add_point skipped while locked) and
    # the header froze at the lock-time elapsed. Finishing must reload the full
    # session from the mirror buffers and set the header to the real duration.
    app, screen = fed.app, fed.app._live_screen
    fed.tick()  # one tick shown before the lock
    _locked_for(fed, 9)
    assert _points(screen.graph) == 1
    app._stop_and_save(reason="timer")
    frames()
    duration = app._db.get_all_sessions(app._current_user_id)[0]["duration"]
    assert _points(screen.graph) == 10  # full session, not partial
    assert screen._timer_label.text.endswith(elapsed_clock(duration))  # real duration, not frozen
    assert screen.summary_session_id is not None


def test_resume_refreshes_stats_state_and_timer(fed, monkeypatch):
    app, screen = fed.app, fed.app._live_screen
    _locked_for(fed, 3)
    stats = calls_of(monkeypatch, screen, "update_stats")
    states = calls_of(monkeypatch, screen, "update_state")
    timers = calls_of(monkeypatch, screen, "update_timer")
    _unlock(fed)
    assert stats == [(app._session.manager.live_score(),)]  # the score kept while locked
    assert states == [("Shamatha",)]
    assert timers == [(app._session.manager.elapsed_formatted,)]


def test_a_reload_keeps_each_points_colouring():
    """A screen lock's reload redraws the line as it was scored, segment by segment (#113)."""
    mirror = LiveMirror()
    for key in ["shamatha_score"] * 3 + ["custom_formula"] * 2:
        mirror.record(RecordedTick(tick_metrics(seed=1.0), raw_sample(seed=1.0),
                                   {"score_target": 50, "score_key": key}, False))
    screen = LiveSessionScreen()
    screen.load_mirror(mirror.snapshot())
    assert screen.graph.gradient_steps == [(0, "shamatha_score"), (3, "custom_formula")]


def test_resume_skips_entirely_when_not_running(fed, monkeypatch):
    app, screen = fed.app, fed.app._live_screen
    _locked_for(fed, 5)
    app._stop_and_save(reason="timer")  # the timer expired during the pause: its summary card covers the live screen
    frames()
    loads = _reloads(fed, monkeypatch)
    stats = calls_of(monkeypatch, screen, "update_stats")
    timers = calls_of(monkeypatch, screen, "update_timer")
    _unlock(fed)
    # Combining graph reloads with _stop_and_save here was the ANR cause.
    assert [len(calls) for calls in loads.values()] == [0, 0, 0] and stats == [] and timers == []


def test_resume_with_empty_buffers_is_safe(fed, monkeypatch):
    app, screen = fed.app, fed.app._live_screen
    app.on_pause()  # RUNNING but no ticks recorded yet
    loads = _reloads(fed, monkeypatch)
    stats = calls_of(monkeypatch, screen, "update_stats")
    timers = calls_of(monkeypatch, screen, "update_timer")
    _unlock(fed)
    assert [len(calls) for calls in loads.values()] == [0, 0, 0] and stats == []
    assert len(timers) == 1  # always refreshed when RUNNING


def test_tick_then_resume_roundtrip_preserves_data(fed):
    """End-to-end: what the ticks mirror is exactly what resume reloads."""
    screen = fed.app._live_screen
    _locked_for(fed, 4)
    _unlock(fed)
    assert list(screen.graph._data["shamatha_score"]) == [0.0, 1.0, 2.0, 3.0]
    assert len(screen.raw_graph._data["eeg"]) == 4 * 3


# --- timer arm-on-connect race (BT-wait success path) ---------------------


@pytest.fixture
def connected(fresh_app, monkeypatch):
    """The app in a Start's BT wait on a headset that has just connected and sent data; its steps are the test's."""
    app = fresh_app
    reload_with(app, timer_enabled="True", timer_minutes="15")
    start_connecting(app, monkeypatch)
    monkeypatch.setattr(NeuroSkyStream, "is_connected", property(lambda self: True))
    monkeypatch.setattr(NeuroSkyStream, "seconds_since_last_packet", property(lambda self: 1.0))
    monkeypatch.setattr(app._real_stream, "read_sample", lambda: dict.fromkeys(
        ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2"), 10.0))
    return app


def test_btwait_arms_countdown_synchronously_on_connect(connected):
    # Regression for the instant-finish bug: start_countdown() must run on the
    # tick thread before the next tick() can read remaining_seconds. If it's
    # deferred to the main thread, remaining stays 0 and the
    # next tick fires the timer immediately → a 0s "timer-ended" session.
    app = connected
    app._session._follow_bt_wait(app._session.run)  # the wait's tick that sees the data
    assert app._session.run.phase is Phase.STARTED
    assert app._session.timer.remaining_seconds == 15 * 60
    assert app._session.manager.state == SessionState.RUNNING


def test_btwait_does_not_start_audio_on_tick_thread(connected, monkeypatch):
    # Regression for "noise plays while the loader is still up": audio start is
    # deferred to the main-thread callback (atomic with hide_overlay), never run
    # synchronously on the tick thread.
    app = connected
    sounds: list = []
    calls_of(monkeypatch, app._audio, "start", sounds, "start")
    calls_of(monkeypatch, app._audio, "play_connect_sound", sounds, "connect sound")
    app._session._follow_bt_wait(app._session.run)
    assert sounds == [] and app._live_screen._overlay.opacity == 1
    frames()  # the main thread's turn
    assert sounds == ["start", "connect sound"] and app._live_screen._overlay.opacity == 0


# --- timer-expiry persistence runs on the tick thread ---------------------


def _sessions(app) -> list[dict]:
    return app._db.get_all_sessions(app._current_user_id)


def test_timer_expiry_persists_on_tick_thread(fed, monkeypatch):
    # The whole point of the lock-survival fix: the DB write happens
    # synchronously on the daemon tick thread, NOT inside the main-thread
    # callback (which is buffered on the paused Clock during a screen lock).
    app = fed.app
    _locked_for(fed, 1)  # screen-locked: per-tick UI is skipped
    audio: list = []
    for name in ("mute", "play_timer_sound", "stop"):
        calls_of(monkeypatch, app._audio, name, audio, name)
    run = app._session.run
    fed.end_by_timer_on_next_tick()
    fed.tick(shown=False)
    # Persisted synchronously, before the main thread ran anything.
    (saved,) = _sessions(app)
    assert len(app._db.get_session_metrics(saved["id"])) == 2  # the row and the buffered ticks, in one transaction
    assert app._session.manager.state not in (SessionState.RUNNING, SessionState.PAUSED)
    # Noise is silenced with the non-blocking mute() on the tick thread, the gong rings here too (on the tick thread →
    # through the lock), but the blocking _audio.stop()/MediaPlayer.release() teardown is NOT run on the tick thread
    # (it deadlocks against the paused main Looper during lock): it's deferred to the main thread.
    assert audio == ["mute", "play_timer_sound"]
    assert app._session.run is run and run.phase is Phase.ENDED  # its UI teardown still waits for the main thread
    frames()
    assert "stop" in audio and app._session.run is None


def test_timer_expiry_leaves_no_live_pipeline_behind(fed):
    """A timer-ended session must not look live while idle: Restore and profile switch key off it."""
    app = fed.app
    fed.tick()
    fed.end_by_timer_on_next_tick()
    fed.tick(shown=False)
    assert app._session.live() is False


def test_timer_expiry_silences_saves_then_rings_and_leaves_the_teardown_to_the_main_thread(fed, monkeypatch):
    # mute() is setVolume: non-blocking, so the noise stops before a save that may wait on the write lock. The players'
    # teardown (stop) would hang while the main Looper is paused, so the writer never calls it; the gong rings last.
    app = fed.app
    _locked_for(fed, 1)
    calls: list = []
    calls_of(monkeypatch, app._db, "checkpoint_session", calls, "save")
    for name, label in (("mute", "mute"), ("play_timer_sound", "gong"), ("stop", "stop")):
        calls_of(monkeypatch, app._audio, name, calls, label)
    fed.end_by_timer_on_next_tick()
    fed.tick(shown=False)
    assert calls == ["mute", "save", "gong"], calls


def test_timer_expiry_updates_existing_session_row(fed):
    app = fed.app
    fed.tick()
    app._session.checkpoint_or_report()  # row already created by a prior flush
    sid = app._session.recorder.session_id
    assert sid is not None
    fed.end_by_timer_on_next_tick()
    fed.tick()
    (row,) = _sessions(app)
    assert row["id"] == sid and len(app._db.get_session_metrics(sid)) == 2  # the earlier flush's row, with the final data
    assert row["score_metric_key"] == "shamatha_score" and row["score_metric_name"] == "Shamatha"  # #51
    assert (row["custom_formulas"], row["session_program"], row["engine_version"]) == (
        "[]", "", MetricsEngine.ENGINE_VERSION)
