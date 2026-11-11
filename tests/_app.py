"""The app made by its real constructor and build(), as main.py makes it, on a temp DB: what conftest's `build_app`
fixture hands the app-level tests. A flow on its own is built by its constructor with tests/_context.stub_context."""
import time

import pytest
from kivy.app import App
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup

import app.ui.app_manager as am
from app.config import APP
from app.eeg.neurosky_stream import NeuroSkyStream
from app.storage.database import DatabaseManager
from app.ui.line_colours import LINE_COLOURS
from app.ui.theme import C, F


def frames(n: int = 10) -> None:
    for _ in range(n):
        EventLoop.idle()


def frames_until(done, seconds: float = 3.0) -> None:
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        EventLoop.idle()


def tap(parent, label: str) -> None:
    next(w for w in parent.walk() if getattr(w, "text", None) == label).dispatch("on_release")


def popups() -> list[Popup]:
    """The popups now open, the newest first."""
    return [w for w in Window.children if isinstance(w, Popup)]


def popup_titles() -> list[str]:
    return [p.title for p in popups()]


def popup_message(popup: Popup) -> str:
    """A message popup's text."""
    return next(w.text for w in popup.content.walk() if isinstance(w, Label) and not isinstance(w, ButtonBehavior))


def last_used(name: str = "me", **settings):
    """A seed: one profile, the one the app starts on, on the mock headset; `settings` are its stored settings."""
    def seed(db):
        uid = db.create_user(name)
        db.set_setting("last_user_id", str(uid))
        for key, value in {"use_mock": "True", **settings}.items():
            db.set_user_setting(uid, key, value)
    return seed


def setting_writes(app, monkeypatch) -> list[tuple[str, str]]:
    """Every per-user setting the app writes from now on, as (key, value) in order; the writes still reach the DB."""
    writes: list = []
    one, many = app._db.set_user_setting, app._db.set_user_settings

    def set_one(uid, key, value):
        writes.append((key, value))
        return one(uid, key, value)

    def set_many(uid, values):
        writes.extend(values.items())
        return many(uid, values)

    monkeypatch.setattr(app._db, "set_user_setting", set_one)
    monkeypatch.setattr(app._db, "set_user_settings", set_many)
    return writes


def start_ticked_by_hand(app, ticks: int = 0) -> None:
    """A mock session whose ticks the test runs: Start without its tick thread, then `ticks` of them."""
    app._ticker.start = lambda: None  # over the method, for this Start only
    try:
        app._on_start()
    finally:
        del app._ticker.start
    for _ in range(ticks):
        app._update_tick(APP.UPDATE_FREQUENCY)
    frames()  # what the ticks queued for the main thread


def reload_with(app, json_settings: dict | None = None, **settings: str) -> None:
    """The active profile with these stored settings, loaded as a profile's pick loads them."""
    uid = app._current_user_id
    for key, value in settings.items():
        app._db.set_user_setting(uid, key, value)
    for key, value in (json_settings or {}).items():
        app._db.set_user_json_setting(uid, key, value)
    app._activate_user(uid)
    frames()


def saved_session(app, ticks: int = 4, name: str = "a sit", **stats) -> int:
    """A finished session of the active profile, as a session's last checkpoint stores it; History is told, as an
    ending tells it."""
    rows = [{"timestamp": t * 0.5, "shamatha_score": 60.0} for t in range(ticks)]
    sid = app._db.checkpoint_session(None, {"duration": ticks // 2, "threshold_used": 70, **stats}, rows,
                                     user_id=app._current_user_id, session_name=name)
    app._history.mark_dirty()
    return sid


def open_history(app, sid: int) -> None:
    """The History screen, its list loaded with session `sid` in it."""
    app._switch_screen("history")
    frames_until(lambda: app._history_screen.session_by_id(sid) is not None)


def open_detail(app, sid: int) -> None:
    """History, then session `sid`'s detail, everything its worker loads in place."""
    open_history(app, sid)
    app._detail.on_session_select(sid)
    detail = app._diary_screen
    frames_until(lambda: detail._selected_session_id == sid
                 and detail._ready >= {"metrics", "raw", "freq", "bands", "what_if"})


def raw_sample(seed: float = 1.0, with_waveform: bool = True) -> dict:
    """A NeuroSky-shaped raw sample with distinct band values per seed."""
    sample = {"delta": seed, "theta": seed + 1, "alpha1": seed + 2, "alpha2": seed + 3, "beta1": seed + 4,
              "beta2": seed + 5, "gamma1": seed + 6, "gamma2": seed + 7, "battery": -1}
    if with_waveform:
        sample["raw_eeg_waveform"] = [seed, seed + 0.5, seed + 1.0]
    return sample


def tick_metrics(seed: float = 1.0) -> dict:
    """What the engine computes for a tick, distinct per seed."""
    return {"shamatha_score": seed, "distraction": seed + 1, "sinking": seed + 2, "subtle_distraction": seed + 3,
            "native_attention": seed + 4, "native_meditation": seed + 5, "state": "Shamatha"}


class FedSession:
    """A mock session whose ticks the test runs on the data it gives: `tick(raw, metrics)` runs one tick with the
    headset's sample `raw` and the engine's result for it `metrics` (the last given when left out; the tick works on
    that very dict). `thresholds` is the base threshold each tick gave the engine."""

    def __init__(self, app, monkeypatch, *, start: bool = True) -> None:
        self.app, self.raw, self.metrics, self.thresholds = app, raw_sample(), tick_metrics(), []
        monkeypatch.setattr(app._session.mock_stream, "read_sample", lambda: self.raw)
        monkeypatch.setattr(app._session.engine, "process_sample", self._computed)
        if start:
            start_ticked_by_hand(app)

    def _computed(self, _raw: dict, threshold: float) -> dict:
        self.thresholds.append(threshold)
        return self.metrics

    def tick(self, raw: dict | None = None, metrics: dict | None = None, *, shown: bool = True) -> None:
        """One tick; with `shown`, what it queued for the main thread has run when it returns."""
        self.raw = self.raw if raw is None else raw
        self.metrics = self.metrics if metrics is None else metrics
        self.app._update_tick(APP.UPDATE_FREQUENCY)
        if shown:
            frames()

    def end_by_timer_on_next_tick(self) -> None:
        self.app._session.timer.set_enabled(True)
        self.app._session.timer.remaining_seconds = APP.UPDATE_FREQUENCY / 2


class HeadsetSession:
    """A session on a real headset whose Bluetooth link is the test's (`connected`, `since_packet`: seconds since
    its last packet) and whose ticks the test runs, on the engine result it gives (`metrics`). Start, the BT wait
    and the wait's first data are the app's own; without `start` the run is left in its wait."""

    def __init__(self, app, monkeypatch, *, start: bool = True) -> None:
        self.app, self.connected, self.since_packet = app, False, 0.0
        self.raw = dict.fromkeys(("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2"), 10.0)
        self.metrics = tick_metrics()
        monkeypatch.setattr(NeuroSkyStream, "is_connected", property(lambda _stream: self.connected))
        monkeypatch.setattr(NeuroSkyStream, "seconds_since_last_packet", property(lambda _stream: self.since_packet))
        monkeypatch.setattr(app._real_stream, "read_sample", lambda: self.raw)
        monkeypatch.setattr(app._session.engine, "process_sample", lambda _raw, _threshold: self.metrics)
        start_connecting(app, monkeypatch)
        app._ticker.stop()  # the ticks are the test's
        if start:
            self.connected, self.since_packet = True, 0.2
            app._follow_bt_wait(app._run)  # the wait's tick that sees the first data
            frames()

    def tick(self, *, shown: bool = True) -> None:
        """One tick; with `shown`, what it queued for the main thread has run when it returns."""
        self.app._update_tick(APP.UPDATE_FREQUENCY)
        if shown:
            frames()


def calls_of(monkeypatch, obj, name: str, log: list | None = None, label: str | None = None) -> list:
    """The real `obj.name`, recorded: each call appends `label` (or its positional arguments) to the returned list."""
    log = [] if log is None else log
    real = getattr(obj, name)

    def recorded(*args, **kwargs):
        log.append(args if label is None else label)
        return real(*args, **kwargs)

    monkeypatch.setattr(obj, name, recorded)
    return log


def program_mode(app, segments: list[dict]) -> None:
    """Settings › Timer on Program with `segments` in its editor, as the editor's own handlers leave it."""
    app._program_settings.segments = [dict(s) for s in segments]
    app._program_settings.on_mode_change("program")


HEADSET = ("00:11:22:33:44:55", "MindWave Mobile")


def start_connecting(app, monkeypatch) -> None:
    """Press Start on a headset that never answers, so the run stays in its BT wait; the reader's start is the
    Bluetooth boundary."""
    def reader_started() -> bool:
        app._real_stream._running = True
        return True

    monkeypatch.setattr(app._real_stream, "start", reader_started)
    app._change_setting("use_mock", False)
    app._real_stream.set_device(*HEADSET)
    app._on_start()


def _environment(monkeypatch, db_path) -> list:
    """What every built app runs in: a temp DB, the mock headset (so no profile load scans), English help, and no
    process-wide crash hooks. Returns the list the app's crash-handler install is recorded in."""
    monkeypatch.setattr(APP, "DB_PATH", str(db_path))
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    monkeypatch.setenv("LANGUAGE", "en")
    monkeypatch.setattr(NeuroSkyStream, "scan_paired_devices", staticmethod(lambda: []))
    installed: list = []
    monkeypatch.setattr(am, "install_crash_handler", installed.append)
    return installed


def _build(seed, installed: list):
    seeding = DatabaseManager(db_path=APP.DB_PATH)
    seed(seeding)
    seeding.close()
    app = am.EEGMeditationApp()
    app.build()
    assert installed[-1] is app
    return app


def _close_modals() -> None:
    for modal in [w for w in Window.children if isinstance(w, ModalView)]:  # the gate's too
        modal.dismiss(animation=False)


def _retire(app) -> None:
    app._ticker.stop()  # a session a test left running: no tick thread, mock reader or sound for the next
    app._session.mock_stream.stop()
    app._audio.cleanup()
    frames()  # what the app queued runs while it is whole
    _close_modals()
    Window.unbind(on_key_down=app._on_key_down, on_keyboard=app._on_keyboard)
    app._db.close()


def built_apps(tmp_path, monkeypatch):
    """Yields build(seed): the app built on a DB that `seed(db)` prepared; what each app left process-wide is undone
    after the test."""
    installed = _environment(monkeypatch, tmp_path / "meditation.db")
    theme, scale, colours, rotation = C.theme_name, F.SCALE, LINE_COLOURS.name, Window.rotation
    running = App.get_running_app()  # Kivy's one running app is the last one constructed: the shared app's again after
    apps = []

    def build(seed=last_used()):
        apps.append(_build(seed, installed))
        return apps[-1]

    try:
        yield build
    finally:
        while apps:
            _retire(apps.pop())
        App._running_app = running
        C.set_theme(theme)
        F.set_scale(scale)
        LINE_COLOURS.set(colours)
        Window.rotation = rotation


class SharedApp:
    """One built app for the whole test run. Each test takes it on a new default profile, after the app's own paths
    have ended what the last test left: a session discarded, popups closed, the last profile deleted. A test that
    seeds its own database, needs the gate, or restores or stops the app builds its own (`build_app`). The app owns
    the process-wide device mode (APP.USE_MOCK_DEVICE) while it lives: a test beside it that needs a mode sets it."""

    def __init__(self, app) -> None:
        self.app = app
        self._profiles = 0

    def rest(self) -> None:
        """After a test: nothing of it keeps running or showing, for whichever test comes next (it may build its own
        app, in the same window)."""
        app = self.app
        assert not getattr(app, "_restoring", False), "a test that restores the database needs build_app"
        if app._is_paused:
            app.on_resume()
        if app._session_pipeline_live():
            app._discard_running_session()
        if app._run is not None:  # a Start that never became a session: still scanning, or asked to pick a headset
            app._cancel_session_start("IDLE")
        app._ticker.stop()
        frames()  # what the test queued lands before its popups are closed
        _close_modals()
        app._fullscreen.close()
        for trigger in app._settle_triggers.values():  # a slider the test moved: nothing of it lands in the next one
            trigger.cancel()
        app._last_back_time = 0.0  # as build() leaves it: this test's back press is not the next one's first

    def fresh(self):
        app = self.app
        App._running_app = app  # whatever app a test before this one constructed
        self._profiles += 1
        uid = app._db.create_user(f"me{self._profiles}")
        app._db.set_user_setting(uid, "use_mock", "True")
        if app._gate.active():  # the last test deleted its profile: out through the gate's own pick
            app._gate.pick_existing(uid)
        else:
            app._activate_user(uid)  # every setting at its default, the shown session dropped
        for user in app._db.get_all_users():
            if user["id"] != uid:
                app._profiles.on_delete(user["id"])
        app._profiles.refresh()
        app._switch_screen("live_session")
        frames()
        _close_modals()
        assert app._current_user_id == uid and app._run is None and not app._gate.active(), "the shared app is not idle"
        return app


def shared_apps(db_dir):
    """Yields the run's SharedApp, built once on its own temp DB. One for the run, and never one per test: a built app
    that is dropped leaves some 30,000 objects behind for good (Kivy 2.3.0's Python 3.12 wheel keeps a traceback per
    exception its widgets' teardown catches), and every collection after that walks them."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        installed = _environment(monkeypatch, db_dir / "meditation.db")
        theme, scale, colours, rotation = C.theme_name, F.SCALE, LINE_COLOURS.name, Window.rotation
        shared = SharedApp(_build(last_used("me0"), installed))
        try:
            yield shared
        finally:
            _retire(shared.__dict__.pop("app"))
            App._running_app = None
            C.set_theme(theme)
            F.set_scale(scale)
            LINE_COLOURS.set(colours)
            Window.rotation = rotation
