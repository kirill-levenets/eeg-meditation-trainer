"""The session's audio: the feedback loops whose volume follows the score, the alerts, the timer gong and Settings'
Test. The players are in `players.py`, the sounds in `sounds.py`."""
import math
import os
import threading
import time

from app.audio_feedback import players
from app.audio_feedback.one_shot import OneShot
from app.audio_feedback.players import AudioFocus, RepeatedError
from app.audio_feedback.sounds import KeptSounds
from app.config import APP
from app.logger import logger


class AudioEngine:
    """4-channel audio engine for meditation neurofeedback.

    Channel 1 (Noise): Looping brown/white noise WAV, volume scaled by
        meditation score via smooth ramping.
    Channel 2 (Bell): Synthesized tingsha bell, one-shot on sinking alert
        with cooldown.
    Channel 3 (Chime): Synthesized chime, one-shot on subtle distraction
        alert with cooldown.
    Channel 4 (Disconnect): Warble alert on Bluetooth disconnection.

    Uses only stdlib + Kivy. No external audio libraries.
    """

    # Volume interpolation: ramp toward target in small steps
    _RAMP_INTERVAL: float = 0.025  # 25ms between steps (40 updates/sec)
    _RAMP_SPEED: float = 0.6  # max volume change per second

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._target_volume: float = 0.0
        self._max_volume: float = APP.MAX_VOLUME
        self._is_playing: bool = False
        self._feedback_players: dict[str, object] = {}  # source_id -> looping player
        self._active_feedback: str = ""                 # below-threshold (noise) player id
        self._reward_feedback: str = ""                 # above-threshold reward player id ("" = none)
        self._reward_target_volume: float = 0.0
        self._alert_until: dict[str, float] = {"sinking": 0.0, "subtle": 0.0}  # each alert's next allowed time
        self._sinking_alert_enabled: bool = False
        self._subtle_alert_enabled: bool = False
        self._disconnect_alert_enabled: bool = APP.DISCONNECT_ALERT_ENABLED
        self._test: _AudioTest | None = None  # Settings' Test run that has the engine, if one has
        self._lock = threading.Lock()
        self._ramp_thread: threading.Thread | None = None
        self._ramp_running: bool = False
        self._focus = AudioFocus()  # one request for the app, held while the session's feedback plays
        # Each one-shot's one player, replayed: the alerts, and the timer-end gong.
        self._bell = OneShot("bell", self._focus)
        self._chime = OneShot("chime", self._focus)
        self._disconnect = OneShot("disconnect", self._focus)
        self._gong = OneShot("gong", self._focus)
        self._sounds = KeptSounds(APP.WHITE_NOISE_SAMPLE_RATE)
        self._sounds.prepare()

    def prepare_feedback(self, sources: dict[str, tuple[str, str]], active_id: str) -> None:
        """Instantiate one looping player per distinct feedback source at volume 0 (main thread)."""
        self._teardown_feedback_players()
        made: dict[str, object] = {}
        for sid, (kind, path) in sources.items():
            if kind == "none":
                continue  # silent channel: no player instantiated
            resolved = self._sounds.feedback_path(kind, path)
            try:
                p = players.make_player(resolved)
                p.volume = 0.0
                made[sid] = p
            except Exception as e:
                logger.warning(f"Feedback source {sid!r} failed to load ({resolved!r}): {e}")
        self._feedback_players = made
        self._active_feedback = self._resolve_active(active_id, list(made))

    @staticmethod
    def _resolve_active(active_id: str, player_ids: list[str]) -> str:
        """Resolve the below/active player id. An empty active_id means 'no below
        channel' (None) and must NOT fall back to another player (e.g. the reward
        one); a non-empty-but-missing id falls back defensively to the first player."""
        if active_id in ("", "none"):
            return ""
        if active_id in player_ids:
            return active_id
        return player_ids[0] if player_ids else ""

    def set_active_feedback(self, source_id: str) -> None:
        """Make source_id the modulated player and zero the old; setVolume-only so it's tick/lock-safe."""
        if source_id == self._active_feedback:
            return
        player = self._feedback_players.get(source_id)
        if player is None:
            logger.warning(f"set_active_feedback: unknown source {source_id!r}")
            return
        old = self._feedback_players.get(self._active_feedback)
        if old is not None:
            try:
                old.volume = 0.0
            except Exception:
                logger.exception("set_active_feedback: zeroing old player failed")
        self._active_feedback = source_id

    def set_reward(self, source_id: str) -> None:
        """Designate the above-threshold reward player ("" = none). setVolume-only path;
        the ramp loop drives it toward _reward_target_volume and zeros non-role players."""
        if source_id and source_id in self._feedback_players:
            self._reward_feedback = source_id
        else:
            self._reward_feedback = ""
            self._reward_target_volume = 0.0

    def _teardown_feedback_players(self) -> None:
        """Stop + unload every feedback player; main thread only (release())."""
        for sid, p in list(self._feedback_players.items()):
            try:
                p.stop()
                p.unload()
            except Exception:
                logger.exception(f"Failed to stop/unload feedback player {sid!r}")
        self._feedback_players = {}
        self._active_feedback = ""
        self._reward_feedback = ""
        self._reward_target_volume = 0.0

    def _start_noise_loop(self) -> None:
        """Play the prepared feedback players looping (active at current volume, rest
        silent). Plays ONLY what prepare_feedback set up — an empty set means every
        channel is Off and must stay silent (no forced rain)."""
        if self._feedback_players:
            self._focus.hold("session")
        for sid, player in self._feedback_players.items():
            try:
                player.volume = self._volume if sid == self._active_feedback else 0.0
                player.play()
            except Exception as e:
                logger.warning(f"Failed to start feedback player {sid!r}: {e}")

    def _set_noise_volume(self, volume: float) -> None:
        """Set target volume — the ramp thread interpolates smoothly toward it."""
        self._target_volume = volume
        self._volume = volume
        self._ensure_ramp_thread()

    def _ensure_ramp_thread(self) -> None:
        """Start the volume ramp thread if not already running."""
        if self._ramp_running:
            return
        self._ramp_running = True
        self._ramp_thread = threading.Thread(target=self._ramp_loop, daemon=True)
        self._ramp_thread.start()

    def _ramp_loop(self) -> None:
        """Background loop: smoothly interpolate every feedback player toward its role
        target — the below/active player toward _target_volume, the reward player toward
        _reward_target_volume, all others toward 0. Volume-only, so tick/lock-safe."""
        max_step = self._RAMP_SPEED * self._RAMP_INTERVAL
        skipped: dict[str, RepeatedError] = {}  # per source: a step every 25 ms logs each error once
        while self._ramp_running and self._is_playing:
            for sid, player in list(self._feedback_players.items()):
                if sid == self._active_feedback:
                    target = self._target_volume
                elif sid == self._reward_feedback:
                    target = self._reward_target_volume
                else:
                    target = 0.0
                try:
                    current = player.volume
                    diff = target - current
                    if abs(diff) < 0.001:
                        player.volume = target
                    else:
                        player.volume = current + max(-max_step, min(max_step, diff))
                except Exception as e:
                    if skipped.setdefault(sid, RepeatedError()).is_new(e):
                        logger.debug(f"Volume ramp step skipped: {e}")
                else:
                    if sid in skipped:
                        skipped[sid].clear()
            time.sleep(self._RAMP_INTERVAL)
        self._ramp_running = False

    def compute_volume(self, meditation_score: float, threshold: float) -> float:
        """Noise volume for a score against the threshold it is scored on (the tick's target).

        Uses log scaling so volume rises quickly at first but the rate of
        increase slows as score approaches zero (concave curve).
        Curve: log(1 + t*k) / log(1 + k), k=9.
        """
        threshold = max(1, threshold)
        if meditation_score >= threshold:
            return 0.0
        return self._log_rise((threshold - meditation_score) / threshold)

    def compute_reward_volume(self, meditation_score: float, threshold: float) -> float:
        """Above-threshold reward volume: silent at/below threshold, log-rising to
        max over [threshold, threshold + REWARD_SPAN]. Mirror of compute_volume so
        the two zones cross-fade cleanly (both 0 exactly at the threshold)."""
        threshold = max(1, threshold)
        if meditation_score <= threshold:
            return 0.0
        span = max(1, APP.REWARD_SPAN)
        return self._log_rise(min(1.0, (meditation_score - threshold) / span))

    def _log_rise(self, t: float) -> float:
        """Volume for t in 0..1, log-curved (log(1 + 9t) / log 10): quick at first, slower toward max."""
        k = 9.0
        scaled = math.log(1.0 + t * k) / math.log(1.0 + k)
        return min(scaled * self._max_volume, self._max_volume)

    def update(self, meditation_score: float, threshold: float) -> None:
        """Drive both feedback zones from one score against the threshold it is scored on: the below/noise channel
        falls as you approach it, the reward channel (if armed) rises above it. The ramp thread interpolates each
        player toward its target."""
        below_vol = self.compute_volume(meditation_score, threshold)
        self._reward_target_volume = (
            self.compute_reward_volume(meditation_score, threshold) if self._reward_feedback else 0.0
        )
        if not self._is_playing or self.testing:
            self._volume = below_vol
            return
        self._set_noise_volume(below_vol)

    def update_sinking(self, sinking_score: float) -> None:
        """Check sinking score and trigger bell alert if needed."""
        if self._alert_due("sinking", self._sinking_alert_enabled, sinking_score,
                           APP.SINKING_ALERT_THRESHOLD, APP.SINKING_ALERT_COOLDOWN):
            self._play_bell()
            logger.info(f"Sinking alert triggered (score={sinking_score:.0f})")

    def update_subtle_distraction(self, subtle_score: float) -> None:
        """Check subtle distraction score and play gentle chime if needed."""
        if self._alert_due("subtle", self._subtle_alert_enabled, subtle_score,
                           APP.SUBTLE_ALERT_THRESHOLD, APP.SUBTLE_ALERT_COOLDOWN):
            self._play_chime()
            logger.info(f"Subtle distraction chime (score={subtle_score:.0f})")

    def _alert_due(self, kind: str, enabled: bool, score: float, threshold: float, cooldown: float) -> bool:
        """An alert sounds while feedback plays, above its threshold, at most once per cooldown."""
        if not enabled or not self._is_playing:
            return False
        now = time.time()
        if score > threshold and now >= self._alert_until[kind]:
            self._alert_until[kind] = now + cooldown
            return True
        return False

    def _play_bell(self) -> None:
        """Play the sinking bell WAV."""
        self._bell.play(self._sounds.path("bell"), 0.8)

    def _play_chime(self) -> None:
        """Play the gentle chime WAV for subtle distraction."""
        self._chime.play(self._sounds.path("chime"), 0.6)

    def _play_disconnect(self) -> None:
        """Play the harsh disconnect alert WAV."""
        self._disconnect.play(self._sounds.path("disconnect"), 0.9)

    def start(self) -> None:
        """Start noise playback."""
        if self._is_playing:
            return
        initial = self._volume if self._volume > 0.001 else self._max_volume * 0.5
        self._volume = initial
        self._target_volume = initial
        self._play_prepared()
        logger.info("Audio engine started")

    def _stop_ramp(self) -> None:
        """Stop the volume ramp thread and wait for it briefly."""
        self._ramp_running = False
        if self._ramp_thread:
            self._ramp_thread.join(timeout=0.5)
            self._ramp_thread = None

    def pause(self) -> None:
        """Silence and pause every feedback player but keep the prepared set and its roles for resume(); main thread."""
        self._is_playing = False  # gates the alert channels and update()
        self._stop_ramp()
        for sid, player in self._feedback_players.items():
            try:
                player.volume = 0.0
                player.stop()
            except Exception:
                logger.exception(f"pause: feedback player {sid!r} failed")
        self._focus.release("session")  # nothing plays while paused: resume asks again
        logger.info("Audio engine paused")

    def resume(self) -> None:
        """Replay the players pause() kept; the ramp brings each role back to its last target volume."""
        if self._is_playing:
            return
        self._play_prepared()
        logger.info("Audio engine resumed")

    def _play_prepared(self) -> None:
        self._is_playing = True
        with self._lock:
            self._start_noise_loop()
        self._ensure_ramp_thread()

    def mute(self) -> None:
        """Silence all feedback players immediately via setVolume only (tick/lock-safe; no teardown)."""
        self._ramp_running = False
        self._volume = 0.0
        self._target_volume = 0.0
        # setVolume-only: stop()/release() deadlock the session's runner vs the paused main Looper under lock
        for sid, p in self._feedback_players.items():
            try:
                p.volume = 0.0
            except Exception:
                logger.exception(f"mute: zeroing feedback player {sid!r} failed")

    def stop(self) -> None:
        """Stop all audio playback."""
        self._stop_ramp()
        self._teardown_feedback_players()
        self._focus.release("session")  # a gong still ringing keeps it until its end
        self._chime.release()  # not the gong or the failure warble: both start just before stop()
        self._is_playing = False
        self._volume = 0.0
        self._target_volume = 0.0
        self._test = None  # a run still on its thread sees it lost the engine and stops

    def test_audio(self, reward_id: str = "") -> None:
        """Settings' Test of every channel on its own thread (_AudioTest): the reward sample if one is armed, a volume
        sweep of the below channel, then the three alerts; a test restarted supersedes the one running."""
        self.end_test()
        run = _AudioTest(self, reward_id)  # the engine as the test finds it, to hand back at its end
        if not self._is_playing:
            self._is_playing = True
            run.owns_playing = True
        self._test = run
        # The Test button demos the rain sweep; prepare a player if a session
        # hasn't (a real session prepares from the user's config, respecting Off).
        if not self._feedback_players:
            self.prepare_feedback({"noise": ("noise", "")}, "noise")
        self._set_noise_volume(0.0)
        with self._lock:
            self._start_noise_loop()
        logger.info("Audio test: started")
        threading.Thread(target=run.run, daemon=True).start()

    @property
    def testing(self) -> bool:
        """A Settings Test run is playing: the ticks' volumes wait (update)."""
        run = self._test
        return run is not None and run.active

    def end_test(self) -> None:
        """Stop a running Settings test where it is and call off its teardown: a session takes the engine over."""
        run, self._test = self._test, None
        if run is not None and run.owns_playing:
            self._is_playing = False
            self._stop_ramp()
            self._focus.release("session")  # the test's hold: a start called off before it plays holds nothing

    def _finish_test(self, run: "_AudioTest") -> None:
        """The test's teardown, on the main thread, unless a session or a new test took the engine over meanwhile."""
        if run is self._test:
            self.stop()

    def play_timer_sound(self, custom_path: str = "", on_end=None) -> str:
        """The timer-end gong, replayed like an alert, safe on the session's runner; returns the file it plays, "" if none."""
        logger.info("Timer gong")
        custom = custom_path if (custom_path and os.path.isfile(custom_path)) else ""
        duck = "AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK"  # other audio dips while it rings, and comes back after
        if custom and self._gong.play(custom, 1.0, on_end, duck):
            return custom
        # A custom file the player can't open rings the default gong, as a missing one does.
        if self._gong.play(self._sounds.path("timer_bell"), 1.0, on_end, duck):
            return self._sounds.path("timer_bell")
        if on_end is not None:
            players.next_frame(on_end)  # nothing plays: the play is over
        return ""

    def stop_timer_bell(self) -> None:
        """Stop and release the gong, or call off one still being built; main thread."""
        if self._gong.player is not None:
            logger.info("Timer gong released")
        self._gong.release()

    def play_connect_sound(self) -> None:
        """Play a chime to confirm device connected."""
        self._play_chime()
        logger.info("Connect sound played")

    def play_transition_cue(self) -> None:
        """Play the chime as a program segment-transition cue."""
        self._play_chime()
        logger.info("Program transition cue played")

    def play_disconnect_alert(self) -> None:
        """Play a harsh warble when device disconnects."""
        if not self._disconnect_alert_enabled:
            return
        self._play_disconnect()
        logger.info("Disconnect alert played")

    def play_alert(self) -> None:
        """Play the disconnect warble channel briefly as a termination alert."""
        try:
            self._play_disconnect()
        except Exception:
            logger.exception("Disconnect alert failed to play")

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def sinking_alert_enabled(self) -> bool:
        return self._sinking_alert_enabled

    @sinking_alert_enabled.setter
    def sinking_alert_enabled(self, value: bool) -> None:
        self._sinking_alert_enabled = value

    @property
    def subtle_alert_enabled(self) -> bool:
        return self._subtle_alert_enabled

    @subtle_alert_enabled.setter
    def subtle_alert_enabled(self, value: bool) -> None:
        self._subtle_alert_enabled = value

    @property
    def disconnect_alert_enabled(self) -> bool:
        return self._disconnect_alert_enabled

    @disconnect_alert_enabled.setter
    def disconnect_alert_enabled(self, value: bool) -> None:
        self._disconnect_alert_enabled = value

    def cleanup(self) -> None:
        """Stop playback and unload the players; the sound files stay for the next launch."""
        self.stop()
        self.stop_timer_bell()
        self._disconnect.release()
        self._bell.release()


class _AudioTest:
    """One run of Settings' Test: the reward sample, the sweep, the alerts, then its teardown. A newer test, or a
    session's start (end_test), stops it where it is."""

    _SWEEP_STEP = 0.05  # 20 volume steps a second

    def __init__(self, engine: AudioEngine, reward_id: str) -> None:
        self._engine = engine
        self._reward_id = reward_id
        self._was_playing = engine._is_playing
        self._saved_volume = engine._volume
        self.active = True  # until its steps are over
        self.owns_playing = False  # it started the engine's playback, so its end hands that back

    def live(self) -> bool:
        """It still has the engine: no newer run or session took it over, and its steps aren't over."""
        return self.active and self._engine._test is self

    def run(self) -> None:
        for step in (self._reward_sample, self._sweep, self._alerts):
            if not step():
                return
        self._finish()

    def _reward_sample(self) -> bool:
        """The armed reward source first: its loop just started, so the cricket chirp (~0.2 s in) comes in the sample."""
        engine, reward_id = self._engine, self._reward_id
        if not (self.live() and reward_id and reward_id in engine._feedback_players):
            return True
        logger.info(f"Audio test: reward sample ({reward_id})")
        engine._reward_feedback = reward_id
        engine._reward_target_volume = engine._max_volume
        player = engine._feedback_players[reward_id]
        try:
            player.volume = engine._max_volume
        except Exception:
            logger.exception("Audio test: reward player volume set failed")
        time.sleep(APP.AUDIO_TEST_DURATION + 1.0)  # long enough to catch one cricket chirp
        if not self.live():
            return False  # a session has the reward channel now
        engine._reward_target_volume = 0.0
        try:
            player.volume = 0.0
        except Exception as e:
            logger.debug(f"Reward volume not reset after its test: {e}")
        engine._reward_feedback = ""
        return True

    def _sweep(self) -> bool:
        """The below channel from silence to max over half the test's length, and back over the other half."""
        n_steps = int(APP.AUDIO_TEST_DURATION / self._SWEEP_STEP)
        half = n_steps // 2
        for i in range(n_steps):
            if not self.live():
                return False
            if i <= half:
                volume = self._engine._max_volume * (i / half)
            else:
                volume = self._engine._max_volume * (1.0 - (i - half) / (n_steps - half))
            self._engine._set_noise_volume(volume)
            time.sleep(self._SWEEP_STEP)
        if not self.live():  # taken over during the last step: the volume is the session's now
            return False
        self._engine._set_noise_volume(0.0)
        return True

    def _alerts(self) -> bool:
        engine = self._engine
        for name, play, length in (("sinking bell", engine._play_bell, APP.BELL_DURATION),
                                   ("subtle distraction chime", engine._play_chime, APP.CHIME_DURATION),
                                   ("disconnect alert", engine._play_disconnect, APP.DISCONNECT_DURATION)):
            if not self.live():
                return False
            logger.info(f"Audio test: {name}")
            play()
            time.sleep(length + 0.3)
        return self.live()

    def _finish(self) -> None:
        """The engine handed back: stopped on the main thread (it releases MediaPlayers) if the test started it."""
        engine = self._engine
        self.active = False
        if not self._was_playing:
            players.next_frame(lambda: engine._finish_test(self))
        else:
            engine._set_noise_volume(self._saved_volume)
        logger.info("Audio test complete")
