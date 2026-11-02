import os
import sqlite3
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

from app import android_jni
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
from app.keep_awake import KeepAwake
from app.logger import logger
from app.metrics.engine import MetricsEngine
from app.metrics.formula_slots import (
    FORMULA_KEYS,
    FormulaSlots,
)
from app.metrics.noise_detector import PowerLineDetector
from app.session.manager import SessionManager, SessionState, elapsed_clock
from app.session.recorder import SessionRecorder
from app.session.session_program import (
    PROGRAM_FORMULA_KEYS,
    segment_target,
)
from app.session.session_run import Phase, SessionRun
from app.session.tick_thread import TickThread
from app.session.timer_state import TimerState
from app.settings.registry import (
    BOOL,
    FLOAT,
    INT,
    STR,
    Setting,
    SettingsStore,
    stored_value,
)
from app.storage.database import DatabaseManager
from app.ui import render_stats
from app.ui.app_context import AppContext, SessionAccess
from app.ui.backup_flow import BackupFlow
from app.ui.bt_wait import BtWait
from app.ui.diary_screen import DiaryScreen
from app.ui.formula_settings import FormulaSettings
from app.ui.graph_fullscreen import GraphFullscreen
from app.ui.graph_series import GraphSeries
from app.ui.headset import Headset
from app.ui.history_flow import HistoryFlow
from app.ui.history_screen import HistoryScreen
from app.ui.hooks import wire
from app.ui.line_colours import DEFAULT as LINE_DEFAULT
from app.ui.line_colours import LINE_COLOURS
from app.ui.line_colours import OPTIONS as LINE_OPTIONS
from app.ui.live_session import LiveSessionScreen
from app.ui.power_exemption import PowerExemption
from app.ui.profiles import ProfileGate, Profiles
from app.ui.program_run import ProgramRun
from app.ui.program_settings import ProgramSettings
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.session_detail_flow import SessionDetailFlow
from app.ui.session_labels import session_title, start_stamp
from app.ui.session_watch import SessionWatch
from app.ui.settings_screen import (
    SettingsScreen,
)
from app.ui.shown_session import ShownSession
from app.ui.theme import (
    DEFAULT_THEME,
    TEXT_SIZES,
    THEMES,
    BottomNav,
    C,
    F,
    StyledButton,
    ThemedLabel,
    confirm_popup,
    fill_background,
    format_count,
    make_message_popup,
    paint_panel,
)
from app.ui.widgets.loading_overlay import LoadingOverlay


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
        # Android pause state: when True, tick thread skips per-tick UI
        # work (graph add_point, stats updates) so a long screen-lock
        # doesn't accumulate thousands of Clock callbacks that flood the
        # main loop on resume (which previously caused a black screen).
        self._is_paused: bool = False
        self._recorder: SessionRecorder = SessionRecorder(
            self._db, self._session_manager, with_score=lambda stats: self._with_score(stats),
            row_fields=lambda: self._session_row_fields())
        self._current_user_id: Optional[int] = None
        # True while _load_user_settings applies values, so its change callbacks don't re-persist them.
        self._loading_settings: bool = False
        self._settle_triggers: dict = {}  # input name -> its settle trigger (_after_settle)
        self._settle_fns: dict = {}  # input name -> the function its trigger runs (the latest one given)
        self._formulas: FormulaSlots = FormulaSlots()
        self.serial_device_override: Optional[str] = None
        self._keep_awake: KeepAwake = KeepAwake()  # held from a session's setup to its ending

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

    def _change_setting(self, key: str, value) -> None:
        """The one change path of a setting the store holds: it holds and applies the value, persisted now, or once a
        continuous input settles."""
        self._settings_store.change(key, value)
        if self._settings_store.settles(key):
            self._persist_user_setting_later(key)
        else:
            self._persist_user_setting(key)

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
        return self._formulas.session_record(self._live_screen.graph.is_visible,
                                             self._settings_store.value("audio_metric"))

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
        src = self._settings_store.value("reward_source")
        if src in ("", "none"):
            return ""
        if src == "custom":
            return self._settings_store.value("reward_sound_path") or ""
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
        src = self._settings_store.value("feedback_source")
        if src in ("", "none"):
            return "none"
        if src == "custom":
            return self._settings_store.value("feedback_sound_path") or "noise"
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

    # Map bottom-nav tab keys to screen groups
    _TAB_SCREENS = {
        "session": "live_session",
        "history": "history",
        "settings": "settings",
    }

    def build(self) -> FloatLayout:
        install_crash_handler(self)
        self._ctx = self._make_context()

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
        self._program_run = ProgramRun(self._ctx, self._session_manager, self._audio, self._live_screen,
                                       formula_vars=self._eval_formula_vars)
        self._settings_screen = SettingsScreen()
        self._history_screen = HistoryScreen()
        self._diary_screen = DiaryScreen()
        self._timer_state = TimerState()
        self._program_settings = ProgramSettings(
            self._ctx, self._settings_screen.timer, self._live_screen, self._session_manager,
            show_saved_series=lambda uid: self._graph_series.apply_saved(self._live_screen.graph, uid))
        self._formula_settings = FormulaSettings(self._ctx, self._settings_screen.formulas, self._live_screen.graph,
                                                 self._formulas, scoring_locked=self._formula_scoring_locked)
        self._headset = Headset(self._ctx, self._real_stream, self._settings_screen.device, self._live_screen,
                                serial_override=lambda: self.serial_device_override)
        self._headset.load_aliases()
        self._power = PowerExemption(self._ctx, self._settings_screen.device)
        self._bt_wait = BtWait(self._real_stream, self._live_screen, headset_name=self._headset.name,
                               on_main_for=self._on_main_for)
        self._watch = SessionWatch(self._real_stream, self._audio, self._live_screen, self._headset,
                                   on_main=self._on_main)

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
            self._ctx, self._live_screen.graph, self._formulas, self._program_run, self._program_settings,
            self._formula_settings, graphs=self._all_graphs, detail_program=self._diary_screen.program_lines_of,
            legacy_defaults=self._settings_screen._graph_toggles)
        self._loading_overlay = LoadingOverlay()
        self._history = HistoryFlow(self._ctx, self._history_screen, self._formulas, self._loading_overlay,
                                    on_sessions_deleted=lambda ids: self._shown.on_sessions_deleted(ids))
        self._shown = ShownSession(self._ctx, self._live_screen, self._audio, self._history, self._recorder)
        self._detail = SessionDetailFlow(self._ctx, self._diary_screen, self._history_screen, self._sm,
                                         self._graph_series)
        self._gate = ProfileGate(
            self._ctx, self._bottom_nav, refresh_profiles=lambda: self._profiles.refresh(),
            scan_for_new_profile=self._headset.scan_for_new_profile, offer_power_exemption=self._power.offer_once)
        self._profiles = Profiles(self._ctx, self._settings_screen, self._gate, deactivate=self._deactivate_user,
                                  on_deleted=self._on_profile_deleted)
        self._last_back_time = 0.0  # for double-back-to-exit on the root screen
        float_root.add_widget(root)
        float_root.add_widget(self._loading_overlay)

        self._bind_callbacks()
        self._link_graph_zoom()
        # After _bind_callbacks (it sets the fields get() snapshots as defaults), before any user load.
        self._build_settings_store()
        resolved_user = self._restore_last_user()
        self._profiles.refresh()

        # Hard user gate: the app is never usable without a resolved concrete
        # user. Gate on "did we resolve a user", NOT on whether the users table
        # is non-empty — reinstall / restored DB / deleted-active-profile /
        # corrupt last_user_id all leave users present but none current. Disable
        # nav synchronously so there is no cold-start window where the app is
        # tappable with no user; the selection modal re-enables it. The modal
        # is a Popup, not a Screen, because a TextInput inside a
        # Screen doesn't get keyboard focus on some platforms.
        if resolved_user is None:
            self._gate.open(0.5)

        return float_root

    def _make_context(self) -> AppContext:
        """What every flow reaches the app through; the callables read the app when called, so they see the profile and
        the session as they are then."""
        session = SessionAccess(live=self._session_pipeline_live, connecting=self._connecting,
                                running_id=self._running_session_id, refused=self._refused_while_session_runs,
                                discard=self._discard_running_session)
        return AppContext(db=self._db, user_id=lambda: self._current_user_id, activate_user=self._activate_user,
                          require_user=self._require_user, on_main=self._on_main, switch_screen=self._switch_screen,
                          info=self._info_popup, toast=self._toast, confirm=self._confirm_action,
                          save_settings=self._save_user_settings, session=session)

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
        wire(
            self._live_screen,
            on_duration_preset=self._program_settings.on_duration_preset,
            on_program_pick=self._program_settings.on_load,
        )
        self._live_screen.overlay_cancel_btn.bind(on_release=self._on_connect_cancel)
        self._live_screen.overlay_retry_btn.bind(on_release=self._on_connect_retry)
        self._live_screen.summary_ok_btn.bind(on_release=self._shown.on_ok)
        self._live_screen.summary_save_notes_btn.bind(on_release=self._shown.on_save_notes)
        self._live_screen.summary_delete_btn.bind(on_release=self._shown.on_delete)

        # Tap on graph to set marker (Android — no keyboard available)
        if android_jni.on_android():
            wire(self._live_screen.graph, on_tap=self._on_marker)

        # Shared fullscreen-expand + series-picker glyphs on every graph
        self._wire_graph_affordances()

        wire(
            self._settings_screen,
            on_threshold_change=self._on_threshold_change,
            on_audio_metric_change=self._on_audio_metric_change,
            on_audio_formula_index=self._on_audio_formula_index,
            on_theme_change=self._on_theme_change,
            on_profile_switch=self._profiles.on_switch,
            on_profile_create=self._profiles.on_create,
            on_profile_delete=self._profiles.on_delete,
            session_counter=self._profiles.count_sessions,
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
            on_battery_settings=self._power.on_battery_settings,
            on_maker_settings=self._power.on_maker_settings,
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

        wire(
            self._diary_screen,
            on_save_notes=self._history.save_notes,
            on_export_csv=self._history.on_export_csv,
            on_back=self._detail.on_diary_back,
            on_band_view_change=self._detail.persist_band_view,
            on_band_collapse=lambda _collapsed: self._persist_user_setting("band_power_collapsed"),
        )

        wire(
            self._history_screen,
            on_session_select=self._detail.on_session_select,
            on_delete_sessions=self._history.delete_sessions,
            on_rename_session=self._history.on_rename_session,
            on_view_mode_change=self._history.on_view_mode_change,
            on_export_sessions=self._history.on_export_sessions_csv,
            on_chart_collapse=lambda _collapsed: self._persist_user_setting("history_chart_collapsed"),
        )
        wire(self._diary_screen.what_if, on_collapse=lambda _collapsed: self._persist_user_setting("what_if_collapsed"))

        # Data Backup section
        self._backup_flow = BackupFlow(self._ctx, self._settings_screen, user_name=self._profiles.current_name,
                                       checkpoint=self._checkpoint_or_report, on_db_replaced=self._on_db_replaced)
        wire(
            self._settings_screen,
            on_backup_pressed=self._backup_flow.on_backup_pressed,
            on_restore_pressed=self._backup_flow.on_restore_pressed,
        )

    def _activate_user(self, uid: int) -> None:
        """Make `uid` the active profile and load its settings; every path that picks a user goes here."""
        if self._shown.owner not in (None, uid):  # the Session screen shows another profile's session
            self._shown.drop(keep_notes=True)
        self._current_user_id = uid
        self._db.set_setting("last_user_id", str(uid))
        self._load_user_settings(uid)
        self._history.mark_dirty()  # History still lists the previous profile's sessions

    def _deactivate_user(self) -> None:
        """No active profile (its own was deleted, the gate opens next): its programs leave the UI now."""
        self._current_user_id = None
        self._program_settings.refresh_saved()

    def _on_profile_deleted(self, uid: int) -> None:
        if uid == self._shown.owner:  # its session went with it: the card has nothing left to save
            self._shown.drop(keep_notes=False)
        self._history.mark_dirty()

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

    def _on_nav_tab(self, tab_key: str) -> None:
        """Handle bottom nav tab press."""
        screen_name = self._TAB_SCREENS.get(tab_key, tab_key)
        self._switch_screen(screen_name)

    def _switch_screen(self, name: str) -> None:
        if name == "diary" and not self._current_user_id:
            # silent-ok: unreachable post-gate; any concrete user passes.
            # Defensive block against a should-not-happen unset.
            logger.debug("Diary switch blocked: no user selected")
            return
        logger.debug(f"Screen switch: {name}")
        self._sm.current = name
        if name == "history":
            self._history.refresh()
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

        run = self._run = SessionRun(self._current_user_id)
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream = self._mock_stream
            self._start_session_common()
            return

        # Real device — need BT connection
        if self._real_stream._device_address:
            # The profile's headset, or one picked in Settings
            self._eeg_stream = self._real_stream
            self._start_session_common()
            return

        # No headset selected: find the profile's among the paired devices, then connect
        self._live_screen.show_overlay("Scanning for MindWave...")
        self._live_screen.set_controls_running()
        logger.info("Auto-scanning for BT device before session start")
        def _scanned(devices: list[dict]) -> None:
            if run is not self._run:
                return  # cancelled while scanning
            if run.user_id != self._current_user_id:
                self._cancel_session_start("IDLE")  # the Start was the profile picked away while it scanned
                return
            mindwaves = self._headset.adopt(devices)
            if self._real_stream._device_address:
                self._eeg_stream = self._real_stream
                self._live_screen.update_overlay(f"Found {self._headset.name()}\nConnecting...")
                self._start_session_common()
            elif mindwaves:
                self._live_screen.set_controls_idle()
                self._live_screen.hide_overlay()
                self._switch_screen("settings")
                self._settings_screen.device.focus_device_section(
                    f"Found {len(mindwaves)} MindWave devices.\n"
                    "Pick the one you want to use, then press Start again."
                )
            elif devices:
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

        self._headset.find_paired(_scanned)

    def _on_main(self, fn) -> None:
        """Queue callable on Kivy's main thread.

        Thread-safe per Kivy docs.  During Kivy pause (screen locked) the
        call is buffered and executed when the app resumes.
        """
        Clock.schedule_once(lambda dt: fn(), 0)

    # ------------------------------------------------------------------

    def _start_session_common(self) -> None:
        """Shared session startup logic after device is resolved."""
        # The session takes the audio over: the last session's gong stops, and so does a Settings test still running.
        self._audio.stop_timer_bell()
        self._audio.end_test()
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
        run = self._run
        self._metrics_engine.reset()
        run.noise_detector = PowerLineDetector() if not APP.USE_MOCK_DEVICE else None
        self._recorder.begin()
        run.connect_start = time.time()

        self._shown.take(self._current_user_id)
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
        self._live_screen.set_controls_running()
        self._settings_screen.lock_threshold(self._refuse_program_threshold if self._program_run.active else None)

        self._keep_awake.hold()

        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.start()
            self._session_manager.start(threshold=threshold)
            run.phase = Phase.STARTED
            self._audio.start()
            self._timer_state.start_countdown()
            self._live_screen.update_device_status(True)
            self._live_screen.update_state("Running")
            self._live_screen.set_start_time(self._session_manager.started_at)
            self._live_screen.hide_overlay()
        elif self._real_stream.is_connected:
            # BT still connected from previous session — reuse it
            self._real_stream.reset_sample_state()
            name = self._headset.name()
            self._session_manager.start(threshold=threshold)
            run.phase = Phase.STARTED
            self._timer_state.start_countdown()
            self._on_session_connected(name)
            logger.info(f"Reusing existing BT connection to {name}")
        elif not self._begin_bt_wait(run):
            return

        self._ticker.start()
        logger.info("Session started via UI")

    def _begin_bt_wait(self, run: SessionRun) -> bool:
        """Main thread: enter the run's BT wait; False if the reader refused to start (the start undone, Retry offered)."""
        end = self._bt_wait.begin(run)
        if end is not None:
            self._undo_failed_start(end.message)
        return end is None

    def _follow_bt_wait(self, run: SessionRun) -> None:
        """Tick thread: one step of the run's BT wait. Its first data starts the session against the threshold in force
        (it may have moved); a give-up tears the wait down here and undoes the start on the main thread."""
        end = self._bt_wait.tick(run)
        if end is None:
            return
        if not end.started:
            self._abort_bt_wait()
            self._on_main_for(run, lambda: self._undo_failed_start(end.message))
            return
        # Armed on this thread before the next tick reads it: deferred to main, a stalled main thread ended a 0 s session.
        self._session_manager.start()
        self._timer_state.start_countdown()
        run.phase = Phase.STARTED
        name = self._headset.name()
        self._on_main_for(run, lambda: self._on_session_connected(name))

    def _undo_failed_start(self, message: str) -> None:
        """Main thread: a start whose BT wait ended without a session is undone, and Retry offered."""
        self._undo_session_setup()
        self._bt_wait.show_retry(message)

    def _abort_bt_wait(self) -> None:
        """Tear down a BT-connect wait; the tick watcher stops first or it reads our stop as a failed connect."""
        self._ticker.stop()
        if self._run is not None:
            self._run.phase = Phase.ENDED
        self._real_stream.stop()
        self._keep_awake.release()
        self._shown.owner = None  # no session came of the start, which emptied the display

    def _on_connect_cancel(self, *args) -> None:
        """Cancel button on connection overlay."""
        self._cancel_session_start("IDLE")

    def _cancel_session_start(self, state: str) -> None:
        """End a start that hasn't become a session: the device scan, the BT wait, or data that arrived in the same frame
        as the Cancel."""
        if self._run is not None and self._run.phase in (Phase.CONNECTING, Phase.STARTED):
            self._abort_bt_wait()
        self._live_screen.hide_overlay()
        self._undo_session_setup()  # also resets a session that started in the frame of the Cancel
        self._live_screen.update_state(state)

    def _undo_session_setup(self) -> None:
        """Main thread: undo what _start_session_common set up, for a session that ended or never started. Ends its
        run, so the callbacks still queued for it do nothing."""
        self._run = None
        self._live_screen.set_training_series(None)  # clear the program "training now" marker
        self._program_run.end()
        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._live_screen.set_shamatha(False)
        self._timer_state.reset()
        self._session_manager.reset()
        self._settings_screen.lock_threshold(None)
        self._keep_awake.release()

    def _on_connect_retry(self, *args) -> None:
        """Retry button on connection overlay."""
        self._live_screen.hide_overlay()
        self._live_screen.set_controls_idle()
        self._on_start()

    def _flush_on_leave(self) -> None:
        """Persist what the user changed but hasn't saved, before the app pauses or exits."""
        self._leaving = True
        try:
            if getattr(self, "_shown", None) is not None:
                self._shown.flush_notes()
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
        # Decided by the session, not the run's phase: a wait that has just ended is over before its idle UI shows.
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
            self._shown.mirror.reload_into(self._live_screen)
        except Exception:
            logger.exception("graph reload on stop failed")
        self._live_screen.update_stats(self._session_manager.live_score())  # the whole session's: no tick ran while locked
        self._undo_session_setup()
        self._live_screen.update_state("FINISHED")
        # Sync the header timer to the final duration (it froze at lock time).
        if stats:
            self._live_screen.update_timer(elapsed_clock(stats.get("duration", 0)))
        self._history.mark_dirty()
        if getattr(getattr(self, "_sm", None), "current", None) == "settings":  # a timer can end it there
            self._settings_screen.refresh_profile_counts()  # else entering Settings redraws them
        if stats and session_id:
            try:
                saved = self._db.get_session(session_id)  # titled like its History row, from what was stored
            except sqlite3.Error:
                logger.exception(f"Session {session_id} saved, but its title couldn't be read for the end card")
                saved = None
            self._shown.show_end_card(session_id, stats, session_title(saved) if saved else "")

    def _refused_while_session_runs(self, doing: str, why: str = "") -> bool:
        """True, after telling the user, while a session runs or connects: until it stops it owns its profile, the
        database it saves to, the metric it is scored on and a program's targets."""
        if not self._session_pipeline_live():
            return False
        self._info_popup("Session in progress", f"{why} Stop the current session before {doing}.".lstrip())
        return True

    def _session_pipeline_live(self) -> bool:
        """True while a session runs or is paused, or its start waits for the headset: the window in which a restore
        or the active profile's delete would drop or orphan it (the state alone misses the wait)."""
        return self._session_manager.state in (SessionState.RUNNING, SessionState.PAUSED) or self._connecting()

    def _connecting(self) -> bool:
        """The BT wait: the reader is up and the first data will start the session."""
        return self._run is not None and self._run.phase is Phase.CONNECTING

    def _discard_running_session(self) -> None:
        """Halt a running session and DELETE its data — used when its owning
        profile is deleted. A checkpoint (the 60 s flush, leaving the app, a backup) may already have written a
        session row under the doomed profile; without the delete it survives as
        an orphan. Then reuses the shared _finalize_stop_ui teardown so the
        Session screen returns to idle."""
        if self._run is not None:
            self._run.phase = Phase.ENDED  # also halts a start still in the BT wait
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

    def _on_main_for(self, run: SessionRun, fn: Callable[[], object]) -> None:
        """Queue fn for the main thread as part of `run`; it does nothing once that run has ended (a Cancel, Stop or
        profile delete handled before it) or another Start has replaced it."""
        self._on_main(lambda: fn() if self._run is run else None)

    def _update_tick(self, dt: float) -> None:
        """Main 2 Hz processing loop.

        Runs on the background SessionTick thread.  All Kivy widget calls are
        dispatched via _on_main so they execute on the main thread.  Audio,
        metrics compute, and DB writes are thread-safe and stay direct.
        """
        run = self._run  # this tick's run: a main-thread stop waits for a tick in progress, so no newer one is begun
        if run is None:
            return
        if run.phase is Phase.CONNECTING:
            self._follow_bt_wait(run)
            return

        if self._session_manager.state != SessionState.RUNNING:
            return

        ending = self._watch.check(run, self._session_manager.elapsed_seconds)
        if ending:
            self._end_from_tick(run, *ending)
            return

        raw_sample = self._eeg_stream.read_sample()
        metrics = self._metrics_engine.process_sample(raw_sample)
        self._watch.check_sample(run, raw_sample)
        run.tick_count += 1
        self._log_tick(run, raw_sample, metrics)

        self._formulas.evaluate_into(metrics, lambda: self._eval_formula_vars(raw_sample, metrics))

        # Program vs simple is what the session started as, not the Settings toggle (editable mid-session).
        # The drive key is resolved once: the tick scores and sounds the same metric.
        if self._program_run.active:
            self._program_run.tick(metrics, raw_sample)
            drive_key, mark = self._audio_drive_key(), None
        else:
            drive_key = mark = self._score_on_drive_key()

        # Merge raw + computed for full storage; a pending marker is in the row before a checkpoint can write it.
        full_record = {**raw_sample, **metrics}
        marker_pending = run.pending_marker
        if marker_pending:
            run.pending_marker = False
            full_record["marker"] = 1
        score = self._recorder.record(metrics, full_record)
        if score is None:  # the session paused or stopped while this tick was read: it isn't part of it
            run.pending_marker |= marker_pending  # the marker goes on the next recorded tick
            return

        # Audio is thread-safe — update directly
        self._audio.update(metrics.get(drive_key, 0))
        if run.tick_count > 10:
            self._audio.update_sinking(metrics.get("sinking", 0))
            self._audio.update_subtle_distraction(metrics.get("subtle_distraction", 0))

        self._shown.mirror.record(metrics, score, raw_sample)  # kept even while the screen is locked
        self._show_tick(run, metrics, raw_sample, score, marker_pending, mark)

        # Timer countdown — tick() is pure counter, no UI
        if self._timer_state.tick(APP.UPDATE_FREQUENCY):
            self._end_by_timer(run)
            return

        self._recorder.flush_tick()  # DB opened with check_same_thread=False

    def _log_tick(self, run: SessionRun, raw_sample: dict, metrics: dict) -> None:
        """Log the raw sample and the metrics every 10 ticks (~5s at 2Hz)."""
        if run.tick_count % 10 != 0:
            return
        bands = {k: f"{raw_sample.get(k, 0):.0f}" for k in BAND_KEYS}
        logger.debug(f"Raw sample #{run.tick_count}: {bands}")
        native_med = raw_sample.get("meditation", -1)
        bat = raw_sample.get("battery", -1)
        bat_str = f" bat={bat}/127" if bat >= 0 else ""
        logger.debug(f"Metrics: med={metrics.get('meditation_score', 0):.0f} "
                     f"sham={metrics.get('shamatha_score', 0):.0f} "
                     f"sink={metrics.get('sinking', 0):.0f} "
                     f"dist={metrics.get('distraction', 0):.0f} "
                     f"native_med={native_med:.0f}{bat_str}")

    def _show_tick(self, run: SessionRun, metrics: dict, raw_sample: dict, score: dict, marker_pending: bool,
                   mark: str | None) -> None:
        """Tick thread: queue the tick's Session screen update for the main thread, unless the screen is locked."""
        elapsed_fmt = self._session_manager.elapsed_formatted

        # Debounced shamatha-zone crossing (tick thread) — only the change is
        # dispatched, so the chip can't restyle every tick.
        sham_prev = run.shamatha_active
        run.shamatha_active, run.shamatha_streak = self._shamatha_transition(
            sham_prev,
            metrics.get("shamatha_score", 0.0) >= self._shamatha_threshold,
            run.shamatha_streak,
        )
        sham_changed = run.shamatha_active != sham_prev

        def _ui_update(
            m=metrics, rs=raw_sample, ef=elapsed_fmt, mp=marker_pending,
            sa=run.shamatha_active, sc=sham_changed, sk=self._scored_mark(run, mark), tg=score["score_target"],
            on=score["score_key"], live=self._session_manager.live_score(),
        ) -> None:
            self._live_screen.graph.add_point(m, threshold=tg, scored=on)  # its line coloured from this point
            self._live_screen.update_stats(live)
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

    def _end_from_tick(self, run: SessionRun, reason: str, alert: str) -> None:
        """Tick thread: a check ended the session. It is frozen here (its duration ends now, its sound goes quiet, no
        later tick can end it again) and saved on the main thread, once, while its run is current."""
        self._session_manager.pause()
        self._checkpoint_or_report()  # Android may close a locked app before the unlock: its ticks so far are saved now
        self._audio.mute()
        self._ticker.stop()
        self._on_main_for(run, lambda: (self._live_screen.show_alert(alert), self._stop_and_save(reason=reason)))

    def _end_by_timer(self, run: SessionRun) -> None:
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
        # Stop the loop now (safe from this thread): no later tick can end the session again.
        self._ticker.stop()

        def _finish_on_main(_dt=None):
            self._audio.stop()  # full noise teardown on the main thread
            self._finalize_stop_ui(stats, session_id)
        self._on_main_for(run, _finish_on_main)  # an ending that ran first (a profile's delete) has done it
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
        if self._gate.active():
            return self._handle_gate_back()
        # An open Popup/ModalView dismisses itself on escape — let it.
        if any(isinstance(c, ModalView) for c in Window.children):
            return False
        # Fullscreen graph overlay → close it (it's not a ModalView).
        if self._fullscreen.close():
            return True
        current = self._sm.current
        if current == "diary":
            self._detail.on_diary_back()
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
        if self._leaving and android_jni.on_android():
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
        if not android_jni.on_android():
            logger.debug(f"toast: {message}")
            return
        try:
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _show():
                from jnius import autoclass
                Toast = autoclass("android.widget.Toast")
                Toast.makeText(
                    android_jni.activity(), android_jni.java_string(message), Toast.LENGTH_SHORT
                ).show()
            _show()
        except Exception as e:
            logger.warning(f"Toast failed: {e}")

    def _on_marker(self, *args) -> None:
        """Place a marker at the current position in the session."""
        run = self._run  # a tick that outlived a Cancel can start the session for a run already ended
        if run is not None and self._session_manager.state == SessionState.RUNNING:
            run.pending_marker = True
            logger.info("Marker placed")

    def _on_threshold_change(self, value: int) -> None:
        if self._shown.mirror.metrics and not self._session_pipeline_live():
            self._shown.clear()  # the last session's line is not the threshold the next one runs against
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
        if self._refused_while_session_runs("testing the audio", why="The test plays through the session's sounds."):
            return
        sources, gid, reward_id = self._test_audio_sources()
        self._warn_missing_sound_files(sources, force=True)
        self._audio.prepare_feedback(sources, gid)
        self._audio.test_audio(reward_id)

    def _on_line_width_change(self, width: float) -> None:
        self._change_setting("line_width", width)

    def _apply_line_width(self, width: float) -> None:
        self._live_screen.graph.set_line_width(width)
        self._live_screen.raw_graph.set_line_width(width)
        self._live_screen.band_graph.set_line_width(width)
        self._diary_screen._metrics_graph.set_line_width(width)
        self._diary_screen._raw_eeg_graph.set_line_width(width)
        self._diary_screen._freq_graph.set_line_width(width)
        logger.debug(f"Line width changed to {width}")

    def _on_rotate_screen(self, rotation: int) -> None:
        self._change_setting("rotation", rotation)
        logger.info(f"Screen rotation set to {rotation}")

    @staticmethod
    def _baseline_audio_metric(key: str) -> str:
        """The user's persisted audio metric; program-formula slots are program-only
        and must never persist as a baseline (outside a program they read 0 -> max noise)."""
        return "shamatha_score" if (not key or key in PROGRAM_FORMULA_KEYS) else key

    def _score_on_drive_key(self) -> str:
        """A simple session is scored on the metric that drives the feedback sound (#51), so they can't diverge."""
        key = self._audio_drive_key()
        self._session_manager.set_active_goal(key)
        return key

    def _scored_mark(self, run: SessionRun, key: Optional[str]) -> Optional[str]:
        """The scored series for the legend to mark this tick: only on a change, and only while the UI is showing (a
        change during a screen lock is picked up by the first tick after it)."""
        if key is None or key == run.scored_key or self._is_paused:
            return None
        run.scored_key = key
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
            key = self._baseline_audio_metric(self._settings_store.value("audio_metric"))
        ev = self._formulas.for_key(key)
        if ev is not None and not ev.is_valid:
            return "shamatha_score"
        return key

    def _on_audio_metric_change(self, key: str) -> None:
        """Switch which metric drives the audio threshold feedback: a running session keeps the one it is scored on
        (#51 scores it on the drive key every tick, so a switch mixed both metrics into one average and streak)."""
        store = self._settings_store
        new_key = FORMULA_KEYS[store.value("audio_formula_index")] if key == "custom_formula" else key
        if new_key != store.value("audio_metric") and self._scoring_locked("changing the metric it is scored on"):
            self._show_audio_metric()
            return
        self._change_setting("audio_metric", new_key)
        logger.info(f"Audio threshold metric changed to: {new_key}")

    def _on_feedback_source_change(self, source: str, path: str) -> None:
        """The global (below-threshold) feedback source chosen in Settings; its path first, so the source shows with
        it."""
        self._change_setting("feedback_sound_path", (path or "").strip())
        self._change_setting("feedback_source", source)
        logger.info(f"Feedback source -> {source} {self._settings_store.value('feedback_sound_path')!r}")

    def _on_reward_source_change(self, source: str, path: str) -> None:
        """The above-threshold reward source chosen in Settings; its path first, so the source shows with it."""
        self._change_setting("reward_sound_path", (path or "").strip())
        self._change_setting("reward_source", source)
        logger.info(f"Reward source -> {source} {self._settings_store.value('reward_sound_path')!r}")

    def _on_audio_formula_index(self, idx: int) -> None:
        """Pick which formula slot drives audio. Only rebinds the live key when a
        custom-formula slot is the selected driver — tapping it while another metric
        is selected just remembers the choice for when custom-formula is picked."""
        idx = max(0, min(idx, len(FORMULA_KEYS) - 1))
        metric = self._settings_store.value("audio_metric")
        if (metric in FORMULA_KEYS and FORMULA_KEYS[idx] != metric
                and self._scoring_locked("changing the metric it is scored on")):
            self._show_audio_metric()
            return
        self._change_setting("audio_formula_index", idx)
        if metric in FORMULA_KEYS:
            # Load derives the index from audio_metric, so persist both or a reload reverts the switch.
            self._change_setting("audio_metric", FORMULA_KEYS[idx])

    def _formula_scoring_locked(self, key: str, doing: str) -> bool:
        """True (after telling the user) when the formula slot `key` drives the sound of a simple session running."""
        return key == self._settings_store.value("audio_metric") and self._scoring_locked(doing)

    def _scoring_locked(self, doing: str) -> bool:
        """True (after telling the user) while a simple session runs: it is scored on the audio control metric (#51)
        until it stops. A program session is scored on its segments' metrics, so the control stays free."""
        return (not self._program_run.active
                and self._refused_while_session_runs(doing))

    def _show_audio_metric(self) -> None:
        """Settings' audio-metric choice and formula-slot buttons show the metric in force."""
        key = self._settings_store.value("audio_metric")
        self._settings_screen.audio_metric = "custom_formula" if key in FORMULA_KEYS else key
        self._settings_screen.audio_formula_index = self._settings_store.value("audio_formula_index")

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
        self._change_setting("sinking_alert", active)
        logger.info(f"Sinking alert {'enabled' if active else 'disabled'}")

    def _on_subtle_alert_toggle(self, active: bool) -> None:
        self._change_setting("subtle_alert", active)
        logger.info(f"Distraction chime {'enabled' if active else 'disabled'}")

    def _on_disconnect_alert_toggle(self, active: bool) -> None:
        self._change_setting("disconnect_alert", active)
        logger.info(f"Disconnect alert {'enabled' if active else 'disabled'}")

    def _on_timer_sound_change(self, path: str) -> None:
        """The custom timer-gong path ("" for the default bell), persisted once typing settles."""
        self._change_setting("timer_sound", path)

    def _on_test_timer_sound(self) -> None:
        path = self._timer_state.custom_sound_path
        logger.debug(f"Test timer sound, path='{path}'")
        self._warn_missing_sound_files({}, path, force=True)
        # The gong's end flips the Test button back from Stop (the engine calls it on Kivy's thread).
        played = self._audio.play_timer_sound(path, on_end=self._settings_screen.timer.notify_timer_sound_test_ended)
        if not played:
            report_soft_error("timer_sound_unplayable", "The timer sound can't be played.", app=self, force=True)
        elif path and played != path and os.path.isfile(path):
            report_soft_error("timer_sound_unplayable",
                              f"Custom timer sound can't be played: {path!r} - using the default gong instead.",
                              app=self, force=True)

    def _on_stop_test_timer_sound(self) -> None:
        logger.debug("Stop timer test sound")
        self._audio.stop_timer_bell()

    # The current Start, from the press to its ending (_undo_session_setup): a callback queued for an earlier one (the
    # device scan's result, the BT wait's UI and audio) finds it replaced and does nothing.
    _run: SessionRun | None = None
    def _running_session_id(self) -> int | None:
        """The running session's row, which History lists and Settings counts only once it ends: it exists from the
        first checkpoint, with stats as of that checkpoint (the ending marks History dirty)."""
        return self._recorder.session_id if self._session_pipeline_live() else None

    # --- Data Backup (app/ui/backup_flow.py) ---

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

    def _build_settings_store(self) -> None:
        """Build the settings registry; call once in build() before any user load, as get() snapshots defaults."""
        ss = self._settings_screen
        ls = self._live_screen
        settings: list[Setting] = []

        def set_timer_enabled(v):
            self._timer_state.set_enabled(v); ss.timer.timer_enabled = v

        def set_timer_minutes(v):
            self._timer_state.set_duration(v); ss.timer.timer_minutes = v

        def apply_timer_sound(v):
            self._timer_state.set_custom_sound_path(v); ss.timer.timer_sound_path = v

        def apply_sinking(v):
            self._audio.sinking_alert_enabled = v; ss.audio._sinking_alert_cb.active = v

        def apply_subtle(v):
            self._audio.subtle_alert_enabled = v; ss.audio._subtle_alert_cb.active = v

        def apply_disconnect(v):
            self._audio.disconnect_alert_enabled = v; ss.audio._disconnect_alert_cb.active = v

        def set_threshold(v):
            ss.threshold = v
            self._apply_threshold(v)

        def set_use_mock(v):
            APP.USE_MOCK_DEVICE = v; ss.device._device_mode_cb.active = v

        def apply_line_width(v):
            ss.display._line_width_slider.value = v; self._apply_line_width(v)

        def apply_rotation(v):
            ss.display._current_rotation = v
            ss.display._rotate_btn.text = f"Rotate Screen ({v}°)"
            Window.rotation = v


        def apply_feedback_source(v):
            ss.audio.set_feedback_source(v, self._settings_store.value("feedback_sound_path"))

        def apply_feedback_path(v):
            ss.audio.set_feedback_source(self._settings_store.value("feedback_source"), v)

        def apply_reward_source(v):
            ss.audio.set_reward_source(v, self._settings_store.value("reward_sound_path"))

        def apply_reward_path(v):
            ss.audio.set_reward_source(self._settings_store.value("reward_source"), v)

        def add(key, codec, get, set_):
            settings.append(Setting(key, get(), codec[0], codec[1], get, set_))

        def hold(key, codec, default, apply_, settle=False):
            settings.append(Setting(key, default, codec[0], codec[1], None, apply_, settle))

        add("timer_enabled", BOOL, lambda: ss.timer.timer_enabled, set_timer_enabled)
        add("timer_minutes", INT, lambda: ss.timer.timer_minutes, set_timer_minutes)
        hold("timer_sound", STR, ss.timer.timer_sound_path, apply_timer_sound, settle=True)
        hold("sinking_alert", BOOL, ss.audio._sinking_alert_cb.active, apply_sinking)
        hs = self._history_screen
        add("history_chart_collapsed", BOOL, lambda: hs.chart_collapsed, hs.set_chart_collapsed)
        what_if = self._diary_screen.what_if
        add("what_if_collapsed", BOOL, lambda: what_if.collapsed, what_if.set_collapsed)
        ds = self._diary_screen
        add("band_power_collapsed", BOOL, lambda: ds.band_collapsed, ds.set_band_collapsed)
        hold("subtle_alert", BOOL, ss.audio._subtle_alert_cb.active, apply_subtle)
        hold("disconnect_alert", BOOL, ss.audio._disconnect_alert_cb.active, apply_disconnect)
        add("threshold", INT, lambda: int(ss.threshold), set_threshold)
        add("use_mock", BOOL, lambda: APP.USE_MOCK_DEVICE, set_use_mock)
        hold("line_width", FLOAT, ss.display._line_width_slider.value, apply_line_width, settle=True)
        hold("rotation", INT, ss.display._current_rotation, apply_rotation)
        add("graph_zoom_seconds", FLOAT, self._saved_zoom_seconds, self._apply_saved_zoom)
        # audio_formula_index BEFORE audio_metric: metric reconciles the index when it's a slot.
        settings += self._audio_metric_settings()
        hold("feedback_source", STR, "noise", apply_feedback_source)
        hold("feedback_sound_path", STR, "", apply_feedback_path)
        hold("reward_source", STR, "none", apply_reward_source)  # the above-threshold channel: off by default
        hold("reward_sound_path", STR, "", apply_reward_path)
        add("marker_hotkey", STR, lambda: ss.display.marker_hotkey,
            lambda v: setattr(ss, "marker_hotkey", v))
        add("stats_view_mode", STR, lambda: getattr(ls, "_stats_mode", "live"),
            self._apply_stats_mode)
        # Its default is the seed, not the startup profile's theme the UI was built in.
        settings.append(theme_setting(self._theme_seed))
        settings.append(text_size_setting())
        settings.append(line_colours_setting())

        self._settings_store = SettingsStore(self._db, settings)

    def _audio_metric_settings(self) -> list[Setting]:
        """The metric that drives the sound and its formula slot; the slot first: the metric reconciles it."""

        def apply_audio_metric(v):
            if v in FORMULA_KEYS:
                self._settings_store.change("audio_formula_index", FORMULA_KEYS.index(v))
            self._show_audio_metric()

        def parse_slot(raw: str) -> int:
            return max(0, min(int(raw), len(FORMULA_KEYS) - 1))

        # A stored program slot heals to the baseline: outside a program it reads 0, constant max noise.
        return [Setting("audio_formula_index", 0, parse_slot, INT[1], None, lambda _v: None),  # shown with the metric
                Setting("audio_metric", "shamatha_score", self._baseline_audio_metric, self._baseline_audio_metric,
                        None, apply_audio_metric)]

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

        self._headset.load(user_id)  # after store.load, which applies use_mock

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
        self._power.refresh()
        if not self._gate.active():  # a first run offers it once the profile is picked (ProfileGate._finish_first_run)
            Clock.schedule_once(lambda _dt: self._power.offer_once(), 1.0)

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
        # in an unset state and no gate is already up, re-enter it rather than
        # resume usable with no user.
        # getattr guards keep this safe if on_resume fires before build() runs.
        gate = getattr(self, "_gate", None)
        if gate is not None and self._current_user_id is None and not gate.shown():
            gate.open(0)
            return
        try:
            Clock.schedule_once(lambda dt: self._refresh_ui_after_resume(), 0)
        except Exception:
            logger.exception("on_resume UI refresh failed")
        self._power.refresh()  # after the session's UI: back from the phone's settings, perhaps changed there

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
            self._shown.mirror.reload_into(self._live_screen)
            if self._shown.mirror.last_metrics:
                self._live_screen.update_stats(self._session_manager.live_score())
                self._live_screen.update_state(self._shown.mirror.last_state)
                self._live_screen.set_shamatha(self._run.shamatha_active)
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
        self._keep_awake.stop_service()  # a start still connecting has no session to stop it
        self._audio.cleanup()
        self._db.mark_shutting_down()
        self._db.close()
        logger.info("Application closed")
