import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime as _dt
from typing import Optional

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivy.utils import platform as kivy_platform

from app.android_jni import java_string
from app.audio_feedback.noise import AudioEngine
from app.config import APP
from app.crash_handler import (
    flush_pre_app_errors,
    install_crash_handler,
    report_soft_error,
)
from app.eeg.band_spec import BAND_KEYS
from app.eeg.mock_stream_v2 import MockEEGStream
from app.eeg.neurosky_stream import NeuroSkyStream
from app.logger import logger, timed
from app.metrics.engine import MetricsEngine
from app.metrics.formula_slots import (
    FORMULA_KEYS,
    FormulaSlots,
    recorded_formulas,
)
from app.metrics.noise_detector import PowerLineDetector
from app.session.manager import SessionManager, SessionState, elapsed_clock
from app.session.recorder import SessionRecorder
from app.session.session_program import (
    PROGRAM_FORMULA_KEYS,
    segment_target,
)
from app.session.tick_thread import TickThread
from app.session.timer_state import TimerState
from app.session.what_if import scored_ticks
from app.settings.registry import (
    BOOL,
    FLOAT,
    INT,
    STR,
    Setting,
    SettingsStore,
    stored_value,
)
from app.storage.csv_export import build_sessions_zip
from app.storage.database import DatabaseManager, UserExistsError
from app.ui import render_stats
from app.ui.backup_flow import BackupFlow
from app.ui.diary_screen import DiaryScreen, detail_graph_data
from app.ui.formula_settings import FormulaSettings
from app.ui.graph_fullscreen import GraphFullscreen
from app.ui.graph_series import GraphSeries
from app.ui.headset import Headset, filter_mindwave
from app.ui.history_screen import HistoryScreen
from app.ui.hooks import wire
from app.ui.line_colours import DEFAULT as LINE_DEFAULT
from app.ui.line_colours import LINE_COLOURS
from app.ui.line_colours import OPTIONS as LINE_OPTIONS
from app.ui.live_mirror import LiveMirror
from app.ui.live_session import LiveSessionScreen
from app.ui.program_run import ProgramRun
from app.ui.program_settings import ProgramSettings
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.session_labels import session_title, start_stamp
from app.ui.settings_screen import (
    SettingsScreen,
)
from app.ui.theme import (
    DEFAULT_THEME,
    TEXT_SIZES,
    THEMES,
    BottomNav,
    C,
    F,
    StyledButton,
    ThemedLabel,
    ThemedPopup,
    confirm_popup,
    fill_background,
    format_count,
    make_message_popup,
    paint_panel,
)
from app.ui.widgets.loading_overlay import LoadingOverlay
from app.ui.widgets.user_picker import UserPickerForm


def resolve_startup_user(db) -> Optional[int]:
    """The uid to restore at startup, or None if the user must be prompted.

    None covers no `last_user_id`, a corrupt value, and a stale id whose user was
    deleted — every case must open the blocking user-select gate rather than let
    the app run usable with no active user (issue #29 root cause)."""
    saved = db.get_setting("last_user_id")
    if not saved:
        return None
    try:
        uid = int(saved)
    except (ValueError, TypeError):
        logger.warning(f"Corrupt last_user_id setting {saved!r} — prompting for user")
        return None
    if uid <= 0:  # not a valid AUTOINCREMENT id — don't rely on get_user(0) missing
        return None
    return uid if db.get_user(uid) else None


def theme_seed(db) -> str:
    """The theme of a profile without its own: the global setting from before themes were per-user, else the
    default."""
    seed = db.get_setting("theme")
    return seed if seed in THEMES else DEFAULT_THEME


def _parse_theme(raw: str) -> str:
    if raw not in THEMES:
        raise ValueError(f"unknown theme {raw!r}")
    return raw


def theme_setting(seed: str) -> Setting:
    """The per-user theme. An unknown stored name loads the seed: set_theme ignores it, which kept the previous
    profile's palette."""
    return Setting("theme", seed, _parse_theme, STR[1], lambda: C.theme_name, C.set_theme)


def _parse_text_size(raw: str) -> float:
    size = float(raw)
    if size not in {scale for scale, _name in TEXT_SIZES}:
        raise ValueError(f"text size {raw!r} isn't on offer")
    return size


def text_size_setting() -> Setting:
    """The per-user text size: loading a profile applies its size to every screen at once."""
    return Setting("text_size", 1.0, _parse_text_size, FLOAT[1], lambda: F.SCALE, F.set_scale)


def _parse_line_colours(raw: str) -> str:
    if raw not in {name for name, _label in LINE_OPTIONS}:
        raise ValueError(f"line colours {raw!r} aren't on offer")
    return raw


def line_colours_setting() -> Setting:
    """The per-user scored line colours: loading a profile redraws every graph in its choice."""
    return Setting("line_colours", LINE_DEFAULT, _parse_line_colours, STR[1], lambda: LINE_COLOURS.name,
                   LINE_COLOURS.set)


def startup_value(db, setting: Setting):
    """The startup profile's value, to build the UI in: its settings load then re-applies it as a no-op."""
    return stored_value(db, resolve_startup_user(db), setting)


def startup_text_size(db) -> float:
    return startup_value(db, text_size_setting())


def startup_theme(db) -> str:
    """The startup profile's theme, else the seed."""
    return startup_value(db, theme_setting(theme_seed(db)))


def sessions_for_view(db, current_uid: Optional[int], show_all: bool) -> list:
    """Sessions to display: every user's when the deliberate All-Users view is
    on, the current user's when a concrete user is active, and NONE when unset —
    an unset user must never fall through to `get_all_sessions(None)` and leak
    every profile's sessions."""
    if show_all:
        return db.get_all_sessions(user_id=None)
    if current_uid:
        return db.get_all_sessions(user_id=current_uid)
    return []


class EEGMeditationApp(App):
    """Main Kivy application for EEG Meditation Trainer."""

    title = APP.APP_NAME
    _PERSIST_SETTLE_S: float = 0.5  # quiet time before a slider/text change is written
    icon = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "assets", "icons", "icon_128.png",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mock_stream: MockEEGStream = MockEEGStream()
        self._real_stream: NeuroSkyStream = NeuroSkyStream()
        self._eeg_stream = self._mock_stream
        self._metrics_engine: MetricsEngine = MetricsEngine()
        self._session_manager: SessionManager = SessionManager()
        self._db: DatabaseManager = DatabaseManager()
        self._audio: AudioEngine = AudioEngine()
        self._session_manager.set_audio(self._audio)
        self._ticker: TickThread = TickThread(lambda dt: self._update_tick(dt))
        self._waiting_for_bt: bool = False
        self._bt_signal_start: float | None = None
        # Android pause state: when True, tick thread skips per-tick UI
        # work (graph add_point, stats updates) so a long screen-lock
        # doesn't accumulate thousands of Clock callbacks that flood the
        # main loop on resume (which previously caused a black screen).
        self._is_paused: bool = False
        self._mirror: LiveMirror = LiveMirror()  # the live graphs' session, kept through a screen lock
        self._recorder: SessionRecorder = SessionRecorder(
            self._db, self._session_manager, with_score=lambda stats: self._with_score(stats),
            row_fields=lambda: self._session_row_fields())
        self._current_user_id: Optional[int] = None
        # True while _load_user_settings applies values, so its change callbacks don't re-persist them.
        self._loading_settings: bool = False
        self._settle_triggers: dict = {}  # input name -> its settle trigger (_after_settle)
        self._settle_fns: dict = {}  # input name -> the function its trigger runs (the latest one given)
        # True only for the deliberate "Show All Users" aggregate history view,
        # distinct from _current_user_id=None (unset). Keeps the unset state from
        # ever querying all profiles' sessions (cross-profile leak).
        self._view_all_users: bool = False
        self._formulas: FormulaSlots = FormulaSlots()
        self._audio_formula_index: int = 0  # the slot that drives the sound when the custom formula does
        self.serial_device_override: Optional[str] = None
        self._wake_lock = None

    def _persist_user_setting(self, key: str) -> None:
        """Persist one setting now via the registry (it reads the live value); no-op mid-load or unbuilt."""
        if self._loading_settings:
            return
        store = getattr(self, "_settings_store", None)
        if store is None:
            return
        try:
            store.persist(self._current_user_id, key)
        except sqlite3.Error as e:
            # The value stays applied in memory; the next batch save retries it.
            report_soft_error("settings_save_failed", f"Couldn't save setting {key!r}: {e}", app=self)

    def _persist_user_setting_later(self, key: str) -> None:
        """Persist a continuous input (slider drag, typing) once it settles, not on every step."""
        if self._loading_settings:
            return
        self._after_settle(key, lambda: self._persist_user_setting(key))

    def _after_settle(self, name: str, fn) -> None:
        """Run the latest `fn` given for input `name` once it has stopped changing for _PERSIST_SETTLE_S."""
        triggers = getattr(self, "_settle_triggers", None)
        if triggers is None:
            triggers = self._settle_triggers = {}
        fns = getattr(self, "_settle_fns", None)
        if fns is None:
            fns = self._settle_fns = {}
        fns[name] = fn
        ev = triggers.get(name)
        if ev is None:
            ev = triggers[name] = Clock.create_trigger(lambda _dt: fns[name](), self._PERSIST_SETTLE_S)
        ev.cancel()  # restart the settle window on every change
        ev()

    def _cancel_settle(self, name: str) -> None:
        ev = getattr(self, "_settle_triggers", {}).get(name)
        if ev is not None:
            ev.cancel()

    def _session_custom_formulas_json(self) -> str:
        return self._formulas.session_record(self._live_screen.graph.is_visible, self._audio_metric_key)

    @staticmethod
    def _source_spec(source_id: str) -> tuple[str, str]:
        """Map a feedback source id to (kind, custom_path); non-builtin ids are custom file paths.
        "" / "none" -> the silent sentinel (no player is instantiated for it)."""
        if source_id in ("", "none"):
            return ("none", "")
        if source_id in ("noise", "tone", "heartbeat"):
            return (source_id, "")
        return ("custom", source_id)

    def _reward_id(self) -> str:
        """The above-threshold reward source id ("" = none). A custom selection with
        no file resolves to silent (unlike the noise channel, which falls back to rain)."""
        src = getattr(self, "_reward_source", "none")
        if src in ("", "none"):
            return ""
        if src == "custom":
            return getattr(self, "_reward_sound_path", "") or ""
        return src

    @staticmethod
    def _feedback_source_id(value: str, global_id: str) -> str:
        """A segment's feedback_sound value as a source id; blank inherits the global source."""
        return value if value else global_id

    @staticmethod
    def _feedback_plan(prog, global_id: str) -> tuple[dict, list, str]:
        """(distinct sources, per-segment ids, initial id) for a program; blanks inherit the global."""
        seg_ids = [
            EEGMeditationApp._feedback_source_id(s.get("feedback_sound", "") or "", global_id)
            for s in prog.segments
        ]
        sources = {sid: EEGMeditationApp._source_spec(sid) for sid in [global_id, *seg_ids]}
        initial = seg_ids[0] if seg_ids else global_id
        return sources, seg_ids, initial

    def _global_feedback_id(self) -> str:
        """The active global feedback source id; a custom selection with no file falls back to noise."""
        src = getattr(self, "_feedback_source", "noise")
        if src in ("", "none"):
            return "none"
        if src == "custom":
            return getattr(self, "_feedback_sound_path", "") or "noise"
        return src

    def _warn_missing_sound_files(self, feedback_sources: dict, timer_path: str = "", *, force: bool = False) -> None:
        """Surface missing custom sound files in ONE report; `force` for user-initiated checks (Test buttons)."""
        problems = []
        missing = [path for kind, path in feedback_sources.values()
                   if kind == "custom" and not (path and os.path.isfile(path))]
        if missing:
            problems.append(f"{format_count(len(missing), 'custom feedback file')} not found: "
                            + ", ".join(repr(p) for p in missing) + " - using rain noise instead.")
        if timer_path and not os.path.isfile(timer_path):
            problems.append(f"Custom timer sound not found: {timer_path!r} - using the default gong instead.")
        if problems:
            report_soft_error("sound_files_missing", "\n".join(problems), app=self, force=force)

    @staticmethod
    def _shamatha_transition(
        active: bool, above: bool, streak: int, enter_ticks: int = 3, exit_ticks: int = 3
    ) -> tuple[bool, int]:
        """Pure debounced shamatha-zone crossing -> (new_active, new_streak).

        Hysteresis against 2Hz noise: a partial streak resets the moment the score
        crosses back, so the chip can't strobe on a single noisy sample.
        """
        if not active:
            streak = streak + 1 if above else 0
            return (True, 0) if streak >= enter_ticks else (False, streak)
        streak = streak + 1 if not above else 0
        return (False, 0) if streak >= exit_ticks else (True, streak)

    def _eval_formula_vars(self, raw_sample: dict, metrics: dict) -> dict:
        """Variable dict for custom-formula evaluation (raw + metrics + derived/sqrt bands)."""
        fvars = {**raw_sample, **metrics}
        fvars.update(self._metrics_engine.derive_bands(raw_sample))
        sqrt_bands = self._metrics_engine.compute_sqrt_relative_bands(raw_sample)
        fvars.update({f"s_{k}": v for k, v in sqrt_bands.items()})
        return fvars

    def _acquire_wake_lock(self) -> None:
        """Keep CPU running + screen on during session (Android only)."""
        if not hasattr(sys, "getandroidapilevel"):
            return
        try:
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _set_flag():
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                WindowManager = autoclass("android.view.WindowManager$LayoutParams")
                activity.getWindow().addFlags(WindowManager.FLAG_KEEP_SCREEN_ON)
            _set_flag()

            # Partial wake lock keeps CPU alive when screen is off.
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            PowerManager = autoclass("android.os.PowerManager")
            pm = PythonActivity.mActivity.getSystemService(Context.POWER_SERVICE)
            self._wake_lock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "eegmeditation:session"
            )
            self._wake_lock.acquire()
            logger.info("Wake lock acquired (partial + screen-on).")
        except Exception as e:
            logger.warning(f"Failed to acquire wake lock: {e}")

    def _release_wake_lock(self) -> None:
        """Release wake locks (Android only)."""
        if not hasattr(sys, "getandroidapilevel"):
            return
        try:
            if self._wake_lock is not None:
                try:
                    self._wake_lock.release()
                except Exception:
                    pass
                self._wake_lock = None
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _clear_flag():
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                WindowManager = autoclass("android.view.WindowManager$LayoutParams")
                activity.getWindow().clearFlags(WindowManager.FLAG_KEEP_SCREEN_ON)
            _clear_flag()
            logger.info("Wake lock released.")
        except Exception as e:
            logger.warning(f"Failed to release wake lock: {e}")

    def _start_session_keep_alive_service(self) -> None:
        """Start the Android foreground service that protects the session from OS kill."""
        if not hasattr(sys, "getandroidapilevel"):
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            service_cls = autoclass("org.eeg.eegmeditation.ServiceSessionkeepalive")
            service_cls.start(PythonActivity.mActivity, "")
            logger.info("SessionKeepAlive service started.")
        except Exception as e:
            logger.warning(f"Failed to start SessionKeepAlive service: {e}")

    def _stop_session_keep_alive_service(self) -> None:
        if not hasattr(sys, "getandroidapilevel"):
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            service_cls = autoclass("org.eeg.eegmeditation.ServiceSessionkeepalive")
            service_cls.stop(PythonActivity.mActivity)
            logger.info("SessionKeepAlive service stopped.")
        except Exception as e:
            logger.warning(f"Failed to stop SessionKeepAlive service: {e}")

    # Map bottom-nav tab keys to screen groups
    _TAB_SCREENS = {
        "session": "live_session",
        "history": "history",
        "settings": "settings",
    }

    def build(self) -> FloatLayout:
        install_crash_handler(self)

        self._theme_seed = theme_seed(self._db)
        C.set_theme(startup_theme(self._db))
        F.set_scale(startup_text_size(self._db))

        # Apply --serial override if provided
        if self.serial_device_override:
            path = self.serial_device_override
            self._real_stream.set_device(path, f"Splitter ({path})")
            APP.USE_MOCK_DEVICE = False
            logger.info(f"Serial device override: {path}")

        root = BoxLayout(orientation="vertical")
        fill_background(root, C.BG_DARK)

        # --- Screen manager (routed via nav) ---
        self._sm = ScreenManager(transition=SlideTransition())

        self._live_screen = LiveSessionScreen()
        self._program_run = ProgramRun(self._session_manager, self._audio, self._live_screen, on_main=self._on_main,
                                       formula_vars=self._eval_formula_vars)
        self._settings_screen = SettingsScreen()
        self._history_screen = HistoryScreen()
        self._diary_screen = DiaryScreen()
        self._timer_state = TimerState()
        self._program_settings = ProgramSettings(
            self._db, self._settings_screen.timer, self._live_screen, self._session_manager,
            user_id=lambda: self._current_user_id, require_user=self._require_user, confirm=self._confirm_action,
            info=self._info_popup, confirm_saved_delete=self._confirm_saved_delete,
            show_saved_series=lambda uid: self._graph_series.apply_saved(self._live_screen.graph, uid),
            save_settings=self._save_user_settings)
        self._formula_settings = FormulaSettings(
            self._db, self._settings_screen.formulas, self._live_screen.graph, self._formulas,
            user_id=lambda: self._current_user_id, require_user=self._require_user,
            scoring_locked=self._scoring_locked, audio_key=lambda: self._audio_metric_key,
            confirm_saved_delete=self._confirm_saved_delete)
        self._headset = Headset(
            self._db, self._real_stream, self._settings_screen.device, self._live_screen,
            user_id=lambda: self._current_user_id, refused_while_session_runs=self._refused_while_session_runs,
            waiting_for_bt=lambda: self._waiting_for_bt, switch_to_settings=lambda: self._switch_screen("settings"),
            serial_override=lambda: self.serial_device_override,
            report=lambda label, detail, force=False: report_soft_error(label, detail, app=self, force=force))
        self._headset.load_aliases()

        self._sm.add_widget(self._live_screen)
        self._sm.add_widget(self._history_screen)
        self._sm.add_widget(self._settings_screen)
        self._sm.add_widget(self._diary_screen)

        root.add_widget(self._sm)

        # --- Bottom navigation ---
        self._bottom_nav = BottomNav(
            tabs=[
                ("Session", "session"),
                ("History", "history"),
                ("Settings", "settings"),
            ],
            callback=self._on_nav_tab,
        )
        root.add_widget(self._bottom_nav)

        # Wrap in a FloatLayout so app-global overlays (loading spinner,
        # fullscreen graph) can sit on top of every screen.
        float_root = FloatLayout()
        self._float_root = float_root
        self._fullscreen = GraphFullscreen(float_root)
        self._graph_series = GraphSeries(
            self._db, self._live_screen.graph, self._formulas, self._program_run, self._program_settings,
            self._formula_settings, self._fullscreen, graphs=self._all_graphs,
            legacy_defaults=self._settings_screen._graph_toggles, user_id=lambda: self._current_user_id,
            require_user=self._require_user)
        self._last_back_time = 0.0  # for double-back-to-exit on the root screen
        float_root.add_widget(root)
        self._loading_overlay = LoadingOverlay()
        float_root.add_widget(self._loading_overlay)

        self._bind_callbacks()
        self._link_graph_zoom()
        # After _bind_callbacks (it sets the fields get() snapshots as defaults), before any user load.
        self._build_settings_store()
        resolved_user = self._restore_last_user()
        self._refresh_profile()

        # Hard user gate: the app is never usable without a resolved concrete
        # user. Gate on "did we resolve a user", NOT on whether the users table
        # is non-empty — reinstall / restored DB / deleted-active-profile /
        # corrupt last_user_id all leave users present but none current. Disable
        # nav synchronously so there is no cold-start window where the app is
        # tappable with no user; the selection modal re-enables it. The modal
        # is a Popup, not a Screen, because a TextInput inside a
        # Screen doesn't get keyboard focus on some platforms.
        if resolved_user is None:
            self._open_user_gate(0.5)
        else:
            self._headset.auto_scan()

        return float_root

    def show_loading(self, text: str = "Loading…", delay: float = 0.0) -> None:
        """Show the app-global loading overlay (no-op before build); `delay` as in LoadingOverlay.show."""
        if getattr(self, "_loading_overlay", None) is not None:
            self._loading_overlay.show(text, delay)

    def hide_loading(self) -> None:
        """Hide the app-global loading overlay (no-op before build)."""
        if getattr(self, "_loading_overlay", None) is not None:
            self._loading_overlay.hide()

    def _all_graphs(self) -> tuple:
        """Every mounted graph, for the cross-graph affordances (expand, picker, fit, restore); zoom links per group."""
        return self._live_graphs() + self._detail_graphs()

    def _live_graphs(self) -> tuple:
        return self._live_screen.graph, self._live_screen.raw_graph, self._live_screen.band_graph

    def _detail_graphs(self) -> tuple:
        return self._diary_screen._metrics_graph, self._diary_screen._raw_eeg_graph, self._diary_screen._freq_graph

    def _wire_graph_affordances(self) -> None:
        """Give every mounted graph the shared fullscreen-expand, series-picker and fit
        glyphs, driven by one presenter each. The picker is wired only where there
        is more than one series to choose from — a single-series graph's picker
        could only blank the line."""
        for g in self._all_graphs():
            g.set_expand_callback(self._fullscreen.present)
            if len(g.series_keys()) > 1:
                g.set_series_picker_callback(self._graph_series.present_picker)
            g.set_fit_callback(ScrollableGraphWidget.toggle_fit)  # its zoom group, together

    def _saved_zoom_seconds(self) -> float:
        return self._live_screen.graph.zoom_seconds

    def _apply_saved_zoom(self, seconds: float) -> None:
        """The saved zoom starts both groups; only the live one's is saved, so a detail's zoom never comes back."""
        self._live_screen.graph.set_zoom_seconds(seconds)
        self._diary_screen._metrics_graph.set_zoom_seconds(seconds)

    def _link_graph_zoom(self) -> None:
        """Two zoom groups: a detail zoomed out over a long session must not reach the live graphs' saved zoom."""
        ScrollableGraphWidget.link_zoom(*self._live_graphs())
        ScrollableGraphWidget.link_zoom(*self._detail_graphs())

    def _bind_callbacks(self) -> None:
        self._live_screen.btn_start.bind(on_release=self._on_start)
        self._live_screen.btn_pause.bind(on_release=self._on_pause)
        self._live_screen.btn_stop.bind(on_release=self._on_stop)
        self._live_screen.btn_marker.bind(on_release=self._on_marker)
        self._live_screen.on_duration_preset = self._program_settings.on_duration_preset
        self._live_screen.on_program_pick = self._program_settings.on_load
        self._live_screen.overlay_cancel_btn.bind(on_release=self._on_connect_cancel)
        self._live_screen.overlay_retry_btn.bind(on_release=self._on_connect_retry)
        self._live_screen.summary_ok_btn.bind(on_release=self._on_summary_ok)
        self._live_screen.summary_save_notes_btn.bind(on_release=self._on_summary_save_notes)
        self._live_screen.summary_delete_btn.bind(on_release=self._on_summary_delete)

        # Tap on graph to set marker (Android — no keyboard available)
        if kivy_platform == "android":
            wire(self._live_screen.graph, on_tap=self._on_marker)

        # Shared fullscreen-expand + series-picker glyphs on every graph
        self._wire_graph_affordances()

        wire(
            self._settings_screen,
            on_threshold_change=self._on_threshold_change,
            on_audio_metric_change=self._on_audio_metric_change,
            on_audio_formula_index=self._on_audio_formula_index,
            on_theme_change=self._on_theme_change,
            on_profile_switch=self._on_user_switch,
            on_profile_create=self._on_user_create,
            on_profile_delete=self._on_user_delete,
            session_counter=self._count_sessions_for_user,
        )
        wire(
            self._settings_screen.audio,
            on_test_audio=self._on_test_audio,
            on_sinking_alert_toggle=self._on_sinking_alert_toggle,
            on_subtle_alert_toggle=self._on_subtle_alert_toggle,
            on_disconnect_alert_toggle=self._on_disconnect_alert_toggle,
            on_feedback_source_change=self._on_feedback_source_change,
            on_reward_source_change=self._on_reward_source_change,
        )
        wire(
            self._settings_screen.device,
            on_device_mode_toggle=self._headset.on_mode_toggle,
            on_scan_devices=self._headset.on_scan,
            on_device_select=self._headset.on_select,
            device_state=self._headset.state,
            on_device_rename=self._headset.on_rename,
            on_copy_diagnostics=self._headset.on_copy_diagnostics,
        )
        wire(
            self._settings_screen.display,
            on_text_size=self._on_text_size_change,
            on_line_colours=self._on_line_colours_change,
            on_line_width_change=self._on_line_width_change,
            on_rotate_screen=self._on_rotate_screen,
        )
        wire(
            self._settings_screen.formulas,
            on_formula_slot_change=self._formula_settings.on_slot_change,
            on_save_formula=self._formula_settings.on_save,
            on_load_formula=self._formula_settings.on_load,
            on_delete_formula=self._formula_settings.on_delete,
            on_export_formulas=self._formula_settings.on_export,
        )
        wire(
            self._settings_screen.timer,
            on_program_mode=self._program_settings.on_mode_change,
            on_program_changed=self._program_settings.on_changed,
            on_program_save=self._program_settings.on_save,
            on_program_load=self._program_settings.on_load,
            on_program_delete=self._program_settings.on_delete,
            on_test_timer_sound=self._on_test_timer_sound,
            on_stop_timer_sound=self._on_stop_test_timer_sound,
            on_timer_sound_change=self._on_timer_sound_change,
        )

        # Keyboard hotkey for marker
        Window.bind(on_key_down=self._on_key_down)
        # Android hardware back button (key 27) — consume it so Kivy's default
        # exit-on-escape doesn't fire; navigate / double-tap-to-exit instead.
        Window.bind(on_keyboard=self._on_keyboard)

        # Hide all custom-formula series until a formula is set + shown via picker
        for _fk in FORMULA_KEYS:
            self._live_screen.graph.set_visible(_fk, False)
        # The program-formula lines are shown only while a program with
        # custom-formula segments runs.
        for _pk in PROGRAM_FORMULA_KEYS:
            self._live_screen.graph.set_visible(_pk, False)
        # Apply default metric visibility (Shamatha only for new users;
        # _load_user_settings will override for existing users)
        for key, active in self._settings_screen._graph_toggles.items():
            self._live_screen.graph.set_visible(key, active)
        self._audio_metric_key: str = "shamatha_score"
        self._feedback_source: str = "noise"
        self._feedback_sound_path: str = ""
        self._reward_source: str = "none"   # above-threshold reward channel (off by default)
        self._reward_sound_path: str = ""

        wire(
            self._diary_screen,
            on_save_notes=self._on_save_notes,
            on_export_csv=self._on_export_csv,
            on_back=self._on_diary_back,
            on_band_view_change=self._persist_band_view,
        )

        wire(
            self._history_screen,
            on_session_select=self._on_session_select,
            on_delete_sessions=self._delete_sessions,
            on_rename_session=self._on_rename_session,
            on_view_mode_change=self._on_history_view_mode_change,
            on_export_sessions=self._on_export_sessions_csv,
        )
        self._history_screen.set_chart_collapse_callback(
            lambda _collapsed: self._persist_user_setting("history_chart_collapsed"))
        self._diary_screen.what_if.set_collapse_callback(
            lambda _collapsed: self._persist_user_setting("what_if_collapsed"))
        self._diary_screen.set_band_collapse_callback(
            lambda _collapsed: self._persist_user_setting("band_power_collapsed"))

        # Data Backup section
        self._backup_flow = BackupFlow(
            self._db, self._settings_screen, user_name=self._current_user_name,
            save_settings=self._save_user_settings, checkpoint=self._checkpoint_or_report,
            refused_while_session_runs=self._refused_while_session_runs, confirm=self._confirm_action,
            info=self._info_popup, on_db_replaced=self._on_db_replaced,
        )
        wire(
            self._settings_screen,
            on_backup_pressed=self._backup_flow.on_backup_pressed,
            on_restore_pressed=self._backup_flow.on_restore_pressed,
        )

    def _activate_user(self, uid: int) -> None:
        """Make `uid` the active profile and load its settings; every path that picks a user goes here."""
        if self._live_display_uid not in (None, uid):  # the Session screen shows another profile's session
            self._drop_shown_session(keep_notes=True)
        self._current_user_id = uid
        self._view_all_users = False
        self._db.set_setting("last_user_id", str(uid))
        self._load_user_settings(uid)
        self._mark_history_dirty()  # History still lists the previous profile's sessions

    def _restore_last_user(self) -> Optional[int]:
        """Restore the last selected user; return the resolved uid, or None when
        the app must prompt (no/stale/corrupt last_user_id). build() opens the
        blocking user gate on None — the app is never left usable with no user."""
        uid = resolve_startup_user(self._db)
        if uid is None:
            return None
        self._activate_user(uid)
        logger.info(f"Restored last user id={uid}")
        return uid

    def _open_user_gate(self, delay: float = 0.0) -> None:
        """Enter the hard user gate: disable the bottom nav and open the blocking
        selection modal. Single source for build() / on_resume / self-delete so
        the 'app unusable without a user' enforcement can't drift between them."""
        # Disable nav BEFORE any dedupe return — the gate state must be enforced
        # even when a popup is already open/scheduled.
        self._bottom_nav.disabled = True
        if getattr(self, "_gate_popup", None) is not None:
            return  # a gate popup is already open — don't stack another
        if getattr(self, "_gate_event", None) is not None:
            return  # one is already scheduled (pre-popup window) — don't stack
        self._gate_event = Clock.schedule_once(self._show_first_run_popup, delay)

    def _handle_gate_back(self) -> bool:
        """Back/Esc while gated: never fall through into the app, but the user must
        still be able to LEAVE — double-press exits the app (a gate with no exit
        traps a fresh-install user who declines to create a profile)."""
        return self._exit_on_second_back()

    def _exit_on_second_back(self) -> bool:
        """A second back press within 2 s exits the app; the first says so."""
        now = time.time()
        if now - self._last_back_time < 2.0:
            App.get_running_app().stop()
            return True
        self._last_back_time = now
        self._toast("Press back again to exit")
        return True

    def _gate_active(self) -> bool:
        """True while the app is gated on user selection — nav disabled, no concrete
        user, not the deliberate All-Users view. Covers both the popup-open state and
        the schedule window before the popup exists, so the gate is un-escapable throughout."""
        nav = getattr(self, "_bottom_nav", None)
        return bool(nav is not None and nav.disabled
                    and not getattr(self, "_current_user_id", None)
                    and not getattr(self, "_view_all_users", False))

    def _reopen_gate_if_unresolved(self) -> None:
        """After a gate create/pick attempt, re-open the gate if no concrete user
        ended up set (invalid name, or a stale/deleted profile row) — otherwise the
        popup is gone, nav stays disabled, and the app is stranded with no user."""
        if not self._current_user_id and not self._view_all_users:
            self._refresh_profile()  # drop any stale row from the picker list
            self._open_user_gate(0)

    def _show_first_run_popup(self, dt) -> None:
        """Show a name-entry popup on first run (no users in DB).

        After uninstall→reinstall on Android, the DB may persist with
        existing profiles — UserPickerForm surfaces them so the user can
        adopt instead of creating a duplicate name.
        """
        self._gate_event = None  # the scheduled open is now firing
        if getattr(self, "_gate_popup", None) is not None:
            return  # a gate popup is already open — never stack a second modal

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))

        welcome = ThemedLabel(
            text="Welcome! Create a profile or pick an existing one:",
            font_size=F.BODY, color=C.TEXT,
            size_hint_y=None, height=dp(48),
            halign="center",
        )
        welcome.bind(size=welcome.setter("text_size"))
        content.add_widget(welcome)

        popup = ThemedPopup(
            title="Select Profile",
            content=content,
            size_hint=(0.9, None),
            auto_dismiss=False,
        )
        # Tracked so _on_keyboard can make the gate un-escapable (back/Esc must
        # not dismiss it or exit the app out from under an unresolved user).
        self._gate_popup = popup
        # A dismissal from ANY path clears the handle, so a stale non-None
        # _gate_popup can never block re-gating forever.
        popup.bind(on_dismiss=lambda *_a: setattr(self, "_gate_popup", None))

        def _on_create(name: str) -> None:
            self._gate_popup = None
            popup.dismiss()
            self._complete_first_run(name)
            self._reopen_gate_if_unresolved()

        def _on_pick(user_id: int) -> None:
            self._gate_popup = None
            popup.dismiss()
            self._on_pick_existing_user(user_id)
            self._reopen_gate_if_unresolved()

        form = UserPickerForm(
            on_create=_on_create,
            on_pick_existing=_on_pick,
        )
        existing_users = self._db.get_all_users()
        form.populate_users(existing_users)
        content.add_widget(form)
        popup.open()

    def _complete_first_run(self, user_name: str) -> None:
        """First-run popup: a typed name creates that profile, in mock mode until a headset is picked; a name that
        exists picks that profile instead."""
        if not user_name or len(user_name.strip()) < 2:
            logger.warning(f"First run with invalid name: '{user_name}', ignoring")
            return
        try:
            uid = self._db.create_user(user_name)
        except UserExistsError as e:
            logger.info(f"First run: '{e.name}' exists, picking it (id={e.user_id})")
            self._on_pick_existing_user(e.user_id)
            return
        except sqlite3.Error as e:  # the popup's caller reopens the gate: no profile was made
            report_soft_error("user_create_failed", f"The profile '{user_name}' could not be created: {e}")
            return
        self._activate_user(uid)
        APP.USE_MOCK_DEVICE = True
        self._db.set_user_setting(uid, "use_mock", "True")
        self._settings_screen.device._device_mode_cb.active = True
        self._live_screen.update_device_status(False, device_name="Mock EEG")
        logger.info("First run: using mock device")
        self._finish_first_run(f"user '{user_name}' created")

    def _finish_first_run(self, what: str) -> None:
        """Leave the first-run popup for the Session screen, the nav usable again."""
        self._bottom_nav.opacity = 1
        self._bottom_nav.disabled = False
        self._refresh_profile()
        self._sm.current = "live_session"
        self._bottom_nav.active_tab = "session"
        self._headset.auto_scan()
        logger.info(f"First run complete: {what}")

    def _on_nav_tab(self, tab_key: str) -> None:
        """Handle bottom nav tab press."""
        screen_name = self._TAB_SCREENS.get(tab_key, tab_key)
        self._switch_screen(screen_name)

    def _switch_screen(self, name: str) -> None:
        if name == "diary" and not self._current_user_id and not self._view_all_users:
            # silent-ok: unreachable post-gate; All-Users browse and any
            # concrete user pass. Defensive block against a should-not-happen unset.
            logger.debug("Diary switch blocked: no user selected")
            return
        logger.debug(f"Screen switch: {name}")
        self._sm.current = name
        if name == "history":
            self._refresh_history()
        elif name == "live_session":
            # Reflect any Settings timer/mode change on the Start duration button.
            self._program_settings.sync_picker()
        # Sync bottom nav highlight
        for tab_key, screen in self._TAB_SCREENS.items():
            if screen == name:
                self._bottom_nav.active_tab = tab_key
                break

    def _on_start(self, *args) -> None:
        if not self._current_user_id:
            self._live_screen.update_state("Select a user profile first")
            logger.warning("Session start blocked: no user selected")
            return

        self._start_attempt += 1
        attempt = self._start_attempt
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream = self._mock_stream
            self._start_session_common()
            return

        # Real device — need BT connection
        if self._real_stream._device_address:
            # Device already selected (from settings or auto-scan)
            self._eeg_stream = self._real_stream
            self._start_session_common()
            return

        # No device selected — auto-scan and connect
        self._live_screen.show_overlay("Scanning for MindWave...")
        self._live_screen.set_controls_running()
        logger.info("Auto-scanning for BT device before session start")


        def _scan_and_connect():
            devices = NeuroSkyStream.scan_paired_devices()
            matches = filter_mindwave(devices)

            def _on_main_thread(dt):
                if attempt != self._start_attempt:
                    return  # cancelled while scanning
                if len(matches) == 1:
                    mindwave = matches[0]
                    self._headset.on_select(mindwave["address"], mindwave["name"])
                    self._eeg_stream = self._real_stream
                    self._live_screen.update_overlay(f"Found {self._headset.name()}\nConnecting...")
                    self._start_session_common()
                elif len(matches) > 1:
                    # Multiple NeuroSky devices paired — user must pick.
                    self._headset.list_devices(matches)
                    self._live_screen.set_controls_idle()
                    self._live_screen.hide_overlay()
                    self._switch_screen("settings")
                    self._settings_screen.device.focus_device_section(
                        f"Found {len(matches)} MindWave devices.\n"
                        "Pick the one you want to use, then press Start again."
                    )
                elif devices:
                    # Found BT devices but no MindWave
                    self._headset.list_devices(devices)
                    self._live_screen.set_controls_idle()
                    self._live_screen.show_overlay_retry(
                        "No MindWave found among paired devices.\n"
                        "Pair it in system Bluetooth settings,\n"
                        "or select manually in Settings tab."
                    )
                else:
                    self._live_screen.set_controls_idle()
                    self._live_screen.show_overlay_retry(
                        "No paired Bluetooth devices found.\n"
                        "Pair your MindWave in system\n"
                        "Bluetooth settings first."
                    )

            Clock.schedule_once(_on_main_thread)

        threading.Thread(target=_scan_and_connect, daemon=True).start()

    def _on_main(self, fn) -> None:
        """Queue callable on Kivy's main thread.

        Thread-safe per Kivy docs.  During Kivy pause (screen locked) the
        call is buffered and executed when the app resumes.
        """
        Clock.schedule_once(lambda dt: fn(), 0)

    # ------------------------------------------------------------------

    def _start_session_common(self) -> None:
        """Shared session startup logic after device is resolved."""
        # If the user starts a new session while a long custom timer bell
        # from the previous session is still ringing, kill it so it
        # doesn't overlap with the new session's noise loop.
        self._audio.stop_timer_bell()
        threshold = self._settings_screen.threshold
        program = self._program_settings.for_session()
        self._cancel_settle("apply_threshold")  # a slider move just before Start: the start applies the slider itself
        if program:
            # Program total drives the timer so auto-stop reuses the proven
            # timer-expiry path; the first segment's target seeds the threshold.
            threshold = segment_target(program.segments[0])
            self._timer_state.set_enabled(True)
            self._timer_state.set_duration(max(1, int(round(program.total_seconds / 60))))
            logger.info(f"Program session: {format_count(len(program.segments), 'segment')}, "
                        f"{program.total_seconds:.0f}s total drives the end gong")
        else:
            # Session start is authoritative: re-sync the timer from Settings so a
            # prior program session's enabled/duration can't leak into a simple one.
            self._timer_state.set_enabled(self._settings_screen.timer.timer_enabled)
            self._timer_state.set_duration(self._settings_screen.timer.timer_minutes)
        self._put_threshold_in_force(threshold)  # this session's, whatever the last one left running
        self._metrics_engine.reset()
        self._noise_detector = PowerLineDetector() if not APP.USE_MOCK_DEVICE else None
        self._recorder.begin()
        self._tick_count = 0
        self._bt_connected_notified = False
        self._pending_marker = False
        self._bt_connect_start = time.time()

        self._clear_live_display()
        self._live_display_uid = self._current_user_id
        gid = self._global_feedback_id()
        if program:
            fb_sources, fb_ids, fb_initial = self._feedback_plan(program, gid)
        else:
            fb_sources, fb_ids, fb_initial = {gid: self._source_spec(gid)}, [], gid
        self._program_run.begin(program, fb_ids, self._program_settings.name)
        # Above-threshold reward channel (global; "" = none). Add its player to the set.
        reward_id = self._reward_id()
        if reward_id:
            fb_sources[reward_id] = self._source_spec(reward_id)
        timer = self._timer_state
        self._warn_missing_sound_files(fb_sources, timer.custom_sound_path if timer.enabled else "")
        self._audio.prepare_feedback(fb_sources, fb_initial)
        self._audio.set_reward(reward_id)
        self._live_screen.set_training_series(None)  # set on first segment crossing
        self._scored_key = None  # a simple session marks its scored series on the first tick
        self._shamatha_active = False
        self._shamatha_streak = 0
        self._live_screen.set_controls_running()
        self._settings_screen.lock_threshold(self._refuse_program_threshold if self._program_run.active else None)

        self._acquire_wake_lock()
        self._start_session_keep_alive_service()

        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.start()
            self._waiting_for_bt = False
            self._session_manager.start(threshold=threshold)
            self._audio.start()
            self._timer_state.start_countdown()
            self._live_screen.update_device_status(True)
            self._live_screen.update_state("Running")
            self._live_screen.set_start_time(self._session_manager.started_at)
            self._live_screen.hide_overlay()
        elif self._real_stream.is_connected:
            # BT still connected from previous session — reuse it
            self._real_stream.reset_sample_state()
            self._waiting_for_bt = False
            name = self._headset.name()
            self._session_manager.start(threshold=threshold)
            self._timer_state.start_countdown()
            self._on_session_connected(name)
            logger.info(f"Reusing existing BT connection to {name}")
        elif not self._begin_bt_wait():
            return

        self._ticker.start()
        self._tick_count = 0
        logger.info("Session started via UI")

    def _begin_bt_wait(self) -> bool:
        """Start the reader and show the connect overlay; False, with the session setup undone, if refused."""
        name = self._headset.name()
        if not self._real_stream.start():
            # Nothing is connecting: entering the wait would misreport a refusal as a failed connect.
            self._undo_session_setup()
            self._live_screen.update_device_status(False, device_name=name)
            self._live_screen.show_overlay_retry(
                f"Can't connect to {name} yet.\n{self._real_stream._last_connect_error}"
            )
            logger.info(f"BT start refused: {self._real_stream._last_connect_error!r}")
            return False
        self._wait_attempt = self._start_attempt
        self._waiting_for_bt = True
        self._bt_drops = 0
        self._live_screen.update_device_status(False, device_name=name, connecting=True)
        self._live_screen.show_overlay(f"Connecting to {name}...")
        logger.info(f"Waiting for BT connection to {name}")
        return True

    def _abort_bt_wait(self) -> None:
        """Tear down a BT-connect wait; the tick watcher stops first or it reads our stop as a failed connect."""
        self._ticker.stop()
        self._waiting_for_bt = False
        self._bt_signal_start = None
        self._real_stream.stop()
        self._release_wake_lock()
        self._stop_session_keep_alive_service()
        self._live_display_uid = None  # no session came of the start, which emptied the display

    def _on_connect_cancel(self, *args) -> None:
        """Cancel button on connection overlay."""
        self._cancel_session_start("IDLE")

    def _cancel_session_start(self, state: str) -> None:
        """End a start that hasn't become a session: the device scan, the BT wait, or data that arrived in the same frame
        as the Cancel."""
        if self._waiting_for_bt or self._ticker.running:
            self._abort_bt_wait()
        self._live_screen.hide_overlay()
        self._undo_session_setup()  # also resets a session that started in the frame of the Cancel
        self._live_screen.update_state(state)

    def _undo_session_setup(self) -> None:
        """Main thread: undo what _start_session_common set up, for a session that ended or never started. Ends its
        start attempt, so the callbacks still queued for it do nothing."""
        self._start_attempt += 1
        self._live_screen.set_training_series(None)  # clear the program "training now" marker
        self._program_run.end()
        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._shamatha_active = False
        self._shamatha_streak = 0
        self._live_screen.set_shamatha(False)
        self._timer_state.reset()
        self._session_manager.reset()
        self._settings_screen.lock_threshold(None)
        self._release_wake_lock()
        self._stop_session_keep_alive_service()

    def _on_connect_retry(self, *args) -> None:
        """Retry button on connection overlay."""
        self._live_screen.hide_overlay()
        self._live_screen.set_controls_idle()
        self._on_start()

    # The session-end card: the session is already saved on every ending; the card only adds notes or deletes it.
    _summary_saved_notes: str = ""  # notes last written from the card for the session it shows
    _live_display_uid: int | None = None  # the profile whose session the Session screen shows: set at Start

    def _on_summary_save_notes(self, *args) -> None:
        if self._live_screen.summary_notes == self._summary_saved_notes:
            if self._summary_saved_notes:
                self._toast("Notes saved")  # already saved; say so rather than ignore the tap
            return
        self._flush_summary_notes()

    def _flush_summary_notes(self) -> None:
        """Write the card's notes only if they changed since the last save, so an untouched card writes nothing."""
        sid = self._live_screen.summary_session_id
        notes = self._live_screen.summary_notes
        if sid and notes != self._summary_saved_notes and self._save_session_notes(sid, notes=notes):
            self._summary_saved_notes = notes

    def _flush_on_leave(self) -> None:
        """Persist what the user changed but hasn't saved, before the app pauses or exits."""
        self._leaving = True
        try:
            if getattr(self, "_live_screen", None) is not None:
                self._flush_summary_notes()
            self._checkpoint_or_report()  # Android may kill a backgrounded app before the next 60 s checkpoint
            # Only on screen: leaving it already saved (or reported a failed save), and a retry on every pause
            # repeated the error, e.g. for a session deleted since.
            if getattr(self, "_diary_screen", None) is not None and self._sm.current == self._diary_screen.name:
                self._diary_screen.flush_notes()
            self._save_user_settings()
        finally:
            self._leaving = False

    def _checkpoint_or_report(self) -> None:
        """Checkpoint a running session where a failure must not stop what follows (leaving the app, a backup)."""
        try:
            self._recorder.checkpoint()
        except Exception as exc:
            logger.exception("Session checkpoint failed")
            report_soft_error("session_checkpoint_failed", f"The running session could not be saved: {exc}")

    def _on_summary_ok(self, *args) -> None:
        self._close_summary(keep_notes=True)

    def _close_summary(self, keep_notes: bool) -> None:
        """Close the end card and stop its bell; its notes are saved only while its session still exists."""
        if keep_notes:
            self._flush_summary_notes()
        self._audio.stop_timer_bell()
        self._live_screen.hide_summary()

    def _drop_shown_session(self, keep_notes: bool) -> None:
        """Take the shown session off the Session screen: its end card, if open, and its display."""
        if self._live_screen.summary_session_id is not None:
            self._close_summary(keep_notes)
        self._clear_live_display()
        self._live_display_uid = None

    def _on_summary_delete(self, *args) -> None:
        sid = self._live_screen.summary_session_id
        if not sid:
            return  # silent-ok: the card is not showing a session

        # The delete closes the card and stops the gong once the session is gone; a failed one leaves both.
        self._confirm_action("Delete session", "Delete this session permanently? This can't be undone.",
                             "Delete", lambda: self._delete_sessions([sid]), ok_color=C.DANGER)

    def _save_session_notes(self, session_id: int, notes: Optional[str] = None,
                            tags: Optional[str] = None, mood: Optional[int] = None) -> bool:
        """The one notes-save path (session-end card, diary): writes only the given fields; failures are reported."""
        try:
            saved = self._db.update_session_notes(session_id, notes=notes, tags=tags, mood_rating=mood)
        except sqlite3.Error as exc:
            report_soft_error("notes_save_failed", f"Notes for session {session_id} were not saved: {exc}")
            return False
        if not saved:
            report_soft_error("notes_save_failed", f"Notes for session {session_id} were not saved: no such session")
            return False
        # In place: a reload would start the History list from the top.
        self._history_screen.update_session(session_id, notes=notes, tags=tags, mood_rating=mood)
        self._toast("Notes saved")
        logger.info(f"Notes saved for session {session_id}")
        return True

    def _on_pause(self, *args) -> None:
        if self._session_manager.state == SessionState.RUNNING:
            self._session_manager.pause()
            self._live_screen.set_controls_paused()
            # Not stop(): that tears down the session's prepared players, which only session start rebuilds.
            self._audio.pause()
            self._ticker.stop()
            logger.info("Session paused")
        elif self._session_manager.state == SessionState.PAUSED:
            self._session_manager.resume()
            self._live_screen.set_controls_running()
            self._audio.resume()
            self._ticker.start()
            logger.info("Session resumed")

    def _on_stop(self, *args) -> None:
        # Decided by the session, not by the wait flag: a wait that has just ended cleared the flag before its idle UI.
        if self._session_manager.state == SessionState.FINISHED:
            logger.info("Stop ignored: the session has already ended and its teardown is queued")
            return
        if self._session_manager.state not in (SessionState.RUNNING, SessionState.PAUSED):
            self._cancel_session_start("Cancelled")
            logger.info("Session cancelled before it started")
            return

        # Pause the tick thread while the dialog is open
        self._ticker.stop()
        # Every ending saves (the same path as a timer or lost-signal stop); deleting is a confirmed card action.
        self._confirm_action(
            "Stop session?", "The session will be saved. You can delete it on the next screen.",
            "Stop", lambda: self._stop_and_save(reason="user"), on_cancel=self._cancel_stop,
        )

    def _make_session_name(self) -> str:
        """Generate default session name including device type."""
        device = "Mock" if APP.USE_MOCK_DEVICE else self._headset.name()
        started = self._session_manager.started_at
        ts = start_stamp(_dt.fromtimestamp(started) if started else _dt.now())
        return f"{ts} - {device}"

    def _persist_session_data(self, reason: str) -> dict:
        """Stop the session and write final stats + metrics to the DB.

        Tick-thread-safe: contains NO Kivy/UI calls so it can run directly on
        the daemon tick thread at timer expiry. That makes the finished session
        durable even if Android kills the app during a screen lock before the
        user unlocks — the main-thread Clock (and `_on_main`) is paused while
        locked, so deferring the save risked losing the whole session.
        """
        stats = self._with_score(self._session_manager.stop(reason=reason))
        # Keep real BT connection alive between sessions to avoid EBUSY on reconnect.
        # Only the mock stream gets stopped here; real stream stays connected.
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.stop()

        if stats:
            self._recorder.checkpoint(stats)
        return stats

    def _session_row_fields(self) -> dict:
        """The running session's row, apart from its stats and ticks, as a checkpoint writes it."""
        return {"user_id": self._current_user_id, "session_name": self._make_session_name(),
                "custom_formulas": self._session_custom_formulas_json(),
                "session_program": self._program_run.segments_json(), "engine_version": MetricsEngine.ENGINE_VERSION,
                "started_at": self._session_manager.started_at or None}

    def _finalize_stop_ui(self, stats: dict, session_id: Optional[int]) -> None:
        """Main-thread UI teardown after a session has been persisted."""
        # Reload the live graph from the mirror buffers so it shows the FULL
        # session (the locked portion never reached the live graph via the
        # per-tick path). Otherwise closing the summary reveals a stale graph
        # covering only the pre-lock seconds while History shows the real
        # duration.
        try:
            self._mirror.reload_into(self._live_screen)
        except Exception:
            logger.exception("graph reload on stop failed")
        self._live_screen.update_stats(self._mirror.last_metrics)  # the whole session's averages: no tick ran while locked
        self._undo_session_setup()
        self._live_screen.update_state("FINISHED")
        # Sync the header timer to the final duration (it froze at lock time).
        if stats:
            self._live_screen.update_timer(elapsed_clock(stats.get("duration", 0)))
        self._mark_history_dirty()
        if stats and session_id:
            self._summary_saved_notes = ""
            try:
                saved = self._db.get_session(session_id)  # titled like its History row, from what was stored
            except sqlite3.Error:
                logger.exception(f"Session {session_id} saved, but its title couldn't be read for the end card")
                saved = None
            self._live_screen.show_summary(session_id, stats, title=session_title(saved) if saved else "")

    def _refused_while_session_runs(self, doing: str, why: str = "") -> bool:
        """True, after telling the user, while a session runs or connects: until it stops it owns its profile, the
        database it saves to, the metric it is scored on and a program's targets."""
        if not self._session_pipeline_live():
            return False
        self._info_popup("Session in progress", f"{why} Stop the current session before {doing}.".lstrip())
        return True

    def _session_pipeline_live(self) -> bool:
        """True if a session is RUNNING/PAUSED *or* still in the BT-connect wait
        (tick thread started, state still IDLE). This is the full window in which a
        restore or active-profile delete would drop/orphan an in-flight session —
        the state-only check misses the connecting phase (mirrors _on_connect_cancel)."""
        return (self._session_manager.state in (SessionState.RUNNING, SessionState.PAUSED)
                or getattr(self, "_waiting_for_bt", False)
                or self._ticker.running)

    def _discard_running_session(self) -> None:
        """Halt a running session and DELETE its data — used when its owning
        profile is deleted. A checkpoint (the 60 s flush, leaving the app, a backup) may already have written a
        session row under the doomed profile; without the delete it survives as
        an orphan. Then reuses the shared _finalize_stop_ui teardown so the
        Session screen returns to idle."""
        self._waiting_for_bt = False  # also halt a session still in the BT-connect wait
        self._bt_signal_start = None
        self._ticker.stop()
        self._session_manager.stop(reason="user")
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.stop()
        self._audio.stop()
        self._recorder.discard()
        self._finalize_stop_ui(None, None)

    def _stop_and_save(self, reason: str = "user") -> None:
        """Stop session and save data immediately (no dialog). Main-thread path."""
        t_start = time.monotonic()
        self._ticker.stop()
        stats = self._persist_session_data(reason)
        self._audio.stop()
        self._finalize_stop_ui(stats, self._recorder.session_id)
        logger.info(
            f"Session stopped and saved (took {time.monotonic() - t_start:.3f}s)"
        )

    def _on_session_connected(self, name: str) -> None:
        """Main thread: a headset session has started (the BT wait's first data, or a kept-alive connection)."""
        self._live_screen.update_device_status(True, device_name=name)
        self._live_screen.update_state("Running")
        self._live_screen.set_start_time(self._session_manager.started_at)
        self._live_screen.hide_overlay()
        self._settings_screen.device.update_device_status(True, name=name)
        # Audio starts with the overlay hide, so the noise never plays while the connecting loader is still visible.
        self._audio.start()
        self._audio.play_connect_sound()

    def _cancel_stop(self) -> None:
        """Back to the session after cancelling stop; a paused one gets its tick back only on Resume."""
        if self._session_manager.state == SessionState.RUNNING:
            self._ticker.start()
        logger.info("Stop cancelled")

    def _on_main_for_wait(self, fn: Callable[[], object]) -> None:
        """Tick thread: queue fn for the main thread as part of this BT wait; it does nothing once the wait's start
        attempt has ended (a Cancel, Stop or profile delete handled before it)."""
        attempt = self._wait_attempt
        self._on_main(lambda: fn() if attempt == self._start_attempt else None)

    _BT_CONNECT_TIMEOUT = 30.0  # seconds before BT socket gives up
    _BT_SIGNAL_TIMEOUT = 8.0   # seconds to wait for EEG packets after connected
    _bt_dropped_at: float = 0.0  # monotonic: when the wait saw the link drop; earlier packets don't count after it
    _BT_MAX_DROPS = 2  # the third drop of the link in one wait ends it: the headset keeps closing it
    _bt_drops: int = 0  # drops the current wait has seen
    _STALE_DATA_THRESHOLD = 10.0  # seconds with no new packets before warning

    def _check_stale_data(self) -> None:
        """Auto-stop session when the real device stops sending EEG data.

        Called from the tick thread; UI calls dispatched via _on_main.
        """
        if APP.USE_MOCK_DEVICE:
            return
        stale_secs = self._real_stream.seconds_since_last_packet
        if stale_secs <= 0:
            self._stale_data_warned = False
            return
        if stale_secs > self._STALE_DATA_THRESHOLD:
            if not getattr(self, '_stale_data_warned', False):
                self._stale_data_warned = True
                logger.warning(f"Stale EEG data: no packets for {stale_secs:.0f}s, auto-stopping")
                self._on_main(lambda: (
                    self._live_screen.show_alert(
                        "No EEG data. Session stopped.\n"
                        "Check headset and battery."
                    ),
                    self._stop_and_save(reason="stale_data"),
                ))
        else:
            self._stale_data_warned = False

    def _give_up_bt_wait(self, name: str, message: str) -> None:
        """End the wait from the tick thread with a retry screen (queued for this attempt only)."""
        self._abort_bt_wait()
        self._on_main_for_wait(lambda: (
            self._undo_session_setup(),
            self._live_screen.update_device_status(False, device_name=name),
            self._live_screen.show_overlay_retry(message),
        ))

    def _handle_bt_wait(self) -> None:
        """Handle the BT connection wait phase (called from _update_tick).

        Runs on the background tick thread — all Kivy UI calls are dispatched
        via _on_main so they execute safely on the main thread.
        """
        name = self._headset.name()
        link_dropped = not self._real_stream.is_connected and self._bt_signal_start is not None
        if link_dropped and self._bt_link_dropped(name):
            return
        elapsed = time.time() - self._bt_connect_start

        if self._real_stream.is_connected:
            self._wait_for_data(name)
        elif not self._real_stream._running:
            self._bt_connect_failed(name)
        elif elapsed > self._BT_CONNECT_TIMEOUT:
            self._bt_connect_timed_out(name)
        else:
            # Still waiting for BT socket — show countdown
            remaining = int(self._BT_CONNECT_TIMEOUT - elapsed)
            msg = f"Connecting to {name}...\nTimeout in {remaining}s"
            self._on_main_for_wait(lambda m=msg: self._live_screen.update_overlay(m))

    def _bt_link_dropped(self, name: str) -> bool:
        """Tick thread: the link dropped and the reader reconnects; True if the headset keeps closing it (the wait ends)."""
        # The next connection gets its own connect and no-data windows, and only its own packets count.
        self._bt_signal_start = None
        self._bt_dropped_at = time.monotonic()
        self._bt_connect_start = time.time()
        self._bt_drops += 1
        if self._bt_drops > self._BT_MAX_DROPS:
            self._give_up_bt_wait(name, f"{name} keeps closing the connection.\n"
                                        "Switch the headset off and on, then retry.")
            logger.error(f"BT wait: {name} closed the connection {self._bt_drops} times, giving up")
            return True
        return False

    def _wait_for_data(self, name: str) -> None:
        """Tick thread: BT socket connected — waiting for actual EEG data; the first data starts the session."""
        if not getattr(self, '_bt_signal_start', None):
            self._bt_signal_start = time.time()
        signal_elapsed = time.time() - self._bt_signal_start
        signal_remaining = int(self._BT_SIGNAL_TIMEOUT - signal_elapsed)

        raw_sample = self._eeg_stream.read_sample()
        sq = raw_sample.get("signal_quality", 200)
        total = sum(raw_sample.get(k, 0.0) for k in BAND_KEYS)

        # Is the headset streaming packets on this connection?
        since_packet = self._real_stream.seconds_since_last_packet
        has_packets = 0 < since_packet < time.monotonic() - self._bt_dropped_at

        if total > 0 and has_packets:  # data on this connection: band values outlive a drop
            self._waiting_for_bt = False
            self._bt_signal_start = None
            self._session_manager.start()  # against the threshold in force, which may have moved
            # Arm the countdown on THIS thread before the next tick()
            # reads it. Deferring it via _on_main let a stalled main
            # thread leave remaining_seconds=0, so the very next tick
            # fired the timer instantly — a 0s "timer-ended" session.
            self._timer_state.start_countdown()
            self._on_main_for_wait(lambda n=name: self._on_session_connected(n))
            logger.info(f"BT device {name} connected, session started")
        elif signal_elapsed > self._BT_SIGNAL_TIMEOUT and not has_packets:
            # No packets — ThinkGear didn't start streaming.
            # Don't try RFCOMM reconnect: closing the socket triggers
            # EBUSY that blocks reconnection for 60+ seconds.
            # The only reliable fix is a headset power cycle.
            self._give_up_bt_wait(name, "No EEG data received.\nCheck battery or restart headset.")
            logger.error("No ThinkGear packets — likely low battery or needs power cycle")
        else:
            # Show signal quality feedback (keep waiting if packets arrive)
            if has_packets:
                # Headset streaming — no timeout, wait for contact
                wait_msg = "Place sensor on forehead..."
            else:
                wait_msg = f"Waiting for EEG data... {signal_remaining}s"
            logger.debug(
                f"BT signal wait: sq={sq} total={total:.0f} "
                f"packets={'yes' if has_packets else 'no'} "
                f"elapsed={signal_elapsed:.0f}s"
            )
            msg = f"Connected to {name}\n{wait_msg}\n{self._sensor_contact(sq)}"
            self._on_main_for_wait(lambda m=msg: self._live_screen.update_overlay(m))

    @staticmethod
    def _sensor_contact(signal_quality: int) -> str:
        """The connect overlay's line on the sensor's contact, from ThinkGear's signal quality (200 = none, 0 = good)."""
        if signal_quality == 200:
            return "Sensor: no contact"
        if signal_quality > 50:
            return f"Sensor: poor (quality {signal_quality})"
        if signal_quality > 0:
            return f"Sensor: fair (quality {signal_quality})"
        return "Sensor: good"

    def _bt_connect_failed(self, name: str) -> None:
        """Tick thread: the connection thread ended with an error."""
        self._abort_bt_wait()
        hint = self._real_stream._last_connect_error or "Check device is on and paired."
        self._on_main_for_wait(lambda n=name, h=hint: (
            self._undo_session_setup(),
            self._live_screen.show_overlay_retry(
                f"Connection to {n} failed.\n{h}"
            ),
        ))
        logger.error("BT connection failed, session aborted")
        self._report_bt_connect_failure(name, hint)

    def _bt_connect_timed_out(self, name: str) -> None:
        """Tick thread: no BT socket within _BT_CONNECT_TIMEOUT."""
        self._abort_bt_wait()
        self._on_main_for_wait(lambda n=name: (
            self._undo_session_setup(),
            self._live_screen.show_overlay_retry(
                f"Connection to {n} timed out.\n"
                "Make sure the device is turned on\nand in range."
            ),
        ))
        logger.error("BT connection timed out")

    def _update_tick(self, dt: float) -> None:
        """Main 2 Hz processing loop.

        Runs on the background SessionTick thread.  All Kivy widget calls are
        dispatched via _on_main so they execute on the main thread.  Audio,
        metrics compute, and DB writes are thread-safe and stay direct.
        """
        if getattr(self, '_waiting_for_bt', False):
            self._handle_bt_wait()
            return

        if self._session_manager.state != SessionState.RUNNING:
            return

        if self._end_at_max_duration():
            return
        self._follow_headset_link()
        self._check_stale_data()

        raw_sample = self._eeg_stream.read_sample()
        metrics = self._metrics_engine.process_sample(raw_sample)
        self._warn_from_sample(raw_sample)
        self._tick_count = getattr(self, '_tick_count', 0) + 1
        self._log_tick(raw_sample, metrics)

        self._formulas.evaluate_into(metrics, lambda: self._eval_formula_vars(raw_sample, metrics))

        # Program vs simple is what the session started as, not the Settings toggle (editable mid-session).
        # The drive key is resolved once: the tick scores and sounds the same metric.
        if self._program_run.active:
            self._program_run.tick(metrics, raw_sample)
            drive_key, scored = self._audio_drive_key(), None
        else:
            drive_key = scored = self._score_on_drive_key()

        # Merge raw + computed for full storage; a pending marker is in the row before a checkpoint can write it.
        full_record = {**raw_sample, **metrics}
        marker_pending = self._pending_marker
        if marker_pending:
            self._pending_marker = False
            full_record["marker"] = 1
        target = self._recorder.record(metrics, full_record)
        if target is None:  # the session paused or stopped while this tick was read: it isn't part of it
            self._pending_marker |= marker_pending  # the marker goes on the next recorded tick
            return

        # Audio is thread-safe — update directly
        self._audio.update(metrics.get(drive_key, 0))
        if self._tick_count > 10:
            self._audio.update_sinking(metrics.get("sinking", 0))
            self._audio.update_subtle_distraction(metrics.get("subtle_distraction", 0))

        self._mirror.record(metrics, target, raw_sample)  # kept even while the screen is locked
        self._show_tick(metrics, raw_sample, target, marker_pending, scored)

        # Timer countdown — tick() is pure counter, no UI
        if self._timer_state.tick(APP.UPDATE_FREQUENCY):
            self._end_by_timer()
            return

        self._recorder.flush_tick()  # DB opened with check_same_thread=False

    def _end_at_max_duration(self) -> bool:
        """Tick thread: stop and save a session that reached the recording limit; True if it did."""
        if self._session_manager.elapsed_seconds < APP.SESSION_MAX_SECONDS:
            return False
        logger.info(f"Session reached max duration ({APP.SESSION_MAX_SECONDS}s), auto-stopping")
        self._audio.play_disconnect_alert()
        limit_msg = (
            f"Session recording limit reached ({APP.SESSION_MAX_SECONDS // 3600}h). "
            "Session saved. Start a new one to continue."
        )
        self._on_main(lambda m=limit_msg: self._live_screen.show_alert(m))
        self._on_main(lambda: self._stop_and_save())
        return True

    def _follow_headset_link(self) -> None:
        """Tick thread: the headset's link coming up (Settings shows it) and dropping during a session (the Session
        screen shows it reconnecting, with the disconnect alert)."""
        if (not self._bt_connected_notified
                and not APP.USE_MOCK_DEVICE
                and self._real_stream.is_connected):
            self._bt_connected_notified = True
            name = self._headset.name()
            self._on_main(lambda n=name: self._settings_screen.device.update_device_status(True, name=n))
            logger.info(f"Settings updated: {name} connected")

        if (not APP.USE_MOCK_DEVICE
                and self._bt_connected_notified
                and not self._real_stream.is_connected):
            self._bt_connected_notified = False
            name = self._headset.name()
            self._on_main(lambda n=name: self._live_screen.update_device_status(
                False, device_name=n, connecting=True
            ))
            self._audio.play_disconnect_alert()
            logger.warning(f"BT device {name} disconnected during session")

    def _warn_from_sample(self, raw_sample: dict) -> None:
        """Tick thread: a low headset battery and power-line noise, each warned about once."""
        # Low battery warning (ThinkGear reports 0-127, warn below ~20%)
        battery = raw_sample.get("battery", -1)
        if battery != -1 and battery < 25 and not getattr(self, '_low_battery_warned', False):
            self._low_battery_warned = True
            pct = int(battery / 127 * 100)
            bat_msg = f"Low headset battery ({pct}%)."
            self._on_main(lambda m=bat_msg: self._live_screen.show_alert(m))
            logger.warning(f"Low headset battery: {battery}/127 ({pct}%)")

        # Feed raw waveform to power line noise detector
        detector = getattr(self, '_noise_detector', None)
        if detector and not detector.ready():
            waveform = raw_sample.get("raw_eeg_waveform", [])
            if waveform:
                detector.feed(waveform)
            if detector.ready():
                detected, freq = detector.result()
                if detected:
                    noise_msg = (
                        f"Warning: {freq} Hz power line noise detected. "
                        f"Check notch filter setting or move away from electrical equipment."
                    )
                    self._on_main(lambda m=noise_msg: self._live_screen.show_alert(m))
                    logger.warning(f"Power line noise detected: {freq} Hz")

    def _log_tick(self, raw_sample: dict, metrics: dict) -> None:
        """Log the raw sample and the metrics every 10 ticks (~5s at 2Hz)."""
        if self._tick_count % 10 != 0:
            return
        bands = {k: f"{raw_sample.get(k, 0):.0f}" for k in BAND_KEYS}
        logger.debug(f"Raw sample #{self._tick_count}: {bands}")
        native_med = raw_sample.get("meditation", -1)
        bat = raw_sample.get("battery", -1)
        bat_str = f" bat={bat}/127" if bat >= 0 else ""
        logger.debug(f"Metrics: med={metrics.get('meditation_score', 0):.0f} "
                     f"sham={metrics.get('shamatha_score', 0):.0f} "
                     f"sink={metrics.get('sinking', 0):.0f} "
                     f"dist={metrics.get('distraction', 0):.0f} "
                     f"native_med={native_med:.0f}{bat_str}")

    def _show_tick(self, metrics: dict, raw_sample: dict, target: float, marker_pending: bool,
                   scored: str | None) -> None:
        """Tick thread: queue the tick's Session screen update for the main thread, unless the screen is locked."""
        elapsed_fmt = self._session_manager.elapsed_formatted

        # Debounced shamatha-zone crossing (tick thread) — only the change is
        # dispatched, so the chip can't restyle every tick.
        sham_prev = self._shamatha_active
        self._shamatha_active, self._shamatha_streak = self._shamatha_transition(
            sham_prev,
            metrics.get("shamatha_score", 0.0) >= self._shamatha_threshold,
            self._shamatha_streak,
        )
        sham_changed = self._shamatha_active != sham_prev

        def _ui_update(
            m=metrics, rs=raw_sample, ef=elapsed_fmt, mp=marker_pending,
            sa=self._shamatha_active, sc=sham_changed, sk=self._scored_mark(scored), tg=target,
        ) -> None:
            self._live_screen.graph.add_point(m, threshold=tg)
            self._live_screen.update_stats(m)
            self._live_screen.update_state(m.get("state", "Neutral"))
            if sc:
                self._live_screen.set_shamatha(sa)
            if sk is not None:
                self._live_screen.set_training_series(sk)
            self._live_screen.update_timer(ef)
            self._live_screen.add_raw_sample(rs)
            if mp:
                self._live_screen.graph.add_marker()
                self._live_screen.raw_graph.add_marker()
                self._live_screen.band_graph.add_marker()

        # Skip per-tick UI work while the app is paused (Android screen
        # locked). Otherwise N minutes locked at 2 Hz queues ~120·N Clock
        # callbacks — each doing a full graph redraw — which flood the
        # main loop on resume and previously caused a black-screen freeze
        # severe enough to require force-closing the app.
        if not self._is_paused:
            self._on_main(_ui_update)

    def _end_by_timer(self) -> None:
        """Tick thread: the timer expired; save the session, silence it, end the tick, ring the gong."""
        logger.info("Timer expired, auto-stopping session")
        # Persist FIRST, before any audio teardown: the session must be saved even with the screen locked, and
        # MediaPlayer.release() on this thread waits on the main Looper, which is paused during a lock.
        stats = self._persist_session_data(reason="timer")
        session_id = self._recorder.session_id
        # Silence the noise with a non-blocking volume→0 (setVolume is a
        # direct native call, safe from this thread even while locked).
        # The real stop()/release() teardown is deferred to the main
        # thread below, where the Looper is live and release() won't hang.
        self._audio.mute()
        # Stop the loop now (safe from this thread); also ends `running`, so idle isn't "live".
        self._ticker.stop()

        def _finish_on_main(_dt=None):
            self._audio.stop()  # full noise teardown on the main thread
            self._finalize_stop_ui(stats, session_id)
        self._on_main(_finish_on_main)
        # Ring the gong LAST, on this thread, so it sounds at the timer end
        # even with the screen locked: it routes through a MediaPlayer
        # (USAGE_MEDIA), which plays through lock — SoundLoader is silenced
        # while locked. Only create/start runs here (release is deferred to
        # the main thread via stop_timer_bell). Done last on purpose: the
        # save, mute, and summary dispatch above are all complete, so even
        # if MediaPlayer setup were to block during lock, nothing critical
        # is lost.
        self._audio.play_timer_sound(self._timer_state.custom_sound_path)

    def _on_key_down(self, window, key, scancode, codepoint, modifiers) -> bool:
        """Handle keyboard hotkey for marker."""
        # Don't capture keys while settings hotkey picker is active
        if self._settings_screen.display._waiting_for_hotkey:
            return False
        hotkey = self._settings_screen.display.marker_hotkey
        if not hotkey:
            return False
        pressed = codepoint if codepoint else str(key)
        if pressed == hotkey:
            self._on_marker()
            return True
        return False

    def _on_keyboard(self, window, key, scancode=0, codepoint=None,
                     modifiers=None) -> bool:
        """Android hardware back / Esc (key 27): close overlays, navigate back to
        Session, or double-tap to exit. Returns True to consume the key so Kivy's
        default exit-on-escape never fires."""
        if key != 27:
            return False
        # The mandatory user-selection gate: back/Esc never falls through INTO the
        # app (covers the pre-popup schedule window too), but double-press exits —
        # a fresh-install user who declines to create a profile must be able to leave.
        if self._gate_active():
            return self._handle_gate_back()
        # An open Popup/ModalView dismisses itself on escape — let it.
        if any(isinstance(c, ModalView) for c in Window.children):
            return False
        # Fullscreen graph overlay → close it (it's not a ModalView).
        if self._fullscreen.close():
            return True
        current = self._sm.current
        if current == "diary":
            self._on_diary_back()
            return True
        if current != "live_session":
            self._switch_screen("live_session")
            return True
        # Root (Session): require two presses within 2s to exit.
        return self._exit_on_second_back()

    _leaving = False  # set while _flush_on_leave runs: nothing the app draws is seen any more

    def _toast(self, message: str) -> None:
        """Short non-blocking confirmation on the theme's modal panel, above any popup. While the app is leaving it is
        the native Android toast instead, the one thing still seen then."""
        if self._leaving and hasattr(sys, "getandroidapilevel"):
            self._android_toast(message)
            return
        lbl = ThemedLabel(text=message, font_size=F.BODY, color=C.TEXT, size_hint=(None, None),
                          padding=(dp(16), dp(10)))
        lbl.texture_update()
        lbl.size = lbl.texture_size
        lbl.pos = ((Window.width - lbl.width) / 2, Window.height * 0.12)
        paint_panel(lbl)
        Window.add_widget(lbl)
        fade = Animation(opacity=0, duration=0.4)
        fade.bind(on_complete=lambda *_a: Window.remove_widget(lbl))
        Clock.schedule_once(lambda _dt: fade.start(lbl), 1.6)

    def _android_toast(self, message: str) -> None:
        """Short Android toast; no-op (logged) off Android."""
        if not hasattr(sys, "getandroidapilevel"):
            logger.debug(f"toast: {message}")
            return
        try:
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _show():
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Toast = autoclass("android.widget.Toast")
                Toast.makeText(
                    PythonActivity.mActivity, java_string(message), Toast.LENGTH_SHORT
                ).show()
            _show()
        except Exception as e:
            logger.warning(f"Toast failed: {e}")

    def _on_marker(self, *args) -> None:
        """Place a marker at the current position in the session."""
        if self._session_manager.state == SessionState.RUNNING:
            self._pending_marker = True
            logger.info("Marker placed")

    def _on_threshold_change(self, value: int) -> None:
        if self._mirror.metrics and not self._session_pipeline_live():
            self._clear_live_display()  # the last session's line is not the threshold the next one runs against
        # A drag is one change of the threshold in force, at the value it settles on, not one per slider step.
        self._after_settle("apply_threshold", lambda: self._apply_threshold(self._settings_screen.threshold))
        self._persist_user_setting_later("threshold")
        logger.debug(f"Threshold changed to {value}")

    def _program_owns_threshold(self) -> bool:
        """A running program's segments own its targets: the Settings threshold waits for the next session."""
        return self._program_run.active and self._session_pipeline_live()

    def _refuse_program_threshold(self) -> bool:
        """A touch on the threshold controls a program locked: True, after saying why, until the session ends."""
        return self._refused_while_session_runs("changing the threshold", why="This program sets its own targets.")

    def _apply_threshold(self, value: int) -> None:
        """Put the Settings threshold in force, unless a running program owns it (a profile reload, a late settle)."""
        if not self._program_owns_threshold():
            self._put_threshold_in_force(value)

    def _clear_live_display(self) -> None:
        """Empty the Session screen of its session: graphs, their mirrors, threshold steps and the readout."""
        self._mirror.clear()
        self._live_screen.graph.clear_data()
        self._live_screen.raw_graph.clear_data()
        self._live_screen.band_graph.clear_data()
        self._live_screen.graph.set_threshold_steps(None)  # each tick's target steps it, a program's too
        self._live_screen.clear_readout()

    def _put_threshold_in_force(self, value: int) -> None:
        """The sound, the scoring, the SHAMATHA pill and the engine together; a session start calls it directly."""
        self._metrics_engine.meditation_threshold = value
        self._audio.set_threshold(value)
        self._shamatha_threshold = value
        self._session_manager.set_threshold(value)  # also what a session waiting for the headset starts with
        self._live_screen.graph.set_threshold(float(value))  # drawn until ticks step the line

    def _test_audio_sources(self) -> tuple[dict, str, str]:
        """(prepared sources, below id, reward id) for the Test button — both the
        selected below feedback source and the reward source (so Crickets etc. preview)."""
        gid = self._global_feedback_id()
        sources = {gid: self._source_spec(gid)}
        reward_id = self._reward_id()
        if reward_id:
            sources[reward_id] = self._source_spec(reward_id)
        return sources, gid, reward_id

    def _on_test_audio(self) -> None:
        """Sample the selected feedback + reward sources, then the alert channels."""
        sources, gid, reward_id = self._test_audio_sources()
        self._warn_missing_sound_files(sources, force=True)
        self._audio.prepare_feedback(sources, gid)
        self._audio.test_audio(reward_id)

    def _on_line_width_change(self, width: float) -> None:
        self._live_screen.graph.set_line_width(width)
        self._live_screen.raw_graph.set_line_width(width)
        self._live_screen.band_graph.set_line_width(width)
        self._diary_screen._metrics_graph.set_line_width(width)
        self._diary_screen._raw_eeg_graph.set_line_width(width)
        self._diary_screen._freq_graph.set_line_width(width)
        logger.debug(f"Line width changed to {width}")

    def _on_rotate_screen(self, rotation: int) -> None:
        Window.rotation = rotation
        self._persist_user_setting("rotation")
        logger.info(f"Screen rotation set to {rotation}")

    @staticmethod
    def _baseline_audio_metric(key: str) -> str:
        """The user's persisted audio metric; program-formula slots are program-only
        and must never persist as a baseline (outside a program they read 0 -> max noise)."""
        return "shamatha_score" if (not key or key in PROGRAM_FORMULA_KEYS) else key

    _scored_key: Optional[str] = None  # the series the live legend marks as scored in a simple session

    def _score_on_drive_key(self) -> str:
        """A simple session is scored on the metric that drives the feedback sound (#51), so they can't diverge."""
        key = self._audio_drive_key()
        self._session_manager.set_active_goal(key)
        return key

    def _scored_mark(self, key: Optional[str]) -> Optional[str]:
        """The scored series for the legend to mark this tick: only on a change, and only while the UI is showing (a
        change during a screen lock is picked up by the first tick after it)."""
        if key is None or key == self._scored_key or self._is_paused:
            return None
        self._scored_key = key
        return key

    def _with_score(self, stats: dict) -> dict:
        """Stats to save, with the scored metric's display name; a program session is scored per segment."""
        if not stats:
            return stats
        if self._program_run.active:
            return {**stats, "score_metric_key": "program",
                    "score_metric_name": self._program_run.name or "Program", "avg_score": None}
        key = stats.get("score_metric_key") or self._audio_drive_key()  # no scored tick yet: what it would score
        return {**stats, "score_metric_key": key, "score_metric_name": self._live_screen.graph.series_name(key)}

    def _audio_drive_key(self) -> str:
        """Metric key feeding noise. A running program drives it from the active segment's
        slot; otherwise the user's baseline. Falls back to shamatha when the key would read
        0 (invalid formula slot, or a program slot outside a program)."""
        if self._program_run.active and self._program_run.audio_key:
            key = self._program_run.audio_key
        else:
            key = self._baseline_audio_metric(self._audio_metric_key)
        ev = self._formulas.for_key(key)
        if ev is not None and not ev.is_valid:
            return "shamatha_score"
        return key

    def _on_audio_metric_change(self, key: str) -> None:
        """Switch which metric drives the audio threshold feedback: a running session keeps the one it is scored on
        (#51 scores it on the drive key every tick, so a switch mixed both metrics into one average and streak)."""
        new_key = FORMULA_KEYS[self._audio_formula_index] if key == "custom_formula" else key
        if new_key != self._audio_metric_key and self._scoring_locked("changing the metric it is scored on"):
            self._show_audio_metric()
            return
        self._audio_metric_key = new_key
        self._persist_user_setting("audio_metric")
        logger.info(f"Audio threshold metric changed to: {self._audio_metric_key}")

    def _on_feedback_source_change(self, source: str, path: str) -> None:
        """Apply the global (below-threshold) feedback source chosen in Settings."""
        self._feedback_source = source
        self._feedback_sound_path = (path or "").strip()
        self._persist_user_setting("feedback_source")
        self._persist_user_setting("feedback_sound_path")
        logger.info(f"Feedback source -> {self._feedback_source} {self._feedback_sound_path!r}")

    def _on_reward_source_change(self, source: str, path: str) -> None:
        """Apply the above-threshold reward source chosen in Settings."""
        self._reward_source = source
        self._reward_sound_path = (path or "").strip()
        self._persist_user_setting("reward_source")
        self._persist_user_setting("reward_sound_path")
        logger.info(f"Reward source -> {self._reward_source} {self._reward_sound_path!r}")

    def _on_audio_formula_index(self, idx: int) -> None:
        """Pick which formula slot drives audio. Only rebinds the live key when a
        custom-formula slot is the selected driver — tapping it while another metric
        is selected just remembers the choice for when custom-formula is picked."""
        idx = max(0, min(idx, len(FORMULA_KEYS) - 1))
        if (self._audio_metric_key in FORMULA_KEYS and FORMULA_KEYS[idx] != self._audio_metric_key
                and self._scoring_locked("changing the metric it is scored on")):
            self._show_audio_metric()
            return
        self._audio_formula_index = idx
        if self._audio_metric_key in FORMULA_KEYS:
            # Load derives the index from audio_metric, so persist both or a reload reverts the switch.
            self._audio_metric_key = FORMULA_KEYS[self._audio_formula_index]
            self._persist_user_setting("audio_metric")
        self._persist_user_setting("audio_formula_index")

    def _scoring_locked(self, doing: str) -> bool:
        """True (after telling the user) while a simple session runs: it is scored on the audio control metric (#51)
        until it stops. A program session is scored on its segments' metrics, so the control stays free."""
        return (not self._program_run.active
                and self._refused_while_session_runs(doing))

    def _show_audio_metric(self) -> None:
        """Settings' audio-metric choice and formula-slot buttons show the metric in force."""
        key = self._audio_metric_key
        self._settings_screen.audio_metric = "custom_formula" if key in FORMULA_KEYS else key
        self._settings_screen.audio_formula_index = self._audio_formula_index

    def _on_text_size_change(self, size: float) -> None:
        self._persist_user_setting("text_size")
        logger.info(f"Text size set to {size:g}")

    def _on_line_colours_change(self, name: str) -> None:
        self._persist_user_setting("line_colours")
        logger.info(f"Scored line colours set to {name}")

    def _on_theme_change(self, theme_name: str) -> None:
        """Persist the theme per user; the selector already applied it to C."""
        self._persist_user_setting("theme")
        logger.info(f"Theme changed to: {theme_name}")

    def _confirm_saved_delete(self, kind: str, entries: list[dict], index: int, label: Callable,
                              delete: Callable[[int], None]) -> None:
        """Ask before deleting a saved formula or program, named as its list row names it."""
        if not (0 <= index < len(entries)):
            return
        self._confirm_action(f"Delete {kind}", f"Delete saved {kind} '{label(index, entries[index])}'?", "Delete",
                             lambda: delete(index), ok_color=C.DANGER)

    def _require_user(self, action: str) -> Optional[int]:
        """Return the active uid, or explain why the action can't run and return
        None. Per-user handlers call this instead of a bare silent `return` — the
        hard gate should make None unreachable, this is the defense-in-depth."""
        if self._current_user_id:
            return self._current_user_id
        self._info_popup("No profile selected", f"Select a profile before you can {action}.")
        return None

    def _info_popup(self, title: str, message: str) -> None:
        ok_btn = StyledButton(text="OK", bg_color=C.ACCENT)
        popup = make_message_popup(title, message, [ok_btn])
        ok_btn.bind(on_release=popup.dismiss)
        popup.open()

    def _confirm_action(self, title, message, ok_text, on_ok, ok_color=None, on_cancel=None) -> None:
        """on_cancel runs on every close that isn't OK: Cancel, a tap outside, or Android back."""
        confirm_popup(title, message, ok_text, on_ok, ok_color=ok_color, on_cancel=on_cancel)

    def _on_sinking_alert_toggle(self, active: bool) -> None:
        self._audio.sinking_alert_enabled = active
        self._persist_user_setting("sinking_alert")
        logger.info(f"Sinking alert {'enabled' if active else 'disabled'}")

    def _on_subtle_alert_toggle(self, active: bool) -> None:
        self._audio.subtle_alert_enabled = active
        self._persist_user_setting("subtle_alert")
        logger.info(f"Distraction chime {'enabled' if active else 'disabled'}")

    def _on_disconnect_alert_toggle(self, active: bool) -> None:
        self._audio.disconnect_alert_enabled = active
        self._persist_user_setting("disconnect_alert")
        logger.info(f"Disconnect alert {'enabled' if active else 'disabled'}")

    def _on_timer_sound_change(self, path: str) -> None:
        """Set the custom timer-gong path ("" for the default bell) and persist it."""
        self._timer_state.set_custom_sound_path(path)
        self._persist_user_setting_later("timer_sound")

    def _on_test_timer_sound(self) -> None:
        logger.debug(f"Test timer sound, path='{self._timer_state.custom_sound_path}'")
        self._warn_missing_sound_files({}, self._timer_state.custom_sound_path, force=True)
        self._audio.play_timer_sound(self._timer_state.custom_sound_path)
        # When the file ends naturally, flip the Settings test button back
        # from "Stop" to "Test". Sound objects are SoundLoader-backed and
        # expose an on_stop event; binding here is best-effort because not
        # every audio backend fires it reliably.
        snd = self._audio._bell_sound
        if snd is None:
            return

        def _on_natural_end(*_):
            try:
                Clock.schedule_once(
                    lambda dt: self._settings_screen.timer.notify_timer_sound_test_ended(),
                    0,
                )
            except Exception:
                pass

        try:
            snd.bind(on_stop=_on_natural_end)
        except Exception:
            pass

    def _on_stop_test_timer_sound(self) -> None:
        logger.debug("Stop timer test sound")
        self._audio.stop_timer_bell()

    def _report_bt_connect_failure(self, device_name: str, hint: str) -> None:
        """Fire a soft-error dialog for a failed BT connect (cooldown-gated).

        The retry overlay already tells the user *something* went wrong; this
        adds a copy-pasteable technical report so they can forward it when
        the friendly hint isn't enough.
        """

        addr = self._real_stream._device_address or "(unset)"
        last_err = self._real_stream._last_connect_error or "(none)"
        detail = (
            f"Device: {device_name} ({addr})\n"
            f"Hint shown to user: {hint}\n"
            f"Stream last_connect_error: {last_err}\n"
        )
        report_soft_error("bt_connect_failed", detail, app=self)

    _detail_load: int = 0  # the session-detail open in progress; a result for an earlier one is dropped

    def _on_session_select(self, session_id: int) -> None:
        """Open the session detail at once (#59): title, stats and notes from the row History holds, so they can be read
        and edited at once; the band totals and graphs load on a worker and fill in, one section per frame."""
        session = self._history_screen.session_by_id(session_id)
        if session is None:  # not in History's list: nothing was tapped
            logger.warning(f"Session detail: session {session_id} isn't listed")
            return
        self._detail_load += 1
        token = self._detail_load
        d = self._diary_screen
        with timed("diary.open"):
            d.set_session_formulas({}, recorded_formulas(session)[1])  # the legend's names from the first frame
            d.show_session_detail(session)
            d.set_metrics_threshold(float(session.get("threshold_used", 50)))
            d.set_program(session.get("session_program", ""))
            bv = {}
            if self._current_user_id:
                bv = self._db.get_user_json_setting(self._current_user_id, "band_breakdown_view", {}) or {}
            d.set_band_view_state(bv.get("mode", "detailed"), bv.get("sort", "band"), bool(bv.get("desc", False)))
            self._session_detail_back = self._sm.current
            self._sm.current = "diary"
        threading.Thread(target=self._load_session_detail, args=(token, session_id, session), daemon=True,
                         name="DiaryLoad").start()

    def _load_session_detail(self, token: int, session_id: int, session: dict) -> None:
        """Worker: the band totals (one query) first, then the metric rows, read once for the graphs and the formula
        replay, built into each graph's data off the main thread; each result goes to _fill_detail as it is ready."""
        d = self._diary_screen
        try:
            with timed("diary.band_totals"):
                totals = self._db.get_session_band_totals(session_id)
            self._on_main(lambda: self._fill_detail(token, [lambda: d.set_band_totals(totals)]))
            with timed("diary.get_metrics"):
                rows = self._db.get_session_metrics(session_id)
            with timed("diary.compute_formulas"):
                series, names = self._compute_session_formulas(session_id, session, rows)
            with timed("diary.graph_data"):
                data = detail_graph_data(rows, series)
        except Exception as e:  # any failure: the sections say so, never "Loading…" for good
            logger.exception(f"Session detail load failed for session {session_id}")

            def failed(err=e) -> None:
                d.show_load_failed()
                report_soft_error("session_detail_load_failed", f"Session {session_id}'s graphs: {err}")

            self._on_main(lambda: self._fill_detail(token, [failed]))
            return

        def fill(section: str) -> None:
            if section == "metrics":
                d.set_session_formulas(series, names)  # the formula lines' names, before their graph
            d.fill_graph(section, data)

        try:
            ticks = scored_ticks(session, rows, series,
                                 lambda evaluators: self._db.recompute_formula_series(session_id, evaluators, rows))
            what_if = lambda: d.set_what_if(ticks, session)
        except Exception:  # broad on purpose: a row it can't score must not take the graphs down with it
            logger.exception(f"What-if scoring failed for session {session_id}")
            what_if = d.show_what_if_failed

        self._on_main(lambda: self._fill_detail(token, [*(lambda s=s: fill(s) for s in d.graph_fill_order()),
                                                        what_if]))

    def _fill_detail(self, token: int, steps: list) -> None:
        """Run one step per frame, so no frame holds them all, while this open is the detail on screen: after Back,
        another tab or another session's open, the rest is dropped."""
        if token != self._detail_load or self._sm.current != "diary" or not steps:
            return
        steps[0]()
        if len(steps) > 1:
            Clock.schedule_once(lambda dt: self._fill_detail(token, steps[1:]), 0)  # 0 from a callback: next frame

    def _persist_band_view(self, mode: str, sort_by: str, descending: bool) -> None:
        """Persist the diary band-table view (mode/sort) per user."""
        if not self._current_user_id:
            return  # silent-ok: view-pref persistence; no concrete user (All-Users) = nothing to save
        self._db.set_user_json_setting(
            self._current_user_id, "band_breakdown_view",
            {"mode": mode, "sort": sort_by, "desc": descending},
        )

    def _compute_session_formulas(self, session_id: int, session: dict,
                                  rows: list[dict] | None = None) -> tuple[dict, dict]:
        """Recompute the session's recorded formula series + names from its band powers, over `rows` when already
        read. Pure DB + compute, no Kivy — safe to call off the main thread."""
        evaluators, names = recorded_formulas(session)
        series = self._db.recompute_formula_series(session_id, evaluators, rows) if evaluators else {}
        return series, names

    def _inject_session_formulas(self, session_id: int, session: dict) -> None:
        """Recompute + apply the session's recorded formulas (synchronous)."""
        series, names = self._compute_session_formulas(session_id, session)
        self._diary_screen.set_session_formulas(series, names)

    def _on_diary_back(self) -> None:
        """Return from diary detail to previous screen (usually history)."""
        back = getattr(self, "_session_detail_back", "history")
        self._switch_screen(back)

    def _on_save_notes(self, session_id: int, notes: str | None = None, tags: str | None = None,
                       mood: int | None = None) -> bool:
        return self._save_session_notes(session_id, notes=notes, tags=tags, mood=mood)

    def _delete_sessions(self, session_ids: list[int], on_done: Optional[Callable[[bool], None]] = None) -> None:
        """The one session-delete path (a History row, the selection, the session-end card): one transaction on a worker
        thread, then History drops the rows in place and the end card closes if it shows one of them. on_done(True)
        once deleted; on_done(False) when refused or failed, with nothing deleted."""
        ids = list(session_ids)
        done = on_done or (lambda _ok: None)
        if self._session_pipeline_live() and self._recorder.session_id in ids:
            # Its row is in History after the first checkpoint; its next checkpoints would write data for no session.
            self._info_popup("Session in progress",
                             "Stop the session first: a running session can't be deleted. Nothing was deleted.")
            done(False)
            return
        # Modal at once, so a tap can't reach the rows or the end card being deleted; painted only if it takes a while.
        self.show_loading(f"Deleting {format_count(len(ids), 'session')}\u2026", delay=0.15)
        t0 = time.monotonic()

        def _finish(error) -> None:
            self.hide_loading()
            if error is not None:
                report_soft_error("session_delete_failed",
                                  f"{format_count(len(ids), 'session')} could not be deleted: {error}")
                done(False)
                return
            logger.info(f"Deleted {format_count(len(ids), 'session')} {ids} in {(time.monotonic() - t0) * 1000:.0f} ms")
            if self._recorder.session_id in ids or self._live_screen.summary_session_id in ids:
                self._drop_shown_session(keep_notes=False)  # the Session screen shows a session that's gone
            self._history_screen.remove_sessions(ids)
            done(True)

        def _worker() -> None:
            try:
                self._db.delete_sessions(ids)
            except sqlite3.Error as e:
                logger.exception(f"Deleting sessions {ids} failed")
                self._on_main(lambda err=e: _finish(err))
                return
            self._on_main(lambda: _finish(None))

        threading.Thread(target=_worker, daemon=True, name="SessionDelete").start()

    def _on_rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session; its History row already shows the new name."""
        self._db.rename_session(session_id, new_name)
        logger.info(f"Session {session_id} renamed to '{new_name}'")

    def _on_export_csv(self, session_id: int, path: Optional[str] = None) -> Optional[str]:
        """Export session data as CSV file. Returns file path or None."""
        csv_data = self._db.export_session_csv(
            session_id, custom_formula=self._formulas.evaluators[0]
        )
        if not csv_data:
            return None
        if not path:
            export_dir = os.path.dirname(self._db._db_path)
            path = os.path.join(export_dir, f"session_{session_id}.csv")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(csv_data)
        logger.info(f"Session {session_id} exported to {path}")
        return path

    def _on_export_sessions_csv(self, session_ids: list) -> None:
        """Bulk-export selected sessions as one ZIP of per-session CSVs (issue #7).
        Runs off the main thread behind the loading spinner; delivers via the shared
        copy_to_documents path (Documents on Android, a Documents folder on desktop)."""
        if not session_ids:
            return
        self.show_loading(f"Exporting {format_count(len(session_ids), 'session')}…")

        def _worker():
            try:
                mapping = {}
                for sid in session_ids:
                    csv = self._db.export_session_csv(sid, custom_formula=self._formulas.evaluators[0])
                    if csv:
                        mapping[sid] = csv
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                fname = f"sessions_{ts}.zip"
                tmp_zip = os.path.join(os.path.dirname(self._db._db_path), fname)
                n = build_sessions_zip(tmp_zip, mapping)
                if n == 0:
                    self._on_main(lambda: (self.hide_loading(), report_soft_error(
                        "export_empty", "No data to export in the selected sessions.", app=self)))
                    return
                dest = tmp_zip
                try:
                    from app.storage.android_share import copy_to_documents
                    shared = copy_to_documents(tmp_zip, display_name=fname)
                    if shared:
                        dest = shared
                except Exception:
                    logger.exception("copy_to_documents failed for bulk export")
                self._on_main(lambda: self._finish_bulk_export(n, dest))
            except Exception:
                logger.exception("Bulk CSV export failed")
                self._on_main(lambda: (self.hide_loading(), report_soft_error(
                    "export_failed", "Bulk CSV export failed — see logs.", app=self)))

        threading.Thread(target=_worker, daemon=True, name="BulkCSVExport").start()

    def _finish_bulk_export(self, count: int, dest: str) -> None:
        self.hide_loading()
        self._history_screen.set_select_mode(False)
        self._info_popup("Export complete", f"Exported {format_count(count, 'session')} to:\n{dest}")

    # Each Start and each ending (_undo_session_setup) moves it on: a callback queued for an earlier attempt (the device
    # scan's result, the BT wait's UI and audio) sees it has changed and does nothing.
    _start_attempt: int = 0
    _wait_attempt: int = 0  # the attempt the BT wait belongs to, taken on the main thread when it begins
    _history_dirty: bool = True
    _history_view: Optional[tuple] = None  # (profile, all-users) History last loaded; a day filter survives only that

    def _refresh_history(self, force: bool = False) -> None:
        if not force and not self._history_dirty:
            return
        with timed("history.get_all_sessions"):
            sessions = sessions_for_view(self._db, self._current_user_id, self._view_all_users)
        if self._session_pipeline_live():
            # The running session's row exists from its first checkpoint, with stats as of that checkpoint: History
            # lists finished sessions only, and the ending marks History dirty so it appears then.
            sessions = [s for s in sessions if s.get("id") != self._recorder.session_id]
        view = (self._current_user_id, self._view_all_users)
        self._history_screen.load_sessions(sessions, keep_filter=view == self._history_view)
        self._history_view = view
        self._history_dirty = False

    def _mark_history_dirty(self) -> None:
        self._history_dirty = True

    def _on_user_switch(self, user_id: Optional[int]) -> None:
        """Switch the active user profile."""
        # The running session owns the loaded settings and saves under its own profile.
        if user_id != self._current_user_id and self._refused_while_session_runs("switching profiles"):
            self._refresh_profile()  # snap the picker back to the active profile
            return
        # Save current user's settings before switching
        self._save_user_settings()
        if user_id:
            user = self._db.get_user(user_id)
            name = user["name"] if user else "Unknown"
            self._activate_user(user_id)
            logger.info(f"Switched to user: {name} (id={user_id})")
        else:
            self._current_user_id = None
            self._view_all_users = True  # deliberate All-Users view
            logger.info("Switched to: All Users")
        self._mark_history_dirty()
        self._refresh_profile()

    def _on_history_view_mode_change(self, mode: str) -> None:
        """Persist the user's preferred History view layout."""
        if not self._current_user_id:
            return  # silent-ok: pref persistence; view already changed, no user to save to
        self._db.set_user_setting(self._current_user_id, "history_view_mode", mode)

    def _count_sessions_for_user(self, user_id: int) -> int:
        return len(self._db.get_all_sessions(user_id=user_id))

    # --- Data Backup (app/ui/backup_flow.py) ---

    def _current_user_name(self) -> str | None:
        user = self._db.get_user(self._current_user_id) if self._current_user_id else None
        return user["name"] if user else None

    def _on_db_replaced(self) -> None:
        """A restore replaced the database file: on_stop/on_pause must not flush settings over it; relaunch."""
        self._restoring = True
        self._show_relaunch_popup()

    def _show_relaunch_popup(self) -> None:
        """Blocking 'please relaunch' popup after a restore. Also re-shown from
        on_resume if Android resumed the process instead of killing it — the DB
        is shut down at that point, so the only way forward is a real relaunch."""
        if getattr(self, "_relaunch_popup", None) is not None:
            return
        ok = StyledButton(text="OK", bg_color=C.ACCENT)
        popup = make_message_popup("Restore complete", "Database restored.\n\nThe app will now exit — please relaunch.",
                                   [ok], width_hint=0.8, auto_dismiss=False)
        self._relaunch_popup = popup

        def _quit(*_a):
            self._relaunch_popup = None
            popup.dismiss()
            App.get_running_app().stop()

        ok.bind(on_release=_quit)
        popup.open()

    def _on_pick_existing_user(self, user_id: int) -> None:
        """First-run popup: an existing profile picked, activated as it is (its own headset and mode)."""
        if not self._db.get_user(user_id):
            logger.warning(f"_on_pick_existing_user: user {user_id} not found")
            return
        self._activate_user(user_id)
        self._finish_first_run(f"user {user_id} picked")

    def _on_user_create(self, name: str) -> None:
        """Create a new user and refresh the profile list.

        Routes UserExistsError to the active picker form (Settings) for
        inline duplicate handling.
        """

        try:
            self._db.create_user(name)
        except UserExistsError as e:
            form = getattr(self._settings_screen, "_user_picker_form", None)
            if form is not None:
                form.show_duplicate_error(user_id=e.user_id, name=e.name)
            return
        except Exception as e:
            report_soft_error(
                "user_create_failed", f"Could not create user '{name}': {e}",
            )
            return
        self._refresh_profile()

    def _on_user_delete(self, user_id: int) -> None:
        """Delete a user profile. Deleting the ACTIVE profile drops the app into
        the no-user state, so re-enter the hard gate instead of leaving the app
        usable with nothing selected."""
        deleted_active = self._current_user_id == user_id
        if deleted_active and self._session_pipeline_live():
            # Discard the running (or connecting) session — otherwise the tick
            # thread keeps running and writes an orphaned session, and saving it
            # under a profile that's about to be deleted just orphans it anyway.
            self._discard_running_session()
        self._db.delete_user(user_id)
        if user_id == self._live_display_uid:  # its session went with it: the card has nothing left to save
            self._drop_shown_session(keep_notes=False)
        self._mark_history_dirty()  # its sessions are gone (the All-Users view lists them)
        remaining = self._db.get_all_users()
        # Re-enter the gate when no usable active user is left: the active profile
        # was deleted, OR the last profile was removed while in the All-Users view
        # (which would otherwise leave the app usable with zero users, no gate).
        if deleted_active or not remaining:
            self._current_user_id = None
            self._view_all_users = False
            self._refresh_profile()
            self._program_settings.refresh_saved()  # drop the deleted user's programs from the UI now
            self._open_user_gate(0)
        else:
            self._refresh_profile()

    def _refresh_profile(self) -> None:
        self._settings_screen.populate_users(self._db.get_all_users(), self._current_user_id)

    def _build_settings_store(self) -> None:
        """Build the settings registry; call once in build() before any user load, as get() snapshots defaults."""
        ss = self._settings_screen
        ls = self._live_screen
        settings: list[Setting] = []

        def set_timer_enabled(v):
            self._timer_state.set_enabled(v); ss.timer.timer_enabled = v

        def set_timer_minutes(v):
            self._timer_state.set_duration(v); ss.timer.timer_minutes = v

        def set_timer_sound(v):
            self._timer_state.set_custom_sound_path(v); ss.timer.timer_sound_path = v

        def set_sinking(v):
            self._audio.sinking_alert_enabled = v; ss.audio._sinking_alert_cb.active = v

        def set_subtle(v):
            self._audio.subtle_alert_enabled = v; ss.audio._subtle_alert_cb.active = v

        def set_disconnect(v):
            self._audio.disconnect_alert_enabled = v; ss.audio._disconnect_alert_cb.active = v

        def set_threshold(v):
            ss.threshold = v
            self._apply_threshold(v)

        def set_use_mock(v):
            APP.USE_MOCK_DEVICE = v; ss.device._device_mode_cb.active = v

        def set_line_width(v):
            ss.display._line_width_slider.value = v; self._on_line_width_change(v)

        def set_rotation(v):
            ss.display._current_rotation = v
            ss.display._rotate_btn.text = f"Rotate Screen ({v}°)"
            Window.rotation = v

        def set_audio_index(v):
            self._audio_formula_index = max(0, min(int(v), len(FORMULA_KEYS) - 1))

        def set_audio_metric(v):
            v = self._baseline_audio_metric(v)  # heal a leaked program slot
            self._audio_metric_key = v
            if v in FORMULA_KEYS:
                self._audio_formula_index = FORMULA_KEYS.index(v)
            self._show_audio_metric()

        def set_feedback_source(v):
            self._feedback_source = v; ss.audio.set_feedback_source(v, self._feedback_sound_path)

        def set_feedback_path(v):
            self._feedback_sound_path = v; ss.audio.set_feedback_source(self._feedback_source, v)

        def set_reward_source(v):
            self._reward_source = v; ss.audio.set_reward_source(v, self._reward_sound_path)

        def set_reward_path(v):
            self._reward_sound_path = v; ss.audio.set_reward_source(self._reward_source, v)

        def add(key, codec, get, set_):
            settings.append(Setting(key, get(), codec[0], codec[1], get, set_))

        add("timer_enabled", BOOL, lambda: ss.timer.timer_enabled, set_timer_enabled)
        add("timer_minutes", INT, lambda: ss.timer.timer_minutes, set_timer_minutes)
        add("timer_sound", STR, lambda: ss.timer.timer_sound_path, set_timer_sound)
        add("sinking_alert", BOOL, lambda: self._audio.sinking_alert_enabled, set_sinking)
        hs = self._history_screen
        add("history_chart_collapsed", BOOL, lambda: hs.chart_collapsed, hs.set_chart_collapsed)
        what_if = self._diary_screen.what_if
        add("what_if_collapsed", BOOL, lambda: what_if.collapsed, what_if.set_collapsed)
        ds = self._diary_screen
        add("band_power_collapsed", BOOL, lambda: ds.band_collapsed, ds.set_band_collapsed)
        add("subtle_alert", BOOL, lambda: self._audio.subtle_alert_enabled, set_subtle)
        add("disconnect_alert", BOOL, lambda: self._audio.disconnect_alert_enabled, set_disconnect)
        add("threshold", INT, lambda: int(ss.threshold), set_threshold)
        add("use_mock", BOOL, lambda: APP.USE_MOCK_DEVICE, set_use_mock)
        add("line_width", FLOAT, lambda: ss.display._line_width_slider.value, set_line_width)
        add("rotation", INT, lambda: ss.display._current_rotation, set_rotation)
        add("graph_zoom_seconds", FLOAT, self._saved_zoom_seconds, self._apply_saved_zoom)
        # audio_formula_index BEFORE audio_metric: metric reconciles the index when it's a slot.
        add("audio_formula_index", INT, lambda: self._audio_formula_index, set_audio_index)
        add("audio_metric", STR,
            lambda: self._baseline_audio_metric(self._audio_metric_key), set_audio_metric)
        add("feedback_source", STR, lambda: self._feedback_source, set_feedback_source)
        add("feedback_sound_path", STR, lambda: self._feedback_sound_path, set_feedback_path)
        add("reward_source", STR, lambda: self._reward_source, set_reward_source)
        add("reward_sound_path", STR, lambda: self._reward_sound_path, set_reward_path)
        add("marker_hotkey", STR, lambda: ss.display.marker_hotkey,
            lambda v: setattr(ss, "marker_hotkey", v))
        add("stats_view_mode", STR, lambda: getattr(ls, "_stats_mode", "live"),
            self._apply_stats_mode)
        # Its default is the seed, not the startup profile's theme the UI was built in.
        settings.append(theme_setting(self._theme_seed))
        settings.append(text_size_setting())
        settings.append(line_colours_setting())

        self._settings_store = SettingsStore(self._db, settings)

    def _apply_stats_mode(self, mode: str) -> None:
        self._live_screen.set_stats_mode(mode)

    def _save_user_settings(self) -> None:
        """Persist current UI settings for the active user."""
        uid = self._current_user_id
        if not uid:
            return  # silent-ok: batch persistence; no active user = nothing to save
        try:
            self._settings_store.save(uid)          # all scalar per-user settings + theme
            self._formula_settings.persist(uid)
            self._program_settings.persist(uid)
            self._graph_series.persist_all()  # the on-graph picker is the source of truth
        except sqlite3.Error as e:
            # Runs from UI callbacks (backup, pause, profile switch): report, don't crash.
            report_soft_error("settings_save_failed", f"Couldn't save your settings: {e}", app=self)
            return
        logger.debug(f"Saved settings for user {uid}")

    def _load_user_settings(self, user_id: int) -> None:
        """Restore persisted settings for a user."""
        self._loading_settings = True  # suppress immediate re-persist of values we're applying
        try:
            self._load_user_settings_inner(user_id)
        finally:
            self._loading_settings = False

    def _load_user_settings_inner(self, user_id: int) -> None:
        g = self._db.get_user_setting

        # Always applies a value (default if absent), so no user inherits the previous user's settings.
        self._settings_store.load(user_id)

        # Load formulas BEFORE GraphSeries.restore so the per-slot validity gate
        # sees real is_valid; the picker selection (graph_series_*) decides visibility.
        self._formula_settings.load(user_id)
        self._program_settings.load(user_id)  # its saved-programs list goes to both UIs at the end (refresh_saved)

        self._graph_series.restore(user_id)

        # Skip BT/mock restore if --serial override is active
        if not self.serial_device_override:
            bt_addr = g(user_id, "bt_device_address")
            bt_name = g(user_id, "bt_device_name")
            if bt_addr:
                self._real_stream.set_device(bt_addr, bt_name or bt_addr)
                self._settings_screen.device.update_device_status(False, meta=f"Saved device: {self._headset.name()}")
            # use_mock is applied by the settings registry (store.load) above.

        # Update live screen device label to match current mode
        if APP.USE_MOCK_DEVICE:
            self._live_screen.update_device_status(False, device_name="Mock EEG")
        elif self._real_stream._device_address:
            name = self._headset.name()
            self._live_screen.update_device_status(False, device_name=name)

        history_mode = g(user_id, "history_view_mode") or "calendar"
        self._history_screen.set_view_mode(history_mode)

        # Sync live-screen preset highlight (incl. program "P") with loaded state
        self._program_settings.sync_picker()
        self._formula_settings.refresh_saved()
        self._program_settings.refresh_saved()
        logger.debug(f"Loaded settings for user {user_id}")

    def on_start(self) -> None:
        """Replay any errors that occurred before the UI was up.

        Diagnostics from `app/config.py` (DB migrations etc.) accumulate in
        `crash_handler._PRE_APP_ERRORS` because Kivy's Clock isn't alive at
        import time. We flush them now via `report_soft_error`.
        """
        try:
            flush_pre_app_errors()
        except Exception:
            logger.exception("flush_pre_app_errors failed")
        render_stats.start()

    def on_pause(self) -> bool:
        """Android lifecycle: save settings and allow Kivy to pause cleanly.

        Session work (compute, audio, DB flush) continues via the background
        tick thread and the foreground service even while the UI is paused.
        Per Kivy docs returning False here would *stop* the app, not prevent
        the pause — so we always return True.

        Also flips `_is_paused` so the tick thread skips per-tick UI work
        (graph add_point, stats updates). Otherwise N minutes of locked
        screen accumulates ~120·N Clock callbacks, each redrawing the
        whole graph; on resume they all fire in a burst and the render
        loop chokes (black-screen / app freeze).
        """
        self._is_paused = True
        logger.info("on_pause fired — _is_paused=True")
        # Skip the flush during a restore's relaunch window (mirrors on_stop):
        # the DB was just replaced with the imported file, so writing the old
        # in-memory state back would clobber the freshly-restored data.
        if not getattr(self, "_restoring", False):
            self._flush_on_leave()
        return True

    def on_resume(self) -> None:
        """Android lifecycle: app foreground after a pause (screen unlock).

        The tick thread skipped per-tick UI updates while paused, so the
        graph and stats labels are stale. Drop the pause flag and force
        a single UI refresh from current session state. Anything queued
        through `_on_main` during the pause (e.g. timer-expiry finish,
        BT alerts) drains on its own from Kivy's Clock.
        """
        self._is_paused = False
        logger.info("on_resume fired — _is_paused=False")
        # Post-restore, the DB is shut down (null connection) and only a real
        # relaunch fixes it. If Android resumed the process instead of killing
        # it, keep the app blocked behind the relaunch popup rather than letting
        # it run against a no-op DB that looks empty.
        if getattr(self, "_restoring", False):
            self._show_relaunch_popup()
            return
        # Re-validate the user gate: if the process survived a background/kill
        # in an unset state (not the deliberate All-Users view) and no gate is
        # already up, re-enter it rather than resume usable with no user.
        # getattr guards keep this safe if on_resume fires before build() runs.
        if (getattr(self, "_bottom_nav", None) is not None
                and getattr(self, "_current_user_id", None) is None
                and not getattr(self, "_view_all_users", False)
                and getattr(self, "_gate_popup", None) is None):
            self._open_user_gate(0)
            return
        try:
            Clock.schedule_once(lambda dt: self._refresh_ui_after_resume(), 0)
        except Exception:
            logger.exception("on_resume UI refresh failed")

    def _refresh_ui_after_resume(self) -> None:
        """Sync UI to current session state after Android resume.

        If the session is no longer RUNNING (e.g. timer expired during
        pause and ``_finish_on_main`` already fired ``_stop_and_save`` →
        the summary card now covers the live screen), skip the graph
        reload entirely. Combining 3 graph reloads with the heavy work
        in ``_stop_and_save`` on the first frame after resume previously
        blocked the UI thread long enough to trigger an Android ANR
        ('App not responding' / black screen).

        While the session is RUNNING, reload all three live graphs in a
        single batch from the session-lifetime mirror buffers (one
        ``load_static_data`` call per graph, one redraw each), then
        refresh the stats/state/timer labels from the latest sample.
        """
        t_start = time.monotonic()
        if getattr(getattr(self, "_sm", None), "current", None) == "history":
            self._history_screen.on_pre_enter()  # resumed onto it on another day: the chart and the totals move on
        if self._session_manager.state != SessionState.RUNNING:
            logger.info("on_resume: session not RUNNING → skipping graph reload")
            return
        try:
            self._mirror.reload_into(self._live_screen)
            if self._mirror.last_metrics:
                self._live_screen.update_stats(self._mirror.last_metrics)
                self._live_screen.update_state(self._mirror.last_state)
                self._live_screen.set_shamatha(self._shamatha_active)
        except Exception:
            logger.exception("graph reload on resume failed")
        try:
            self._live_screen.update_timer(self._session_manager.elapsed_formatted)
        except Exception:
            logger.exception("update_timer on resume failed")
        logger.info(
            f"on_resume: refresh complete in {time.monotonic() - t_start:.3f}s"
        )

    def on_stop(self) -> None:
        """Cleanup on app exit.

        We intentionally do NOT call _real_stream.stop() here.  Letting the
        process exit naturally allows the kernel to close the RFCOMM socket
        while BlueZ may keep the ACL link alive.  This means the *next* app
        launch can open a fresh RFCOMM on the existing ACL link and the
        ThinkGear ASIC will resume streaming immediately — avoiding the
        "connected but no packets" problem caused by a stale ACL.

        After a Restore-database, _restoring is set so we skip
        _flush_on_leave: the DB file has just been replaced and writing
        the current in-memory state would clobber the imported data.
        """
        if not getattr(self, "_restoring", False):
            self._flush_on_leave()
            if self._session_manager.state in (SessionState.RUNNING, SessionState.PAUSED):
                # Skipped while _restoring: the DB is already shut down, so the
                # save would silently no-op into the null connection. (The restore
                # entry points refuse to run while a session is active, so this is
                # defense-in-depth, not a data-loss path.)
                self._stop_and_save()
        self._audio.cleanup()
        self._db.mark_shutting_down()
        self._db.close()
        logger.info("Application closed")
