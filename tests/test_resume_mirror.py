"""Tests for the UI mirror buffers and post-resume graph reload.

The Android screen-lock fix splits live-graph updates into two paths:

- The tick thread mirrors every sample into session-lifetime deques
  (``_ui_metrics_history`` / ``_ui_band_history`` / ``_ui_raw_waveform``)
  regardless of pause state — no Kivy graphics ops, so it is safe while
  the screen is locked.
- ``_refresh_ui_after_resume`` reloads all three graphs from those
  mirrors in a single ``load_static_data`` batch per graph, instead of
  replaying N per-tick Clock callbacks (which flooded the main loop and
  caused a post-resume black screen / ANR).

These tests drive the real ``_update_tick`` and ``_refresh_ui_after_resume``
with stubbed subsystems so the mirror-fill and batch-reload logic — the
exact lines the ANR fix introduced — are exercised, not re-implemented.
"""

import time
from collections import deque
from unittest.mock import MagicMock

from app.config import APP
from app.session.manager import SessionState
from app.session.timer_state import TimerState
from app.ui.app_manager import EEGMeditationApp
from app.ui.live_session import METRICS_COLORS

BAND_KEYS = ("alpha", "beta", "gamma", "theta", "delta")


def _raw_sample(seed: float = 1.0, with_waveform: bool = True) -> dict:
    """A NeuroSky-shaped raw sample with distinct band values per seed."""
    sample = {
        "delta": seed,
        "theta": seed + 1,
        "alpha1": seed + 2,
        "alpha2": seed + 3,
        "beta1": seed + 4,
        "beta2": seed + 5,
        "gamma1": seed + 6,
        "gamma2": seed + 7,
        "battery": -1,
    }
    if with_waveform:
        sample["raw_eeg_waveform"] = [seed, seed + 0.5, seed + 1.0]
    return sample


def _metrics(seed: float = 1.0) -> dict:
    return {
        "shamatha_score": seed,
        "distraction": seed + 1,
        "sinking": seed + 2,
        "subtle_distraction": seed + 3,
        "native_attention": seed + 4,
        "native_meditation": seed + 5,
        "state": "Shamatha",
    }


def _make_tick_app(is_paused: bool = False) -> EEGMeditationApp:
    """An app stubbed enough to run the real ``_update_tick`` to completion."""
    app = EEGMeditationApp.__new__(EEGMeditationApp)

    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._session_manager.elapsed_seconds = 0
    app._session_manager.elapsed_formatted = "0:01"

    # Skip the real-BT notify/disconnect branches regardless of USE_MOCK_DEVICE.
    app._real_stream = MagicMock()
    app._real_stream.is_connected = True
    app._bt_connected_notified = True

    app._check_stale_data = MagicMock()
    app._eeg_stream = MagicMock()
    app._metrics_engine = MagicMock()
    app._noise_detector = None  # skip power-line feed branch
    app._custom_formula = MagicMock()
    app._custom_formula.is_valid = False  # MagicMock is truthy by default

    app._audio = MagicMock()
    app._audio_metric_key = "shamatha_score"

    app._timer_state = MagicMock()
    app._timer_state.tick.return_value = False  # never expire

    app._metrics_buffer = []
    app._raw_buffer = []
    app._flush_counter = 0  # 60s flush never triggers within these short tests
    app._pending_marker = False
    app._on_main = MagicMock()
    app._is_paused = is_paused
    app._live_screen = MagicMock()

    # Persistence deps (used by the timer-expiry path via _persist_session_data).
    app._db = MagicMock()
    app._db.save_session.return_value = 42
    app._current_session_id = None
    app._current_user_id = 1
    app._make_session_name = MagicMock(return_value="sess")
    app._tick_stop_event = MagicMock()

    app._ui_metrics_history = deque(maxlen=APP.GRAPH_POINTS_MAX)
    app._ui_band_history = deque(maxlen=APP.GRAPH_POINTS_MAX)
    app._ui_raw_waveform = deque(maxlen=512 * 60)
    app._ui_last_metrics = {}
    app._ui_last_state = "Neutral"
    return app


def _drive_tick(app: EEGMeditationApp, raw: dict, metrics: dict) -> None:
    app._eeg_stream.read_sample.return_value = raw
    app._metrics_engine.process_sample.return_value = metrics
    EEGMeditationApp._update_tick(app, APP.UPDATE_FREQUENCY)


# --- mirror-buffer fill (tick thread) -------------------------------------


def test_tick_appends_to_all_mirror_buffers():
    app = _make_tick_app()
    _drive_tick(app, _raw_sample(), _metrics())

    assert len(app._ui_metrics_history) == 1
    assert len(app._ui_band_history) == 1
    assert len(app._ui_raw_waveform) == 3  # waveform of length 3
    assert app._ui_last_metrics == _metrics()
    assert app._ui_last_state == "Shamatha"


def test_tick_band_record_aggregates_paired_bands():
    app = _make_tick_app()
    raw = _raw_sample(seed=10.0)
    _drive_tick(app, raw, _metrics())

    band = app._ui_band_history[-1]
    assert band["alpha"] == raw["alpha1"] + raw["alpha2"]
    assert band["beta"] == raw["beta1"] + raw["beta2"]
    assert band["gamma"] == raw["gamma1"] + raw["gamma2"]
    assert band["theta"] == raw["theta"]
    assert band["delta"] == raw["delta"]
    assert set(band) == set(BAND_KEYS)


def test_tick_waveform_fallback_appends_band_sum():
    app = _make_tick_app()
    raw = _raw_sample(seed=2.0, with_waveform=False)
    _drive_tick(app, raw, _metrics())

    # No raw waveform → one synthetic point equal to the band-record sum.
    band = app._ui_band_history[-1]
    assert len(app._ui_raw_waveform) == 1
    assert app._ui_raw_waveform[-1] == sum(band.values())


def test_tick_stores_metrics_copy_not_reference():
    app = _make_tick_app()
    metrics = _metrics()
    _drive_tick(app, _raw_sample(), metrics)

    metrics["shamatha_score"] = 999  # mutate the original after the tick
    assert app._ui_metrics_history[-1]["shamatha_score"] != 999


def test_mirror_fills_while_paused_but_skips_ui_dispatch():
    app = _make_tick_app(is_paused=True)
    _drive_tick(app, _raw_sample(), _metrics())

    # The whole point of the fix: data still accrues while the screen is
    # locked, but no per-tick UI work is queued onto the (paused) Clock.
    assert len(app._ui_metrics_history) == 1
    assert len(app._ui_band_history) == 1
    assert len(app._ui_raw_waveform) == 3
    app._on_main.assert_not_called()


def test_unpaused_tick_dispatches_ui_once():
    app = _make_tick_app(is_paused=False)
    _drive_tick(app, _raw_sample(), _metrics())

    assert len(app._ui_metrics_history) == 1
    app._on_main.assert_called_once()


# --- resume reload (main thread) ------------------------------------------


def _make_resume_app(running: bool = True) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._session_manager = MagicMock()
    app._session_manager.state = (
        SessionState.RUNNING if running else SessionState.FINISHED
    )
    app._session_manager.elapsed_formatted = "1:23"
    app._live_screen = MagicMock()
    app._ui_metrics_history = deque(maxlen=APP.GRAPH_POINTS_MAX)
    app._ui_band_history = deque(maxlen=APP.GRAPH_POINTS_MAX)
    app._ui_raw_waveform = deque(maxlen=512 * 60)
    app._ui_last_metrics = {}
    app._ui_last_state = "Neutral"
    return app


def _populate(app: EEGMeditationApp, n: int) -> None:
    for i in range(n):
        app._ui_metrics_history.append(_metrics(seed=float(i)))
        raw = _raw_sample(seed=float(i))
        app._ui_band_history.append(
            {
                "alpha": raw["alpha1"] + raw["alpha2"],
                "beta": raw["beta1"] + raw["beta2"],
                "gamma": raw["gamma1"] + raw["gamma2"],
                "theta": raw["theta"],
                "delta": raw["delta"],
            }
        )
        app._ui_raw_waveform.extend(raw["raw_eeg_waveform"])
    app._ui_last_metrics = _metrics(seed=float(n - 1))
    app._ui_last_state = "Shamatha"


def test_resume_batch_reloads_each_graph_once():
    app = _make_resume_app(running=True)
    _populate(app, n=5)

    EEGMeditationApp._refresh_ui_after_resume(app)

    ls = app._live_screen
    # One batched load per graph — never the per-tick add_point path.
    ls.graph.load_static_data.assert_called_once()
    ls.band_graph.load_static_data.assert_called_once()
    ls.raw_graph.load_static_data.assert_called_once()
    ls.graph.add_point.assert_not_called()


def test_resume_reload_series_shapes_match_buffers():
    app = _make_resume_app(running=True)
    _populate(app, n=5)

    EEGMeditationApp._refresh_ui_after_resume(app)
    ls = app._live_screen

    metric_series = ls.graph.load_static_data.call_args[0][0]
    assert set(metric_series) == set(METRICS_COLORS)
    assert all(len(v) == 5 for v in metric_series.values())

    band_series = ls.band_graph.load_static_data.call_args[0][0]
    assert set(band_series) == set(BAND_KEYS)
    assert all(len(v) == 5 for v in band_series.values())

    raw_series = ls.raw_graph.load_static_data.call_args[0][0]
    assert set(raw_series) == {"eeg"}
    assert len(raw_series["eeg"]) == 5 * 3  # 5 ticks x 3 samples each


def test_finalize_stop_ui_reloads_full_graph_and_sets_duration():
    # Regression: after a session that ended during lock, the live graph held
    # only the pre-lock portion (per-tick add_point skipped while locked) and
    # the header froze at the lock-time elapsed. Finishing must reload the full
    # session from the mirror buffers and set the header to the real duration.
    app = _make_resume_app(running=False)  # session already FINISHED
    _populate(app, n=10)
    app._timer_state = MagicMock()
    app._release_wake_lock = MagicMock()
    app._stop_session_keep_alive_service = MagicMock()
    app._mark_history_dirty = MagicMock()

    EEGMeditationApp._finalize_stop_ui(app, {"duration": 60}, 7)

    ls = app._live_screen
    series = ls.graph.load_static_data.call_args[0][0]
    assert all(len(v) == 10 for v in series.values())  # full session, not partial
    ls.update_timer.assert_called_once_with("01:00")    # real duration, not frozen
    ls.show_summary.assert_called_once_with(7, {"duration": 60})


def test_resume_refreshes_stats_state_and_timer():
    app = _make_resume_app(running=True)
    _populate(app, n=3)

    EEGMeditationApp._refresh_ui_after_resume(app)
    ls = app._live_screen

    ls.update_stats.assert_called_once_with(app._ui_last_metrics)
    ls.update_state.assert_called_once_with("Shamatha")
    ls.update_timer.assert_called_once_with("1:23")


def test_resume_skips_entirely_when_not_running():
    app = _make_resume_app(running=False)
    _populate(app, n=5)

    EEGMeditationApp._refresh_ui_after_resume(app)
    ls = app._live_screen

    # Timer expired during pause → summary card covers the live screen;
    # combining graph reloads with _stop_and_save here was the ANR cause.
    ls.graph.load_static_data.assert_not_called()
    ls.band_graph.load_static_data.assert_not_called()
    ls.raw_graph.load_static_data.assert_not_called()
    ls.update_stats.assert_not_called()
    ls.update_timer.assert_not_called()


def test_resume_with_empty_buffers_is_safe():
    app = _make_resume_app(running=True)  # RUNNING but no ticks recorded yet

    EEGMeditationApp._refresh_ui_after_resume(app)
    ls = app._live_screen

    ls.graph.load_static_data.assert_not_called()
    ls.band_graph.load_static_data.assert_not_called()
    ls.raw_graph.load_static_data.assert_not_called()
    ls.update_stats.assert_not_called()
    ls.update_timer.assert_called_once_with("1:23")  # always refreshed when RUNNING


def test_tick_then_resume_roundtrip_preserves_data():
    """End-to-end: what the ticks mirror is exactly what resume reloads."""
    app = _make_tick_app(is_paused=True)
    for i in range(4):
        _drive_tick(app, _raw_sample(seed=float(i)), _metrics(seed=float(i)))

    app._live_screen = MagicMock()
    EEGMeditationApp._refresh_ui_after_resume(app)

    metric_series = app._live_screen.graph.load_static_data.call_args[0][0]
    assert metric_series["shamatha_score"] == [0.0, 1.0, 2.0, 3.0]
    raw_series = app._live_screen.raw_graph.load_static_data.call_args[0][0]
    assert len(raw_series["eeg"]) == 4 * 3


# --- timer arm-on-connect race (BT-wait success path) ---------------------


def _make_btwait_app() -> EEGMeditationApp:
    """An app stubbed to run the real ``_handle_bt_wait`` success branch."""
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._real_stream = MagicMock()
    app._real_stream.is_connected = True
    app._real_stream._device_name = "MindWave"
    app._real_stream.seconds_since_last_packet = 1.0
    app._bt_signal_start = None
    app._bt_connect_start = time.time()
    app._pending_threshold = 50
    app._waiting_for_bt = True

    app._eeg_stream = MagicMock()
    app._eeg_stream.read_sample.return_value = {
        "delta": 10.0, "theta": 10.0, "alpha1": 10.0, "alpha2": 10.0,
        "beta1": 10.0, "beta2": 10.0, "gamma1": 10.0, "gamma2": 10.0,
    }
    app._session_manager = MagicMock()
    app._audio = MagicMock()
    app._on_main = MagicMock()  # deferred UI/audio is NOT executed here
    app._live_screen = MagicMock()
    app._settings_screen = MagicMock()

    ts = TimerState()
    ts.set_enabled(True)
    ts.set_duration(15)
    app._timer_state = ts
    return app


def test_btwait_arms_countdown_synchronously_on_connect():
    # Regression for the instant-finish bug: start_countdown() must run on the
    # tick thread before the next tick() can read remaining_seconds. If it's
    # deferred to _on_main (here a no-op MagicMock), remaining stays 0 and the
    # next tick fires the timer immediately → a 0s "timer-ended" session.
    app = _make_btwait_app()
    EEGMeditationApp._handle_bt_wait(app)

    assert app._waiting_for_bt is False
    assert app._timer_state.remaining_seconds == 15 * 60
    app._session_manager.start.assert_called_once_with(threshold=50)
    app._on_main.assert_called_once()  # UI/audio still deferred to main thread


def test_btwait_does_not_start_audio_on_tick_thread():
    # Regression for "noise plays while the loader is still up": audio start is
    # deferred to the main-thread callback (atomic with hide_overlay), never run
    # synchronously on the tick thread.
    app = _make_btwait_app()
    EEGMeditationApp._handle_bt_wait(app)

    app._audio.start.assert_not_called()
    app._audio.play_connect_sound.assert_not_called()


# --- timer-expiry persistence runs on the tick thread ---------------------


def test_timer_expiry_persists_on_tick_thread():
    # The whole point of the lock-survival fix: the DB write happens
    # synchronously on the daemon tick thread, NOT inside the _on_main
    # callback (which is buffered on the paused Clock during a screen lock).
    app = _make_tick_app(is_paused=True)  # screen-locked: per-tick UI is skipped
    app._timer_state.tick.return_value = True  # expire on this tick
    app._timer_state.custom_sound_path = ""
    app._session_manager.stop.return_value = {"duration": 100}
    app._metrics_buffer = [{"shamatha_score": 1.0}]

    _drive_tick(app, _raw_sample(), _metrics())

    # Persisted synchronously even though _on_main (MagicMock) never ran.
    app._session_manager.stop.assert_called_once_with(reason="timer")
    app._db.save_session.assert_called_once()
    app._db.save_metrics_batch.assert_called_once()
    # Noise is silenced with the non-blocking mute() on the tick thread...
    app._audio.mute.assert_called_once()
    # ...the gong rings here too (on the tick thread → through the lock)...
    app._audio.play_timer_sound.assert_called_once()
    # ...but the blocking _audio.stop()/MediaPlayer.release() teardown is NOT
    # run on the tick thread (it deadlocks against the paused main Looper
    # during lock); it's deferred to the main thread via _on_main.
    app._audio.stop.assert_not_called()
    # UI teardown + gong are still deferred to the main thread (one dispatch,
    # since the per-tick UI update is skipped while paused/locked).
    app._on_main.assert_called_once()


def test_timer_expiry_persists_before_muting_audio():
    # Order matters: the save must complete before any audio call, so a hang
    # in audio teardown can never cost the session. Assert save_session is
    # invoked and precedes mute() in call order.
    app = _make_tick_app(is_paused=True)
    app._timer_state.tick.return_value = True
    app._timer_state.custom_sound_path = ""
    app._session_manager.stop.return_value = {"duration": 100}
    app._metrics_buffer = [{"shamatha_score": 1.0}]

    calls = []
    app._session_manager.stop.side_effect = lambda **k: calls.append("stop") or {"duration": 100}
    app._db.save_session.side_effect = lambda *a, **k: calls.append("save") or 42
    app._audio.mute.side_effect = lambda: calls.append("mute")

    _drive_tick(app, _raw_sample(), _metrics())

    assert calls.index("save") < calls.index("mute"), calls


def test_timer_expiry_updates_existing_session_row():
    app = _make_tick_app()
    app._timer_state.tick.return_value = True
    app._timer_state.custom_sound_path = ""
    app._session_manager.stop.return_value = {"duration": 100}
    app._current_session_id = 7  # row already created by a prior flush

    _drive_tick(app, _raw_sample(), _metrics())

    app._db.update_session.assert_called_once_with(7, {"duration": 100})
    app._db.save_session.assert_not_called()
