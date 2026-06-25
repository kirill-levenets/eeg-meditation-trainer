import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime as _dt
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivy.uix.textinput import TextInput
from kivy.utils import platform as kivy_platform

from app.audio_feedback.noise import AudioEngine
from app.config import APP
from app.crash_handler import (
    flush_pre_app_errors,
    install_crash_handler,
    report_soft_error,
)
from app.eeg.mock_stream_v2 import MockEEGStream
from app.eeg.neurosky_stream import NeuroSkyStream
from app.logger import logger, timed
from app.metrics.custom_formula import CustomFormulaEvaluator
from app.metrics.engine import MetricsEngine
from app.metrics.noise_detector import PowerLineDetector
from app.session.manager import SessionManager, SessionState
from app.session.session_program import SessionProgram
from app.session.timer_state import TimerState
from app.storage import backup as _backup
from app.storage.backup import restore_backup, validate_backup
from app.storage.database import DatabaseManager, UserExistsError
from app.ui.diary_screen import DiaryScreen
from app.ui.history_screen import HistoryScreen
from app.ui.live_session import METRICS_COLORS, LiveSessionScreen
from app.ui.profile_screen import ProfileScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import BottomNav, C, F, Icons, S, StyledButton
from app.ui.widgets.legend import LegendBar
from app.ui.widgets.loading_overlay import LoadingOverlay
from app.ui.widgets.user_picker import UserPickerForm
from app.ui.wizard_screen import WizardScreen

FORMULA_KEYS: tuple[str, ...] = ("custom_formula", "custom_formula_2", "custom_formula_3")
_MAX_FORMULAS = len(FORMULA_KEYS)


class EEGMeditationApp(App):
    """Main Kivy application for EEG Meditation Trainer."""

    title = APP.APP_NAME
    icon = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "assets", "icons", "icon_128.png",
    )

    # Expose theme colors as app properties for kv language access
    @property
    def theme_bg_card(self):
        return C.BG_CARD

    @property
    def theme_text_secondary(self):
        return C.TEXT_SECONDARY

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
        self._tick_thread: Optional[threading.Thread] = None
        self._tick_stop_event: threading.Event = threading.Event()
        # Android pause state: when True, tick thread skips per-tick UI
        # work (graph add_point, stats updates) so a long screen-lock
        # doesn't accumulate thousands of Clock callbacks that flood the
        # main loop on resume (which previously caused a black screen).
        self._is_paused: bool = False
        self._metrics_buffer: list[dict] = []
        self._raw_buffer: list[dict] = []
        # Session-lifetime mirrors of what would have gone into the live
        # graphs. Tick thread appends to these regardless of pause state;
        # on resume we reload graphs from these in a single batch instead
        # of replaying N per-tick UI updates. Bounded by graph capacity.
        self._ui_metrics_history: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self._ui_band_history: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self._ui_raw_waveform: deque[float] = deque(maxlen=512 * 60)
        self._ui_last_metrics: dict = {}
        self._ui_last_state: str = "Neutral"
        self._flush_counter: int = 0
        self._current_session_id: Optional[int] = None
        self._current_user_id: Optional[int] = None
        self._init_formula_slots()
        self.serial_device_override: Optional[str] = None
        self._wake_lock = None
        self._active_program = None
        self._program_seg_idx: int = -1
        self._program_formula_ev = None
        self._session_program_active: bool = False

    def _init_formula_slots(self) -> None:
        """Three independent formula evaluators (one per slot) + their names."""
        self._formula_slots: list[CustomFormulaEvaluator] = [
            CustomFormulaEvaluator() for _ in range(_MAX_FORMULAS)
        ]
        self._formula_names: list[str] = [f"Custom {i + 1}" for i in range(_MAX_FORMULAS)]
        self._audio_formula_index: int = 0

    def _formula_for_key(self, key: str) -> CustomFormulaEvaluator | None:
        """Map a series key to its slot evaluator, or None for non-formula keys."""
        if key in FORMULA_KEYS:
            return self._formula_slots[FORMULA_KEYS.index(key)]
        return None

    def _apply_active_formulas(self, active: list[dict] | None) -> None:
        """Load an active_formulas list into the slots (names + formulas)."""
        active = active or []
        for i in range(_MAX_FORMULAS):
            entry = active[i] if i < len(active) and isinstance(active[i], dict) else {}
            self._formula_names[i] = entry.get("name") or f"Custom {i + 1}"
            self._formula_slots[i].set_formula(entry.get("formula", "") or "")

    def _persist_active_formulas(self, user_id: int) -> None:
        """Serialize all slots (names + formulas) to a single JSON key."""
        active = [
            {"name": self._formula_names[i], "formula": self._formula_slots[i].formula}
            for i in range(_MAX_FORMULAS)
        ]
        self._db.set_user_json_setting(user_id, "active_formulas", active)

    def _read_active_formulas_with_migration(self, user_id: int) -> list[dict]:
        """Return active_formulas if present, else seed slot 1 from the legacy scalar."""
        active = self._db.get_user_json_setting(user_id, "active_formulas")
        if isinstance(active, list):
            return active
        legacy = self._db.get_user_setting(user_id, "custom_formula")
        return [{"name": "Custom 1", "formula": legacy}] if legacy else []

    def _push_formula_names_to_graph(self) -> None:
        """Propagate slot display names to the live metrics graph's series labels."""
        for key, name in zip(FORMULA_KEYS, self._formula_names):
            self._live_screen.graph.set_series_name(key, name)

    def _session_custom_formulas_json(self) -> str:
        """JSON of the valid slots active this session, recorded at save for diary replay.

        `slot` is stored explicitly so a sparse set (e.g. only slots 0 and 2) replays
        onto the correct series keys instead of being packed densely and misaligned.
        """
        return json.dumps([
            {"slot": i,
             "name": self._formula_names[i],
             "formula": self._formula_slots[i].formula,
             "visible": self._live_screen.graph.is_visible(FORMULA_KEYS[i]),
             "drove_audio": self._audio_metric_key == FORMULA_KEYS[i]}
            for i in range(_MAX_FORMULAS) if self._formula_slots[i].is_valid
        ])

    def _persist_session_program(self, uid: int) -> None:
        """Persist the active editable program + timer mode for a user."""
        if not uid:
            return
        self._db.set_user_json_setting(uid, "session_program", self._session_program_segments)
        self._db.set_user_setting(uid, "timer_mode", self._timer_mode)

    def _load_session_program(self, uid: int) -> None:
        """Restore the active editable program + timer mode for a user."""
        self._session_program_segments = self._db.get_user_json_setting(
            uid, "session_program", default=[]
        ) or []
        self._timer_mode = self._db.get_user_setting(uid, "timer_mode") or "simple"

    def _build_session_program(self) -> SessionProgram:
        """Build a SessionProgram from the active editable segments."""
        return SessionProgram(self._session_program_segments)

    @staticmethod
    def _program_transition(prev_idx: int, elapsed: float, program):
        """Pure: (new_idx, segment, crossed). crossed=True when new_idx != prev_idx."""
        idx, seg = program.segment_at(elapsed)
        return (idx, seg, idx != prev_idx)

    def _eval_formula_vars(self, raw_sample: dict, metrics: dict) -> dict:
        """Variable dict for custom-formula evaluation (raw + metrics + derived/sqrt bands)."""
        fvars = {**raw_sample, **metrics}
        fvars.update(self._metrics_engine.derive_bands(raw_sample))
        sqrt_bands = self._metrics_engine.compute_sqrt_relative_bands(raw_sample)
        fvars.update({f"s_{k}": v for k, v in sqrt_bands.items()})
        return fvars

    def _apply_program_tick(self, metrics: dict, raw_sample: dict) -> None:
        """Per-tick program stepping: cross segments, fire cues, evaluate a custom segment formula.

        Runs on the daemon tick thread — only thread-safe state here (audio
        set_threshold/one-shot, SessionManager, pure evaluators). Kivy widget
        mutations are dispatched via _on_main.
        """
        prog = self._active_program
        if not prog:
            return
        elapsed = self._session_manager.elapsed_seconds
        idx, seg, crossed = self._program_transition(self._program_seg_idx, elapsed, prog)
        if seg is None:
            return
        if crossed:
            self._apply_program_segment(self._program_seg_idx, idx, seg)
            self._program_seg_idx = idx
        # A custom-formula segment is evaluated every tick into metrics["program_formula"].
        ev = self._program_formula_ev
        if ev is not None and ev.is_valid:
            fvars = self._eval_formula_vars(raw_sample, metrics)
            ev.push_variables(fvars)
            metrics["program_formula"] = ev.evaluate(fvars)

    def _apply_program_segment(self, prev_idx: int, idx: int, seg: dict) -> None:
        """On a boundary crossing: end-cue for the prior segment + repoint target/formula/audio."""
        # End cue for the segment that just ended (skip on initial entry prev_idx == -1).
        if prev_idx >= 0:
            prev_seg = self._active_program.segments[prev_idx]
            self._play_segment_end_sound(prev_seg.get("end_sound"))
        # Resolve the driving formula -> a metrics key. Custom formula gets its own evaluator.
        formula = seg.get("formula", "shamatha_score")
        self._program_formula_ev = None
        if isinstance(formula, dict):
            ev = CustomFormulaEvaluator()
            ok, err = ev.set_formula(formula.get("formula", "") or "")
            if ok and ev.is_valid:
                self._program_formula_ev = ev
                metric_key = "program_formula"
            else:
                metric_key = "shamatha_score"  # spec: unparseable saved formula falls back
                logger.warning(f"Program segment formula invalid, using shamatha: {err}")
        else:
            metric_key = formula or "shamatha_score"
        target = int(seg.get("target", 50))
        self._audio_metric_key = metric_key
        self._session_manager.set_active_goal(metric_key, target)
        self._audio.set_threshold(target)
        self._on_main(lambda t=target, k=metric_key:
                      self._live_screen.graph.set_threshold(float(t), k))
        logger.info(f"Program segment {idx}: metric={metric_key} target={target}")

    def _play_segment_end_sound(self, sound_id) -> None:
        """Segment-end cue. v1: chime (default) or 'warble'; richer choices land with #10."""
        try:
            if sound_id == "warble":
                self._audio.play_alert()
            else:
                self._audio.play_transition_cue()
        except Exception:
            logger.exception("Program segment end cue failed")

    def _session_program_json(self) -> str:
        """JSON of the program that ran this session (empty for a simple session)."""
        if self._session_program_active and self._session_program_segments:
            return json.dumps(self._session_program_segments)
        return ""

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

        # Restore saved theme before building UI
        saved_theme = self._db.get_setting("theme")
        if saved_theme:
            C.set_theme(saved_theme)

        # Apply --serial override if provided
        if self.serial_device_override:
            path = self.serial_device_override
            self._real_stream.set_device(path, f"Splitter ({path})")
            APP.USE_MOCK_DEVICE = False
            logger.info(f"Serial device override: {path}")

        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C.BG_DARK)
            self._root_bg = Rectangle(size=root.size, pos=root.pos)
        root.bind(
            size=lambda w, v: setattr(self._root_bg, "size", v),
            pos=lambda w, v: setattr(self._root_bg, "pos", v),
        )

        # --- Screen manager (all screens still exist, routed via nav) ---
        self._sm = ScreenManager(transition=SlideTransition())

        self._profile_screen = ProfileScreen()
        self._live_screen = LiveSessionScreen()
        self._settings_screen = SettingsScreen()
        self._history_screen = HistoryScreen()
        self._diary_screen = DiaryScreen()
        self._timer_state = TimerState()

        self._wizard_screen = WizardScreen()
        self._sm.add_widget(self._live_screen)
        self._sm.add_widget(self._wizard_screen)
        self._sm.add_widget(self._history_screen)
        self._sm.add_widget(self._settings_screen)
        self._sm.add_widget(self._profile_screen)
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
        self._fullscreen_overlay = None
        self._fullscreen_graph = None
        self._fullscreen_close = None  # _restore closure, set while fullscreen
        self._last_back_time = 0.0  # for double-back-to-exit on the root screen
        float_root.add_widget(root)
        self._loading_overlay = LoadingOverlay()
        float_root.add_widget(self._loading_overlay)

        self._bind_callbacks()
        self._link_graph_zoom()
        self._restore_last_user()
        self._refresh_profile()

        # First-run: show name entry popup if no users exist.
        # Uses a Popup instead of the wizard Screen because TextInput
        # inside a Screen doesn't get keyboard focus on some platforms.
        if not self._db.get_all_users():
            Clock.schedule_once(self._show_first_run_popup, 0.5)
        else:
            self._auto_scan_bt()

        return float_root

    def show_loading(self, text: str = "Loading…") -> None:
        """Show the app-global loading overlay (no-op before build)."""
        if getattr(self, "_loading_overlay", None) is not None:
            self._loading_overlay.show(text)

    def hide_loading(self) -> None:
        """Hide the app-global loading overlay (no-op before build)."""
        if getattr(self, "_loading_overlay", None) is not None:
            self._loading_overlay.hide()

    def _all_graphs(self) -> tuple:
        """Every mounted ScrollableGraphWidget — the single source of truth for
        the cross-graph affordances (expand, series picker, zoom-link, restore)."""
        return (
            self._live_screen.graph,
            self._live_screen.raw_graph,
            self._live_screen.band_graph,
            self._diary_screen._metrics_graph,
            self._diary_screen._raw_eeg_graph,
            self._diary_screen._freq_graph,
        )

    def _wire_graph_affordances(self) -> None:
        """Give every mounted graph the shared fullscreen-expand and series-picker
        glyphs, driven by one presenter each. The picker is wired only where there
        is more than one series to choose from — a single-series graph's picker
        could only blank the line."""
        for g in self._all_graphs():
            g.set_expand_callback(self._present_graph_fullscreen)
            if len(g.series_keys()) > 1:
                g.set_series_picker_callback(self._present_series_picker)

    def _present_graph_fullscreen(self, graph) -> None:
        """Reparent `graph` into a full-window overlay; restore it on close.

        Reparenting (not cloning) keeps the widget's single Window bind and its
        live add_point feed, so a live graph keeps updating in fullscreen. A
        plain root overlay (not a Popup) is used so the graph reaches every
        edge — a Popup insets its content with title/border chrome.
        """
        parent = graph.parent
        if parent is None or getattr(self, "_fullscreen_overlay", None) is not None:
            return
        index = parent.children.index(graph)
        # Copy these — size_hint/size are live ReferenceListProperties; a bare
        # reference would track the (1,1) we set below and break restore.
        orig_size_hint = list(graph.size_hint)
        orig_pos_hint = dict(graph.pos_hint)
        orig_size = list(graph.size)

        overlay = FloatLayout(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        with overlay.canvas.before:
            Color(*C.BG_DARK)
            bg = Rectangle(size=overlay.size, pos=overlay.pos)
        overlay.bind(
            size=lambda w, v: setattr(bg, "size", v),
            pos=lambda w, v: setattr(bg, "pos", v),
        )

        # Hide only the expand glyph while fullscreen (already fullscreen); keep
        # the series picker so the user can change series here too.
        graph.set_expand_callback(None)
        parent.remove_widget(graph)
        graph.size_hint = (1, 1)
        graph.pos_hint = {}
        # graph + legend stacked, so the fullscreen view keeps its legend.
        content = BoxLayout(orientation="vertical", spacing=dp(4))
        content.add_widget(graph)
        self._fullscreen_content = content
        self._fullscreen_legend = self._build_fullscreen_legend(graph)
        content.add_widget(self._fullscreen_legend)
        overlay.add_widget(content)

        close_btn = StyledButton(
            icon=Icons.CLOSE_CIRCLE_OUTLINE, font_size=dp(30),
            size_hint=(None, None), size=(dp(48), dp(48)),
            pos_hint={"right": 0.99, "top": 0.99},
            bg_color=[0, 0, 0, 0], bg_pressed=[0, 0, 0, 0],
            text_color=list(C.TEXT),
        )
        # StyledButton hard-sets horizontal padding (12dp) which would crop the
        # circular glyph; the icon needs the button's full width.
        close_btn.padding = [0, 0]
        overlay.add_widget(close_btn)
        self._float_root.add_widget(overlay)
        self._fullscreen_overlay = overlay
        self._fullscreen_graph = graph

        def _restore(*_a):
            self._fullscreen_close = None
            self._float_root.remove_widget(overlay)
            if graph.parent is not None:
                graph.parent.remove_widget(graph)
            graph.size_hint = orig_size_hint
            graph.pos_hint = orig_pos_hint
            graph.size = orig_size
            parent.add_widget(graph, index=index)
            graph.set_expand_callback(self._present_graph_fullscreen)
            graph._redraw()
            self._fullscreen_overlay = None
            self._fullscreen_content = None
            self._fullscreen_legend = None
            self._fullscreen_graph = None

        self._fullscreen_close = _restore
        close_btn.bind(on_release=_restore)

    def _build_fullscreen_legend(self, graph):
        """A wrapping legend (colored names) for the currently visible series."""
        legend = LegendBar()
        legend.set_items([
            (graph.series_name(key), graph.series_color(key))
            for key in graph.visible_keys()
        ])
        return legend

    def _link_graph_zoom(self) -> None:
        """Link zoom across all graph widgets so they share the same time scale."""
        ScrollableGraphWidget.link_zoom(*self._all_graphs())

    def _bind_callbacks(self) -> None:
        # Wizard
        self._wizard_screen.set_complete_callback(self._on_wizard_complete)
        self._wizard_screen.set_scan_callback(self._on_wizard_scan)
        self._wizard_screen.set_pick_existing_callback(
            lambda uid: self._on_pick_existing_user(uid, source="wizard"),
        )
        self._wizard_screen.populate_existing_users(self._db.get_all_users())

        self._live_screen.btn_start.bind(on_release=self._on_start)
        self._live_screen.btn_pause.bind(on_release=self._on_pause)
        self._live_screen.btn_stop.bind(on_release=self._on_stop)
        self._live_screen.btn_marker.bind(on_release=self._on_marker)
        self._live_screen.on_duration_preset = self._on_duration_preset
        self._live_screen.overlay_cancel_btn.bind(on_release=self._on_connect_cancel)
        self._live_screen.overlay_retry_btn.bind(on_release=self._on_connect_retry)
        self._live_screen.summary_save_btn.bind(on_release=self._on_summary_save)
        self._live_screen.summary_history_btn.bind(on_release=self._on_summary_history)
        self._live_screen.summary_close_btn.bind(on_release=self._on_summary_close)

        # Tap on graph to set marker (Android — no keyboard available)
        if kivy_platform == "android":
            self._live_screen.graph.set_tap_callback(self._on_marker)

        # Shared fullscreen-expand + series-picker glyphs on every graph
        self._wire_graph_affordances()

        self._settings_screen.set_threshold_callback(self._on_threshold_change)
        self._settings_screen.set_test_audio_callback(self._on_test_audio)
        self._settings_screen.set_sinking_alert_callback(self._on_sinking_alert_toggle)
        self._settings_screen.set_subtle_alert_callback(self._on_subtle_alert_toggle)
        self._settings_screen.set_disconnect_alert_callback(self._on_disconnect_alert_toggle)
        self._settings_screen.set_device_mode_callback(self._on_device_mode_toggle)
        self._settings_screen.set_scan_devices_callback(self._on_scan_devices)
        self._settings_screen.set_device_select_callback(self._on_device_select)
        self._settings_screen.set_copy_diagnostics_callback(self._on_copy_diagnostics)
        self._settings_screen.set_line_width_callback(self._on_line_width_change)
        self._settings_screen.set_rotate_screen_callback(self._on_rotate_screen)
        self._settings_screen.set_formula_slot_callback(self._on_formula_slot_change)
        self._settings_screen.set_save_formula_callback(self._on_save_formula)
        self._settings_screen.set_load_formula_callback(self._on_load_formula)
        self._settings_screen.set_delete_formula_callback(self._on_delete_formula)
        self._settings_screen.set_export_formulas_callback(self._on_export_formulas)
        self._settings_screen.set_audio_metric_callback(self._on_audio_metric_change)
        self._settings_screen.set_audio_formula_index_callback(self._on_audio_formula_index)
        self._settings_screen.set_program_mode_callback(self._on_timer_mode_change)
        self._settings_screen.set_program_changed_callback(self._on_program_changed)
        self._settings_screen.set_program_save_callback(self._on_program_save)
        self._settings_screen.set_program_load_callback(self._on_program_load)
        self._settings_screen.set_program_delete_callback(self._on_program_delete)
        self._settings_screen.set_theme_callback(self._on_theme_change)

        # Keyboard hotkey for marker
        Window.bind(on_key_down=self._on_key_down)
        # Android hardware back button (key 27) — consume it so Kivy's default
        # exit-on-escape doesn't fire; navigate / double-tap-to-exit instead.
        Window.bind(on_keyboard=self._on_keyboard)

        # Hide all custom-formula series until a formula is set + shown via picker
        for _fk in FORMULA_KEYS:
            self._live_screen.graph.set_visible(_fk, False)
        # Apply default metric visibility (Shamatha only for new users;
        # _load_user_settings will override for existing users)
        for key, active in self._settings_screen._graph_toggles.items():
            self._live_screen.graph.set_visible(key, active)
        self._audio_metric_key: str = "shamatha_score"
        self._session_program_segments: list[dict] = []
        self._timer_mode: str = "simple"

        self._diary_screen.set_session_select_callback(self._on_session_select)
        self._diary_screen.set_save_notes_callback(self._on_save_notes)
        self._diary_screen.set_export_csv_callback(self._on_export_csv)
        self._diary_screen.set_delete_session_callback(self._on_delete_session)
        self._diary_screen.set_rename_session_callback(self._on_rename_session)
        self._diary_screen.set_back_callback(self._on_diary_back)

        self._history_screen.set_callbacks(
            on_session_select=self._on_session_select,
            on_save_notes=self._on_save_notes,
            on_delete_session=self._on_delete_session,
            on_export_csv=self._on_export_csv,
            on_rename_session=self._on_rename_session,
        )
        self._history_screen.set_view_mode_callback(
            self._on_history_view_mode_change,
        )

        self._settings_screen.set_test_timer_sound_callback(self._on_test_timer_sound)
        self._settings_screen.set_stop_timer_sound_callback(self._on_stop_test_timer_sound)
        self._settings_screen.set_timer_sound_change_callback(
            self._timer_state.set_custom_sound_path
        )

        self._profile_screen.set_user_switch_callback(self._on_user_switch)
        self._profile_screen.set_user_create_callback(self._on_user_create)
        self._profile_screen.set_user_delete_callback(self._on_user_delete)

        # Profile section in settings
        self._settings_screen.set_profile_callbacks(
            on_switch=self._on_user_switch,
            on_create=self._on_user_create,
            on_delete=self._on_user_delete,
        )
        self._settings_screen.set_session_counter(self._count_sessions_for_user)

        # Data Backup section
        self._settings_screen.set_backup_callback(self._on_backup_pressed)
        self._settings_screen.set_restore_callback(self._on_restore_pressed)

    def _restore_last_user(self) -> None:
        """Restore last selected user from DB settings on startup."""
        saved = self._db.get_setting("last_user_id")
        if saved:
            try:
                uid = int(saved)
                user = self._db.get_user(uid)
                if user:
                    self._current_user_id = uid
                    self._load_user_settings(uid)
                    logger.info(f"Restored last user: {user['name']} (id={uid})")
            except (ValueError, TypeError):
                pass

    def _show_first_run_popup(self, dt) -> None:
        """Show a name-entry popup on first run (no users in DB).

        After uninstall→reinstall on Android, the DB may persist with
        existing profiles — UserPickerForm surfaces them so the user can
        adopt instead of creating a duplicate name.
        """

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))

        welcome = Label(
            text="Welcome! Create a profile or pick an existing one:",
            font_size=F.BODY, color=C.TEXT,
            size_hint_y=None, height=dp(48),
            halign="center",
        )
        welcome.bind(size=welcome.setter("text_size"))
        content.add_widget(welcome)

        popup = Popup(
            title="First-time Setup",
            content=content,
            size_hint=(0.9, 0.7),
            auto_dismiss=False,
        )

        def _on_create(name: str) -> None:
            popup.dismiss()
            self._on_wizard_complete(name, None, None)

        def _on_pick(user_id: int) -> None:
            popup.dismiss()
            self._on_pick_existing_user(user_id, source="first_run")

        form = UserPickerForm(
            on_create=_on_create,
            on_pick_existing=_on_pick,
        )
        existing_users = self._db.get_all_users()
        form.populate_users(existing_users)
        content.add_widget(form)

        # Stash form so duplicate-error routing can find it
        self._first_run_form = form
        popup.open()

    def _on_wizard_complete(self, user_name: str, device_addr, device_name) -> None:
        """Wizard finished: create user, optionally set device, go to session."""
        if not user_name or len(user_name.strip()) < 2:
            logger.warning(f"Wizard complete with invalid name: '{user_name}', ignoring")
            return
        # Create user (or adopt an existing one with the same name)

        try:
            uid = self._db.create_user(user_name)
            self._current_user_id = uid
            self._db.set_setting("last_user_id", str(uid))
        except UserExistsError as e:
            self._current_user_id = e.user_id
            self._db.set_setting("last_user_id", str(e.user_id))
            logger.info(f"Wizard: adopting existing user {e.name} (id={e.user_id})")

        # Set device
        if device_addr:
            self._real_stream.set_device(device_addr, device_name or device_addr)
            APP.USE_MOCK_DEVICE = False
            if self._current_user_id:
                self._db.set_user_setting(self._current_user_id, "bt_device_address", device_addr)
                self._db.set_user_setting(self._current_user_id, "bt_device_name", device_name or "")
                self._db.set_user_setting(self._current_user_id, "use_mock", "False")
            self._settings_screen._device_mode_cb.active = False
            self._live_screen.update_device_status(False, device_name=device_name or device_addr)
            logger.info(f"Wizard: device set to {device_name} ({device_addr})")
        else:
            APP.USE_MOCK_DEVICE = True
            if self._current_user_id:
                self._db.set_user_setting(self._current_user_id, "use_mock", "True")
            self._settings_screen._device_mode_cb.active = True
            self._live_screen.update_device_status(False, device_name="Mock EEG")
            logger.info("Wizard: using mock device")

        # Show nav and go to session
        self._bottom_nav.opacity = 1
        self._bottom_nav.disabled = False
        self._refresh_profile()
        self._sm.current = "live_session"
        self._bottom_nav.active_tab = "session"
        self._auto_scan_bt()
        logger.info(f"Wizard complete: user '{user_name}' created")

    def _on_wizard_scan(self) -> None:
        """Scan for BT devices from wizard."""

        def _run():
            devices = NeuroSkyStream.scan_paired_devices()
            Clock.schedule_once(lambda dt: self._wizard_screen.populate_devices(devices))

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _filter_mindwave(devices: list) -> list:
        """Subset of `devices` whose name looks like a NeuroSky MindWave."""
        out = []
        for dev in devices:
            name = (dev.get("name") or "").lower()
            if "mindwave" in name or "neurosky" in name:
                out.append(dev)
        return out

    def _auto_scan_bt(self) -> None:
        """Background-scan paired BT devices at startup and auto-select MindWave."""
        if self.serial_device_override:
            return
        if self._real_stream._device_address:
            # Already have a saved device from user settings
            return

        def _scan_thread():
            return NeuroSkyStream.scan_paired_devices()

        def _on_scan_done(devices):
            if not devices:
                return
            matches = self._filter_mindwave(devices)
            if len(matches) == 1:
                self._on_device_select(matches[0]["address"], matches[0]["name"])
                logger.info(f"Auto-selected BT device: {matches[0]['name']}")
                return
            if len(matches) > 1:
                # Multiple NeuroSky devices paired — user must choose explicitly.
                logger.info(
                    f"Found {len(matches)} MindWave devices — routing to settings picker"
                )
                self._settings_screen.populate_bt_devices(matches)
                self._switch_screen("settings")
                self._settings_screen.focus_device_section(
                    f"Found {len(matches)} MindWave devices.\n"
                    "Pick the one you want to use."
                )
                return
            # No MindWave found — populate settings list for manual pick
            self._settings_screen.populate_bt_devices(devices)


        def _run():
            try:
                devices = _scan_thread()
                Clock.schedule_once(lambda dt: _on_scan_done(devices))
            except Exception as e:
                logger.warning(f"Auto-scan failed: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_nav_tab(self, tab_key: str) -> None:
        """Handle bottom nav tab press."""
        screen_name = self._TAB_SCREENS.get(tab_key, tab_key)
        self._switch_screen(screen_name)

    def _switch_screen(self, name: str) -> None:
        if name == "diary" and not self._current_user_id:
            logger.debug("Diary switch blocked: no user selected")
            return
        logger.debug(f"Screen switch: {name}")
        self._sm.current = name
        if name == "history":
            self._refresh_history()
        elif name == "diary":
            self._refresh_diary()
        elif name == "profile":
            self._refresh_profile()
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
            matches = self._filter_mindwave(devices)

            def _on_main_thread(dt):
                if len(matches) == 1:
                    mindwave = matches[0]
                    self._on_device_select(mindwave["address"], mindwave["name"])
                    self._eeg_stream = self._real_stream
                    self._live_screen.update_overlay(
                        f"Found {mindwave['name']}\nConnecting..."
                    )
                    self._start_session_common()
                elif len(matches) > 1:
                    # Multiple NeuroSky devices paired — user must pick.
                    self._settings_screen.populate_bt_devices(matches)
                    self._live_screen.set_controls_idle()
                    self._live_screen.hide_overlay()
                    self._switch_screen("settings")
                    self._settings_screen.focus_device_section(
                        f"Found {len(matches)} MindWave devices.\n"
                        "Pick the one you want to use, then press Start again."
                    )
                elif devices:
                    # Found BT devices but no MindWave
                    self._settings_screen.populate_bt_devices(devices)
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

    # ------------------------------------------------------------------
    # Background tick thread (replaces Clock.schedule_interval so that
    # compute / audio / DB work continues while Android screen is locked)
    # ------------------------------------------------------------------

    def _on_main(self, fn) -> None:
        """Queue callable on Kivy's main thread.

        Thread-safe per Kivy docs.  During Kivy pause (screen locked) the
        call is buffered and executed when the app resumes.
        """
        Clock.schedule_once(lambda dt: fn(), 0)

    def _start_tick_thread(self) -> None:
        """Start the 2 Hz tick loop in a background daemon thread.

        Survives Kivy pause (Android screen lock) because it runs outside
        the UI thread.
        """
        self._tick_stop_event.clear()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="SessionTick"
        )
        self._tick_thread.start()
        logger.debug("SessionTick thread started")

    def _stop_tick_thread(self) -> None:
        """Signal the tick thread to exit and join briefly.

        Safe to call from the tick thread itself: skips join() in that case
        (joining the current thread raises RuntimeError, which would swallow
        the rest of the calling tick — that bug caused the connect-overlay
        countdown to freeze when BT failure paths called this from inside
        _handle_bt_wait).
        """
        self._tick_stop_event.set()
        t = self._tick_thread
        self._tick_thread = None
        if (
            t is not None
            and t.is_alive()
            and t is not threading.current_thread()
        ):
            t.join(timeout=1.0)
        logger.debug("SessionTick thread stopped")

    def _tick_loop(self) -> None:
        """Daemon-thread loop: call _update_tick every UPDATE_FREQUENCY seconds."""
        interval = APP.UPDATE_FREQUENCY
        next_t = time.monotonic()
        while not self._tick_stop_event.is_set():
            try:
                self._update_tick(interval)
            except Exception:
                logger.exception("Error in session tick loop")
            next_t += interval
            remaining = next_t - time.monotonic()
            if remaining > 0:
                if self._tick_stop_event.wait(remaining):
                    break
            else:
                next_t = time.monotonic()

    # ------------------------------------------------------------------

    def _start_session_common(self) -> None:
        """Shared session startup logic after device is resolved."""
        # If the user starts a new session while a long custom timer bell
        # from the previous session is still ringing, kill it so it
        # doesn't overlap with the new session's noise loop.
        self._audio.stop_timer_bell()
        threshold = self._settings_screen.threshold
        prog = self._build_session_program()
        self._program_seg_idx = -1
        self._program_formula_ev = None
        self._session_program_active = self._timer_mode == "program" and bool(prog)
        self._active_program = prog if self._session_program_active else None
        if self._session_program_active:
            # Program total drives the timer so auto-stop reuses the proven
            # timer-expiry path; the first segment's target seeds the threshold.
            threshold = int(prog.segments[0].get("target", threshold))
            self._timer_state.set_enabled(True)
            self._timer_state.set_duration(max(1, int(round(prog.total_seconds / 60))))
        self._metrics_engine.meditation_threshold = threshold
        self._audio.set_threshold(threshold)
        self._metrics_engine.reset()
        self._noise_detector = PowerLineDetector() if not APP.USE_MOCK_DEVICE else None
        self._metrics_buffer = []
        self._raw_buffer = []
        self._ui_metrics_history.clear()
        self._ui_band_history.clear()
        self._ui_raw_waveform.clear()
        self._ui_last_metrics = {}
        self._ui_last_state = "Neutral"
        self._flush_counter = 0
        self._tick_count = 0
        self._current_session_id = None
        self._bt_connected_notified = False
        self._pending_marker = False
        self._bt_connect_start = time.time()

        self._live_screen.graph.clear_data()
        self._live_screen.raw_graph.clear_data()
        self._live_screen.band_graph.clear_data()
        if self._session_program_active:
            self._live_screen.graph.set_threshold_steps(
                prog.threshold_steps(self._live_screen.graph._sample_rate)
            )
        else:
            self._live_screen.graph.set_threshold_steps(None)
            self._live_screen.graph.set_threshold(float(threshold), "shamatha_score")
        self._live_screen.hide_alert()
        self._live_screen.set_controls_running()

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
            self._live_screen.set_start_time(time.time())
            self._live_screen.hide_overlay()
        elif self._real_stream.is_connected:
            # BT still connected from previous session — reuse it
            self._real_stream.reset_sample_state()
            self._waiting_for_bt = False
            name = self._real_stream._device_name or "Real EEG"
            self._session_manager.start(threshold=threshold)
            self._audio.start()
            self._audio.play_connect_sound()
            self._timer_state.start_countdown()
            self._live_screen.update_device_status(True, device_name=name)
            self._live_screen.update_state("Running")
            self._live_screen.set_start_time(time.time())
            self._live_screen.hide_overlay()
            logger.info(f"Reusing existing BT connection to {name}")
        else:
            self._eeg_stream.start()
            self._waiting_for_bt = True
            self._pending_threshold = threshold
            name = self._real_stream._device_name or "Real EEG"
            self._live_screen.update_device_status(
                False, device_name=name, connecting=True
            )
            self._live_screen.show_overlay(
                f"Connecting to {name}..."
            )
            logger.info(f"Waiting for BT connection to {name}")

        self._start_tick_thread()
        self._tick_count = 0
        logger.info("Session started via UI")

    def _on_connect_cancel(self, *args) -> None:
        """Cancel button on connection overlay."""
        self._live_screen.hide_overlay()
        if self._waiting_for_bt or self._tick_thread is not None:
            self._real_stream.stop()
            self._waiting_for_bt = False
            self._stop_tick_thread()
            self._release_wake_lock()
            self._stop_session_keep_alive_service()
        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._live_screen.update_state("IDLE")

    def _on_connect_retry(self, *args) -> None:
        """Retry button on connection overlay."""
        self._live_screen.hide_overlay()
        self._live_screen.set_controls_idle()
        self._on_start()

    def _on_summary_save(self, *args) -> None:
        """Save notes from summary overlay."""
        self._audio.stop_timer_bell()
        sid = self._live_screen.summary_session_id
        notes = self._live_screen.summary_notes
        if sid and notes:
            self._db.update_session_notes(sid, notes)
            self._mark_history_dirty()
            logger.info(f"Quick notes saved for session {sid}")
        self._live_screen.hide_summary()

    def _on_summary_history(self, *args) -> None:
        """Navigate to history from summary."""
        self._audio.stop_timer_bell()
        self._live_screen.hide_summary()
        self._switch_screen("history")

    def _on_summary_close(self, *args) -> None:
        """Close summary without saving notes."""
        self._audio.stop_timer_bell()
        self._live_screen.hide_summary()

    def _on_pause(self, *args) -> None:
        if self._session_manager.state == SessionState.RUNNING:
            self._session_manager.pause()
            self._live_screen.set_controls_paused()
            self._audio.stop()
            self._stop_tick_thread()
            logger.info("Session paused")
        elif self._session_manager.state == SessionState.PAUSED:
            self._session_manager.resume()
            self._live_screen.set_controls_running()
            self._audio.start()
            self._start_tick_thread()
            logger.info("Session resumed")

    def _on_stop(self, *args) -> None:
        # If still waiting for BT, session never started — just clean up
        if getattr(self, '_waiting_for_bt', False):
            self._stop_tick_thread()
            self._waiting_for_bt = False
            self._eeg_stream.stop()
            self._live_screen.set_controls_idle()
            self._live_screen.update_device_status(False)
            self._live_screen.update_state("Cancelled")
            self._timer_state.reset()
            self._release_wake_lock()
            self._stop_session_keep_alive_service()
            logger.info("Session cancelled during BT connection wait")
            return

        # Pause the tick thread while the dialog is open
        self._stop_tick_thread()

        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
        content.add_widget(Label(
            text="Save session data?",
            font_size=dp(16),
            halign="center",
        ))
        btn_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        btn_save = Button(
            text="Save", font_size=dp(15), bold=True,
            background_color=(0.2, 0.7, 0.3, 1.0),
        )
        btn_discard = Button(
            text="Discard", font_size=dp(15), bold=True,
            background_color=(0.8, 0.2, 0.2, 1.0),
        )
        btn_cancel = Button(
            text="Cancel", font_size=dp(15),
            background_color=(0.3, 0.3, 0.4, 1.0),
        )
        btn_row.add_widget(btn_save)
        btn_row.add_widget(btn_discard)
        btn_row.add_widget(btn_cancel)
        content.add_widget(btn_row)

        popup = Popup(
            title="Stop Session",
            content=content,
            size_hint=(0.7, 0.3),
            auto_dismiss=False,
        )
        btn_save.bind(on_release=lambda x: self._finish_stop(popup, save=True))
        btn_discard.bind(on_release=lambda x: self._finish_stop(popup, save=False))
        btn_cancel.bind(on_release=lambda x: self._cancel_stop(popup))
        popup.open()

    def _make_session_name(self) -> str:
        """Generate default session name including device type."""
        device = "Mock" if APP.USE_MOCK_DEVICE else (
            self._real_stream._device_name or "Real EEG"
        )
        ts = time.strftime("%H:%M")
        return f"{ts} - {device}"

    def _persist_session_data(self, reason: str) -> dict:
        """Stop the session and write final stats + metrics to the DB.

        Tick-thread-safe: contains NO Kivy/UI calls so it can run directly on
        the daemon tick thread at timer expiry. That makes the finished session
        durable even if Android kills the app during a screen lock before the
        user unlocks — the main-thread Clock (and `_on_main`) is paused while
        locked, so deferring the save risked losing the whole session.
        """
        stats = self._session_manager.stop(reason=reason)
        # Keep real BT connection alive between sessions to avoid EBUSY on reconnect.
        # Only the mock stream gets stopped here; real stream stays connected.
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.stop()

        if stats:
            if self._current_session_id is not None:
                self._db.update_session(
                    self._current_session_id, stats,
                    custom_formulas=self._session_custom_formulas_json(),
                    session_program=self._session_program_json(),
                )
            else:
                self._current_session_id = self._db.save_session(
                    stats, user_id=self._current_user_id,
                    session_name=self._make_session_name(),
                    custom_formulas=self._session_custom_formulas_json(),
                    session_program=self._session_program_json(),
                )
            if self._metrics_buffer:
                self._db.save_metrics_batch(self._current_session_id, self._metrics_buffer)
                self._metrics_buffer = []
        return stats

    def _reload_live_graphs_from_mirror(self) -> None:
        """Batch-reload the 3 live graphs from the session-lifetime mirror
        buffers (one load_static_data per graph). Used on Android resume and on
        session finish: during a screen lock the per-tick add_point is skipped
        (mirror buffers fill instead), so without this the live graph would
        show only the pre-lock portion of the session."""
        metrics_snapshot = list(self._ui_metrics_history)
        band_snapshot = list(self._ui_band_history)
        waveform_snapshot = list(self._ui_raw_waveform)
        if metrics_snapshot:
            metric_series = {
                key: [d.get(key, 0.0) for d in metrics_snapshot]
                for key in METRICS_COLORS
            }
            self._live_screen.graph.load_static_data(metric_series)
        if band_snapshot:
            band_keys = ("alpha", "beta", "gamma", "theta", "delta")
            band_series = {
                key: [d.get(key, 0.0) for d in band_snapshot]
                for key in band_keys
            }
            self._live_screen.band_graph.load_static_data(band_series)
        if waveform_snapshot:
            self._live_screen.raw_graph.load_static_data({"eeg": waveform_snapshot})

    def _finalize_stop_ui(self, stats: dict, session_id: Optional[int]) -> None:
        """Main-thread UI teardown after a session has been persisted."""
        # Reload the live graph from the mirror buffers so it shows the FULL
        # session (the locked portion never reached the live graph via the
        # per-tick path). Otherwise closing the summary reveals a stale graph
        # covering only the pre-lock seconds while History shows the real
        # duration.
        try:
            self._reload_live_graphs_from_mirror()
        except Exception:
            logger.exception("graph reload on stop failed")
        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._live_screen.update_state("FINISHED")
        # Sync the header timer to the final duration (it froze at lock time).
        if stats:
            secs = int(stats.get("duration", 0))
            self._live_screen.update_timer(f"{secs // 60:02d}:{secs % 60:02d}")
        self._timer_state.reset()
        self._session_manager.reset()
        self._release_wake_lock()
        self._stop_session_keep_alive_service()
        self._mark_history_dirty()
        if stats and session_id:
            self._live_screen.show_summary(session_id, stats)

    def _stop_and_save(self, reason: str = "user") -> None:
        """Stop session and save data immediately (no dialog). Main-thread path."""
        t_start = time.monotonic()
        self._stop_tick_thread()
        stats = self._persist_session_data(reason)
        self._audio.stop()
        self._finalize_stop_ui(stats, self._current_session_id)
        logger.info(
            f"Session stopped and saved (took {time.monotonic() - t_start:.3f}s)"
        )

    def _cancel_stop(self, popup) -> None:
        """Resume the session after cancelling stop."""
        popup.dismiss()
        self._start_tick_thread()
        logger.info("Stop cancelled, session resumed")

    def _finish_stop(self, popup, save: bool) -> None:
        """Finish stopping the session, optionally saving data."""
        popup.dismiss()

        stats = self._session_manager.stop(reason="user")
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.stop()
        self._audio.stop()

        if save and stats:
            if self._current_session_id is not None:
                self._db.update_session(
                    self._current_session_id, stats,
                    custom_formulas=self._session_custom_formulas_json(),
                    session_program=self._session_program_json(),
                )
            else:
                self._current_session_id = self._db.save_session(
                    stats, user_id=self._current_user_id,
                    session_name=self._make_session_name(),
                    custom_formulas=self._session_custom_formulas_json(),
                    session_program=self._session_program_json(),
                )
            if self._metrics_buffer:
                self._db.save_metrics_batch(self._current_session_id, self._metrics_buffer)
                self._metrics_buffer = []
            logger.info("Session stopped and saved")
        else:
            # Discard: delete partially flushed data if any
            if self._current_session_id is not None:
                self._db.delete_session(self._current_session_id)
                logger.info(f"Session {self._current_session_id} discarded")
            self._metrics_buffer = []
            logger.info("Session stopped, data discarded")

        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._live_screen.update_state("FINISHED")
        self._timer_state.reset()
        self._session_manager.reset()
        self._release_wake_lock()
        self._stop_session_keep_alive_service()
        self._mark_history_dirty()

        if save and stats and self._current_session_id:
            self._live_screen.show_summary(self._current_session_id, stats)

    _BT_CONNECT_TIMEOUT = 30.0  # seconds before BT socket gives up
    _BT_SIGNAL_TIMEOUT = 8.0   # seconds to wait for EEG packets after connected
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

    def _handle_bt_wait(self) -> None:
        """Handle the BT connection wait phase (called from _update_tick).

        Runs on the background tick thread — all Kivy UI calls are dispatched
        via _on_main so they execute safely on the main thread.
        """
        elapsed = time.time() - self._bt_connect_start
        name = self._real_stream._device_name or "Real EEG"

        if self._real_stream.is_connected:
                # BT socket connected — waiting for actual EEG data
                if not getattr(self, '_bt_signal_start', None):
                    self._bt_signal_start = time.time()
                signal_elapsed = time.time() - self._bt_signal_start
                signal_remaining = int(self._BT_SIGNAL_TIMEOUT - signal_elapsed)

                raw_sample = self._eeg_stream.read_sample()
                sq = raw_sample.get("signal_quality", 200)
                total = sum(raw_sample.get(k, 0.0) for k in
                            ("delta", "theta", "alpha1", "alpha2",
                             "beta1", "beta2", "gamma1", "gamma2"))

                # Check if headset is actually streaming packets
                has_packets = self._real_stream.seconds_since_last_packet > 0

                if total > 0:
                    self._waiting_for_bt = False
                    self._bt_signal_start = None
                    self._session_manager.start(
                        threshold=self._pending_threshold
                    )
                    # Arm the countdown on THIS thread before the next tick()
                    # reads it. Deferring it via _on_main let a stalled main
                    # thread leave remaining_seconds=0, so the very next tick
                    # fired the timer instantly — a 0s "timer-ended" session.
                    self._timer_state.start_countdown()
                    _n = name
                    self._on_main(lambda n=_n: (
                        self._live_screen.update_device_status(True, device_name=n),
                        self._live_screen.update_state("Running"),
                        self._live_screen.set_start_time(time.time()),
                        self._live_screen.hide_overlay(),
                        self._settings_screen.update_device_status(True, name=n),
                        # Start audio on the main thread together with hiding the
                        # overlay, so white-noise never plays while the connecting
                        # loader is still visible (previously non-atomic: audio
                        # started on the tick thread, overlay hide was deferred).
                        self._audio.start(),
                        self._audio.play_connect_sound(),
                    ))
                    logger.info(f"BT device {name} connected, session started")
                elif signal_elapsed > self._BT_SIGNAL_TIMEOUT and not has_packets:
                    # No packets — ThinkGear didn't start streaming.
                    # Don't try RFCOMM reconnect: closing the socket triggers
                    # EBUSY that blocks reconnection for 60+ seconds.
                    # The only reliable fix is a headset power cycle.
                    self._waiting_for_bt = False
                    self._bt_signal_start = None
                    self._real_stream.stop()
                    self._stop_tick_thread()
                    _n = name
                    self._on_main(lambda n=_n: (
                        self._live_screen.set_controls_idle(),
                        self._live_screen.update_device_status(False, device_name=n),
                        self._live_screen.show_overlay_retry(
                            "No EEG data received.\n"
                            "Check battery or restart headset."
                        ),
                    ))
                    self._release_wake_lock()
                    self._stop_session_keep_alive_service()
                    logger.error("No ThinkGear packets — likely low battery or needs power cycle")
                else:
                    # Show signal quality feedback (keep waiting if packets arrive)
                    if sq == 200:
                        sensor_info = "Sensor: no contact"
                    elif sq > 50:
                        sensor_info = f"Sensor: poor (quality {sq})"
                    elif sq > 0:
                        sensor_info = f"Sensor: fair (quality {sq})"
                    else:
                        sensor_info = "Sensor: good"
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
                    _msg = f"Connected to {name}\n{wait_msg}\n{sensor_info}"
                    self._on_main(lambda m=_msg: self._live_screen.update_overlay(m))
        elif not self._real_stream._running:
            # Connection thread ended with error
            self._waiting_for_bt = False
            self._bt_signal_start = None
            self._stop_tick_thread()
            hint = self._real_stream._last_connect_error or "Check device is on and paired."
            _n = name
            _h = hint
            self._on_main(lambda n=_n, h=_h: (
                self._live_screen.set_controls_idle(),
                self._live_screen.update_device_status(False),
                self._live_screen.show_overlay_retry(
                    f"Connection to {n} failed.\n{h}"
                ),
            ))
            logger.error("BT connection failed, session aborted")
            self._report_bt_connect_failure(name, hint)
        elif elapsed > self._BT_CONNECT_TIMEOUT:
            # Timeout waiting for BT socket
            self._waiting_for_bt = False
            self._bt_signal_start = None
            self._real_stream.stop()
            self._stop_tick_thread()
            _n = name
            self._on_main(lambda n=_n: (
                self._live_screen.set_controls_idle(),
                self._live_screen.update_device_status(False),
                self._live_screen.show_overlay_retry(
                    f"Connection to {n} timed out.\n"
                    "Make sure the device is turned on\nand in range."
                ),
            ))
            self._release_wake_lock()
            self._stop_session_keep_alive_service()
            logger.error("BT connection timed out")
        else:
            # Still waiting for BT socket — show countdown
            remaining = int(self._BT_CONNECT_TIMEOUT - elapsed)
            _msg = f"Connecting to {name}...\nTimeout in {remaining}s"
            self._on_main(lambda m=_msg: self._live_screen.update_overlay(m))

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

        # Auto-stop when session reaches max duration
        if self._session_manager.elapsed_seconds >= APP.SESSION_MAX_SECONDS:
            logger.info(f"Session reached max duration ({APP.SESSION_MAX_SECONDS}s), auto-stopping")
            self._audio.play_disconnect_alert()
            _limit_msg = (
                f"Session recording limit reached ({APP.SESSION_MAX_SECONDS // 3600}h). "
                "Session saved. Start a new one to continue."
            )
            self._on_main(lambda m=_limit_msg: self._live_screen.show_alert(m))
            self._on_main(lambda: self._stop_and_save())
            return

        # Update settings status when real BT device connects
        if (not self._bt_connected_notified
                and not APP.USE_MOCK_DEVICE
                and self._real_stream.is_connected):
            self._bt_connected_notified = True
            name = self._real_stream._device_name or "Real EEG"
            _n = name
            self._on_main(lambda n=_n: self._settings_screen.update_device_status(True, name=n))
            logger.info(f"Settings updated: {name} connected")

        # Detect BT disconnect during session
        if (not APP.USE_MOCK_DEVICE
                and self._bt_connected_notified
                and not self._real_stream.is_connected):
            self._bt_connected_notified = False
            name = self._real_stream._device_name or "Real EEG"
            _n = name
            self._on_main(lambda n=_n: self._live_screen.update_device_status(
                False, device_name=n, connecting=True
            ))
            self._audio.play_disconnect_alert()
            logger.warning(f"BT device {name} disconnected during session")

        self._check_stale_data()

        raw_sample = self._eeg_stream.read_sample()
        metrics = self._metrics_engine.process_sample(raw_sample)

        # Low battery warning (ThinkGear reports 0-127, warn below ~20%)
        battery = raw_sample.get("battery", -1)
        if battery != -1 and battery < 25 and not getattr(self, '_low_battery_warned', False):
            self._low_battery_warned = True
            pct = int(battery / 127 * 100)
            _bat_msg = f"Low headset battery ({pct}%)."
            self._on_main(lambda m=_bat_msg: self._live_screen.show_alert(m))
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
                    _noise_msg = (
                        f"Warning: {freq} Hz power line noise detected. "
                        f"Check notch filter setting or move away from electrical equipment."
                    )
                    self._on_main(lambda m=_noise_msg: self._live_screen.show_alert(m))
                    logger.warning(f"Power line noise detected: {freq} Hz")

        # Log raw sample every 10 ticks (~5s at 2Hz)
        self._tick_count = getattr(self, '_tick_count', 0) + 1
        if self._tick_count % 10 == 0:
            bands = {k: f"{raw_sample.get(k, 0):.0f}" for k in
                     ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2")}
            logger.debug(f"Raw sample #{self._tick_count}: {bands}")
            native_med = raw_sample.get("meditation", -1)
            bat = raw_sample.get("battery", -1)
            bat_str = f" bat={bat}/127" if bat >= 0 else ""
            logger.debug(f"Metrics: med={metrics.get('meditation_score', 0):.0f} "
                         f"sham={metrics.get('shamatha_score', 0):.0f} "
                         f"sink={metrics.get('sinking', 0):.0f} "
                         f"dist={metrics.get('distraction', 0):.0f} "
                         f"native_med={native_med:.0f}{bat_str}")

        # Evaluate custom formulas if any slot is active
        if any(e.is_valid for e in self._formula_slots):
            formula_vars = self._eval_formula_vars(raw_sample, metrics)
            for key, ev in zip(FORMULA_KEYS, self._formula_slots):
                if ev.is_valid:
                    ev.push_variables(formula_vars)
                    metrics[key] = ev.evaluate(formula_vars)

        if getattr(self, "_timer_mode", "simple") == "program":
            self._apply_program_tick(metrics, raw_sample)

        self._session_manager.add_metric(metrics)
        # Merge raw + computed for full storage
        full_record = {**raw_sample, **metrics}
        self._metrics_buffer.append(full_record)
        self._raw_buffer.append(raw_sample)

        # Audio is thread-safe — update directly
        self._audio.update(metrics.get(self._audio_drive_key(), 0))
        if self._tick_count > 10:
            self._audio.update_sinking(metrics.get("sinking", 0))
            self._audio.update_subtle_distraction(metrics.get("subtle_distraction", 0))

        # Mirror what the UI graphs would have received. Done here on the
        # tick thread (no Kivy graphics ops) so the data exists even while
        # the UI is paused (Android screen lock); on resume we batch-reload
        # the graphs from these mirrors instead of replaying N per-tick
        # Clock callbacks (which previously flooded the main loop and
        # caused a black screen).
        self._ui_metrics_history.append(dict(metrics))
        _band_record = {
            "alpha": raw_sample.get("alpha1", 0.0) + raw_sample.get("alpha2", 0.0),
            "beta": raw_sample.get("beta1", 0.0) + raw_sample.get("beta2", 0.0),
            "gamma": raw_sample.get("gamma1", 0.0) + raw_sample.get("gamma2", 0.0),
            "theta": raw_sample.get("theta", 0.0),
            "delta": raw_sample.get("delta", 0.0),
        }
        self._ui_band_history.append(_band_record)
        _waveform = raw_sample.get("raw_eeg_waveform")
        if _waveform:
            self._ui_raw_waveform.extend(_waveform)
        else:
            self._ui_raw_waveform.append(sum(_band_record.values()))
        self._ui_last_metrics = metrics
        self._ui_last_state = metrics.get("state", "Neutral")

        # UI updates — dispatch to main thread
        _elapsed_fmt = self._session_manager.elapsed_formatted
        _marker_pending = self._pending_marker
        if _marker_pending:
            self._pending_marker = False
            full_record["marker"] = 1

        def _ui_update(
            m=metrics, rs=raw_sample, ef=_elapsed_fmt, mp=_marker_pending
        ) -> None:
            self._live_screen.graph.add_point(m)
            self._live_screen.update_stats(m)
            self._live_screen.update_state(m.get("state", "Neutral"))
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

        # Timer countdown — tick() is pure counter, no UI
        if self._timer_state.tick(APP.UPDATE_FREQUENCY):
            logger.info("Timer expired, auto-stopping session")
            # Stop the audio loop on the tick thread directly so the
            # white-noise actually ends at timer-expiry even when the
            # screen is locked (the noise channel is MediaPlayer-based
            # on Android and `AudioEngine.stop()` is thread-safe).
            # Without this, _on_main below would queue stop() through
            # Kivy's Clock — paused while the screen is locked — so
            # the noise kept playing past the timer end.
            # Persist FIRST, on THIS daemon thread, before any audio teardown.
            # The finished session must be saved even though the screen may be
            # locked. (Originally _audio.stop() ran here first and DEADLOCKED
            # the tick thread: MediaPlayer.release() synchronises with its
            # event handler on the main Looper, which is PAUSED during lock —
            # so the save never ran and the whole session was lost.)
            stats = self._persist_session_data(reason="timer")
            session_id = self._current_session_id
            # Silence the noise with a non-blocking volume→0 (setVolume is a
            # direct native call, safe from this thread even while locked).
            # The real stop()/release() teardown is deferred to the main
            # thread below, where the Looper is live and release() won't hang.
            self._audio.mute()
            # Stop the tick loop NOW (in the thread itself) so it doesn't keep
            # iterating through the pause while _finish_on_main waits on the
            # paused Clock.
            self._tick_stop_event.set()
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
            return

        # Flush buffer to DB every 60 seconds (DB opened with check_same_thread=False)
        self._flush_counter += 1
        ticks_per_flush = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY)
        if self._flush_counter >= ticks_per_flush and self._metrics_buffer:
            if self._current_session_id is None:
                stats_partial = self._session_manager.compute_statistics()
                self._current_session_id = self._db.save_session(
                    stats_partial, user_id=self._current_user_id,
                    session_name=self._make_session_name(),
                    custom_formulas=self._session_custom_formulas_json(),
                    session_program=self._session_program_json(),
                )
            self._db.save_metrics_batch(self._current_session_id, self._metrics_buffer)
            self._metrics_buffer = []
            self._flush_counter = 0

    def _on_key_down(self, window, key, scancode, codepoint, modifiers) -> bool:
        """Handle keyboard hotkey for marker."""
        # Don't capture keys while settings hotkey picker is active
        if self._settings_screen._waiting_for_hotkey:
            return False
        hotkey = self._settings_screen.marker_hotkey
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
        # An open Popup/ModalView dismisses itself on escape — let it.
        if any(isinstance(c, ModalView) for c in Window.children):
            return False
        # Fullscreen graph overlay → close it (it's not a ModalView).
        if self._fullscreen_overlay is not None and self._fullscreen_close is not None:
            self._fullscreen_close()
            return True
        current = self._sm.current
        if current == "diary":
            self._on_diary_back()
            return True
        if current != "live_session":
            self._switch_screen("live_session")
            return True
        # Root (Session): require two presses within 2s to exit.
        now = time.time()
        if now - self._last_back_time < 2.0:
            App.get_running_app().stop()
            return True
        self._last_back_time = now
        self._android_toast("Press back again to exit")
        return True

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
                    PythonActivity.mActivity, message, Toast.LENGTH_SHORT
                ).show()
            _show()
        except Exception as e:
            logger.warning(f"Toast failed: {e}")

    def _on_marker(self, *args) -> None:
        """Place a marker at the current position in the session."""
        if self._session_manager.state == SessionState.RUNNING:
            self._pending_marker = True
            logger.info("Marker placed")

    def _on_duration_preset(self, value) -> None:
        """Handle Live Session preset tap: update timer settings + persist."""
        if value is None:
            self._settings_screen.timer_enabled = False
        else:
            self._settings_screen.timer_enabled = True
            self._settings_screen.timer_minutes = value
        self._save_user_settings()
        self._live_screen.refresh_duration_preset(
            self._settings_screen.timer_enabled,
            self._settings_screen.timer_minutes,
        )

    def _on_threshold_change(self, value: int) -> None:
        self._metrics_engine.meditation_threshold = value
        self._audio.set_threshold(value)
        self._live_screen.graph.set_threshold(float(value), "shamatha_score")
        logger.debug(f"Threshold changed to {value}")

    def _present_series_picker(self, graph) -> None:
        """Open the shared multi-select series popup for `graph`.

        Reads the graph's own catalog/labels/colors, so one presenter serves
        every graph. Wired to all multi-series graphs by _wire_graph_affordances.
        For the live metrics graph, custom-formula rows also carry a Choose button
        that assigns a saved formula to that slot without leaving the picker.
        """
        is_live = graph is self._live_screen.graph
        body = BoxLayout(orientation="vertical", spacing=S.GAP_SM, padding=S.GAP)
        for key in graph.series_keys():
            vis = graph.is_visible(key)
            btn = StyledButton(
                text=graph.series_name(key), height=dp(44),
                bg_color=C.ACCENT if vis else C.BG_CARD,
                text_color=C.TEXT if vis else C.TEXT_SECONDARY, bold=vis,
            )
            btn.bind(on_release=lambda b, k=key: self._toggle_series_row(graph, k, b))
            if is_live and key in FORMULA_KEYS:
                row = BoxLayout(orientation="horizontal", spacing=S.GAP_SM, height=dp(44), size_hint_y=None)
                btn.size_hint_x = 1
                choose_btn = StyledButton(
                    text="Choose…", height=dp(44), size_hint_x=None, width=dp(90),
                    bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                )
                slot_idx = FORMULA_KEYS.index(key)
                choose_btn.bind(on_release=lambda _b, si=slot_idx, tb=btn: self._open_saved_formula_chooser(si, tb))
                row.add_widget(btn)
                row.add_widget(choose_btn)
                body.add_widget(row)
            else:
                body.add_widget(btn)
        # Neutral outlined Close — a green fill (PRIMARY) collided with the
        # green "selected" pills (ACCENT) on the green palettes.
        close_btn = StyledButton(
            text="Close", height=dp(44),
            outline=True, bg_color=C.TEXT_SECONDARY,
            text_color=C.TEXT, bg_pressed=C.BG_CARD,
        )
        popup = Popup(
            title="Graph series", content=body,
            size_hint=(0.8, None),
            height=dp(80 + 50 * (len(graph.series_keys()) + 1)),
            auto_dismiss=True,
        )
        close_btn.bind(on_release=lambda *_a: popup.dismiss())
        body.add_widget(close_btn)
        popup.bind(on_dismiss=lambda *_a: self._persist_graph_series(graph))
        popup.open()

    def _open_saved_formula_chooser(self, slot_idx: int, toggle_btn) -> None:
        """Open a second popup listing saved formulas; selecting one assigns it to
        slot_idx and refreshes the picker's toggle button to its new visible state."""
        if not self._current_user_id:
            return
        formulas = self._db.get_saved_formulas(self._current_user_id)
        inner_body = BoxLayout(orientation="vertical", spacing=S.GAP_SM, padding=S.GAP)
        inner_popup = Popup(
            title="Choose saved formula", content=inner_body,
            size_hint=(0.75, None),
            height=dp(80 + 50 * (max(len(formulas), 1) + 1)),
            auto_dismiss=True,
        )

        def _choose(entry):
            inner_popup.dismiss()
            self._assign_saved_to_slot(slot_idx, entry)
            vis = self._live_screen.graph.is_visible(FORMULA_KEYS[slot_idx])
            toggle_btn.bg_color = C.ACCENT if vis else C.BG_CARD
            toggle_btn.text_color = C.TEXT if vis else C.TEXT_SECONDARY
            toggle_btn.bold = vis

        if not formulas:
            inner_body.add_widget(Label(
                text="No saved formulas", color=C.TEXT_SECONDARY,
                height=dp(44), size_hint_y=None,
            ))
        else:
            for entry in formulas:
                row_btn = StyledButton(
                    text=entry.get("name", entry.get("formula", "")[:30]),
                    height=dp(44),
                    bg_color=C.BG_CARD, text_color=C.TEXT,
                )
                row_btn.bind(on_release=lambda _b, e=entry: _choose(e))
                inner_body.add_widget(row_btn)
        cancel_btn = StyledButton(
            text="Cancel", height=dp(44),
            bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM,
        )
        cancel_btn.bind(on_release=lambda *_a: inner_popup.dismiss())
        inner_body.add_widget(cancel_btn)
        inner_popup.open()

    def _toggle_series_row(self, graph, key: str, btn) -> None:
        """Flip one series on `graph` (stays in the popup for multi-select)."""
        visible = not graph.is_visible(key)
        # The live formula must be valid to plot live custom_formula values;
        # diary custom_formula is recorded data and toggles freely.
        ev = self._formula_for_key(key)
        if ev is not None and graph is self._live_screen.graph:
            visible = visible and ev.is_valid
        graph.set_visible(key, visible)  # fires the owning screen's legend refresh
        self._refresh_fullscreen_legend()
        vis = graph.is_visible(key)
        btn.bg_color = C.ACCENT if vis else C.BG_CARD
        btn.text_color = C.TEXT if vis else C.TEXT_SECONDARY
        btn.bold = vis

    def _refresh_fullscreen_legend(self) -> None:
        """Rebuild the fullscreen legend after a series toggle (if fullscreen)."""
        if self._fullscreen_overlay is None or self._fullscreen_graph is None:
            return
        self._fullscreen_content.remove_widget(self._fullscreen_legend)
        self._fullscreen_legend = self._build_fullscreen_legend(self._fullscreen_graph)
        self._fullscreen_content.add_widget(self._fullscreen_legend)

    def _persist_graph_series(self, graph) -> None:
        """Persist `graph`'s visible series under its per-graph key on picker close."""
        uid = self._current_user_id
        if uid and graph.graph_id:
            self._db.set_user_json_setting(
                uid, f"graph_series_{graph.graph_id}", graph.visible_keys()
            )

    def _on_test_audio(self) -> None:
        logger.debug("Test audio triggered")
        self._audio.test_audio()

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
        logger.info(f"Screen rotation set to {rotation}")

    def _audio_drive_key(self) -> str:
        """Metric key feeding noise; falls back to shamatha if a bound formula slot
        is invalid (a missing series reads 0 → would otherwise drive MAX noise)."""
        ev = self._formula_for_key(self._audio_metric_key)
        if ev is not None and not ev.is_valid:
            return "shamatha_score"
        return self._audio_metric_key

    def _on_audio_metric_change(self, key: str) -> None:
        """Switch which metric drives the audio threshold feedback."""
        if key == "custom_formula":
            self._audio_metric_key = FORMULA_KEYS[self._audio_formula_index]
        else:
            self._audio_metric_key = key
        logger.info(f"Audio threshold metric changed to: {self._audio_metric_key}")

    def _on_audio_formula_index(self, idx: int) -> None:
        """Pick which formula slot drives audio. Only rebinds the live key when a
        custom-formula slot is the selected driver — tapping it while another metric
        is selected just remembers the choice for when custom-formula is picked."""
        self._audio_formula_index = max(0, min(idx, _MAX_FORMULAS - 1))
        if self._audio_metric_key in FORMULA_KEYS:
            self._audio_metric_key = FORMULA_KEYS[self._audio_formula_index]

    def _on_theme_change(self, theme_name: str) -> None:
        """Save selected theme."""
        self._db.set_setting("theme", theme_name)
        logger.info(f"Theme changed to: {theme_name}")

    def _on_formula_slot_change(self, idx: int, name: str, formula: str, *, show: bool = True) -> None:
        """Apply a slot's name+formula. show=True reveals the series (interactive).

        `show=True` (interactive apply) reveals the line on success — you typed a
        formula, you want to see it. `show=False` (restore) only sets eligibility;
        visibility is then decided by the persisted picker selection in
        _restore_graph_series, so a hidden-but-valid choice survives a reload.
        """
        ev = self._formula_slots[idx]
        key = FORMULA_KEYS[idx]
        self._formula_names[idx] = name or f"Custom {idx + 1}"
        self._live_screen.graph.set_series_name(key, self._formula_names[idx])
        if not formula:
            ev.set_formula("")
            self._live_screen.graph.set_visible(key, False)
            self._settings_screen.set_formula_slot_status(idx, "Formula cleared")
            logger.info(f"Custom formula slot {idx} cleared")
        else:
            ok, err = ev.set_formula(formula)
            if ok:
                # set_visible fires the graph's visibility callback → legend rebuilds.
                if show:
                    self._live_screen.graph.set_visible(key, True)
                self._settings_screen.set_formula_slot_status(idx, "Formula active")
                logger.info(f"Custom formula slot {idx} applied: {formula}")
            else:
                self._live_screen.graph.set_visible(key, False)
                self._settings_screen.set_formula_slot_status(idx, f"Error: {err}", is_error=True)
        if self._current_user_id:
            self._persist_active_formulas(self._current_user_id)

    def _on_save_formula(self, idx: int, name: str, formula: str) -> None:
        """Save a slot's formula to the user's saved library, named by the slot."""
        if not self._current_user_id:
            self._settings_screen.set_formula_slot_status(idx, "No user selected", is_error=True)
            return
        if not formula:
            self._settings_screen.set_formula_slot_status(idx, "Nothing to save", is_error=True)
            return
        # Fall back to a truncated formula as the display name when none is given.
        label = name or (formula[:40] + ("..." if len(formula) > 40 else ""))
        ok = self._db.add_saved_formula(self._current_user_id, label, formula)
        if ok:
            self._settings_screen.set_formula_slot_status(idx, "Formula saved")
            self._refresh_saved_formulas()
            logger.info(f"Formula saved: {label} = {formula}")
        else:
            self._settings_screen.set_formula_slot_status(idx, "Limit reached (50 max)", is_error=True)

    def _on_load_formula(self, index: int) -> None:
        """Load a saved formula into the first empty slot and apply it."""
        if not self._current_user_id:
            return
        formulas = self._db.get_saved_formulas(self._current_user_id)
        if 0 <= index < len(formulas):
            entry = formulas[index]
            formula = entry["formula"]
            name = entry.get("name", "") or ""
            slot = self._first_empty_slot()
            self._settings_screen.set_formula_slot(slot, name, formula)
            self._on_formula_slot_change(slot, name, formula)

    def _first_empty_slot(self) -> int:
        """First slot with no valid formula; slot 0 if all are full."""
        return next((i for i in range(_MAX_FORMULAS) if not self._formula_slots[i].is_valid), 0)

    def _assign_saved_to_slot(self, idx: int, entry: dict) -> None:
        """Assign a saved {name, formula} entry to slot idx, show it, and persist."""
        self._on_formula_slot_change(idx, entry.get("name", ""), entry.get("formula", ""), show=True)
        self._settings_screen.set_formula_slot(
            idx, self._formula_names[idx], self._formula_slots[idx].formula
        )

    def _on_delete_formula(self, index: int) -> None:
        """Delete a saved formula."""
        if not self._current_user_id:
            return
        self._db.remove_saved_formula(self._current_user_id, index)
        self._refresh_saved_formulas()
        self._settings_screen.set_formula_slot_status(0, "Formula deleted")
        logger.info(f"Saved formula #{index} deleted")

    def _on_export_formulas(self) -> None:
        """Export saved formulas to a text file."""
        if not self._current_user_id:
            self._settings_screen.set_formula_slot_status(0, "No user selected", is_error=True)
            return
        formulas = self._db.get_saved_formulas(self._current_user_id)
        if not formulas:
            self._settings_screen.set_formula_slot_status(0, "No formulas to export", is_error=True)
            return
        export_dir = os.path.dirname(self._db._db_path)
        path = os.path.join(export_dir, f"formulas_user_{self._current_user_id}.txt")
        with open(path, "w") as f:
            for entry in formulas:
                f.write(f"{entry['formula']}\n")
        self._settings_screen.set_formula_slot_status(0, f"Exported to {os.path.basename(path)}")
        logger.info(f"Exported {len(formulas)} formulas to {path}")

    def _on_timer_mode_change(self, mode: str) -> None:
        self._timer_mode = mode
        self._persist_session_program(self._current_user_id)

    def _on_program_changed(self, segments: list) -> None:
        self._session_program_segments = segments
        self._persist_session_program(self._current_user_id)

    def _on_program_save(self, name: str) -> None:
        if name.strip() and self._current_user_id:
            self._db.add_saved_program(self._current_user_id, name.strip(),
                                       self._session_program_segments)
            self._settings_screen.set_saved_programs(
                self._db.get_saved_programs(self._current_user_id))

    def _on_program_load(self, index: int) -> None:
        if not self._current_user_id:
            return
        progs = self._db.get_saved_programs(self._current_user_id)
        if 0 <= index < len(progs):
            self._session_program_segments = progs[index]["segments"]
            self._timer_mode = "program"
            self._persist_session_program(self._current_user_id)
            self._settings_screen.load_program(self._session_program_segments, "program")

    def _on_program_delete(self, index: int) -> None:
        if not self._current_user_id:
            return
        self._db.remove_saved_program(self._current_user_id, index)
        self._settings_screen.set_saved_programs(
            self._db.get_saved_programs(self._current_user_id))

    def _refresh_saved_formulas(self) -> None:
        """Refresh the saved formulas list in settings UI."""
        if not self._current_user_id:
            self._settings_screen.populate_saved_formulas([])
            return
        formulas = self._db.get_saved_formulas(self._current_user_id)
        self._settings_screen.populate_saved_formulas(formulas)

    def _on_sinking_alert_toggle(self, active: bool) -> None:
        self._audio.sinking_alert_enabled = active
        logger.info(f"Sinking alert {'enabled' if active else 'disabled'}")

    def _on_subtle_alert_toggle(self, active: bool) -> None:
        self._audio.subtle_alert_enabled = active
        logger.info(f"Distraction chime {'enabled' if active else 'disabled'}")

    def _on_disconnect_alert_toggle(self, active: bool) -> None:
        self._audio.disconnect_alert_enabled = active
        logger.info(f"Disconnect alert {'enabled' if active else 'disabled'}")

    def _on_test_timer_sound(self) -> None:
        logger.debug(f"Test timer sound, path='{self._timer_state.custom_sound_path}'")
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
                    lambda dt: self._settings_screen.notify_timer_sound_test_ended(),
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

    def _on_device_mode_toggle(self, use_mock: bool) -> None:
        APP.USE_MOCK_DEVICE = use_mock
        if use_mock:
            self._settings_screen.update_device_status(False, meta="Mode: Mock Data")
            self._live_screen.update_device_status(False, device_name="Mock EEG")
        else:
            name = self._real_stream._device_name or ""
            addr = self._real_stream._device_address or "none"
            self._settings_screen.update_device_status(False, meta=f"Mode: Real Device ({addr})")
            self._live_screen.update_device_status(False, device_name=name or "Real EEG")
        if self._current_user_id:
            self._db.set_user_setting(self._current_user_id, "use_mock", str(use_mock))
        logger.info(f"Device mode: {'Mock' if use_mock else 'Real'}")

    def _on_scan_devices(self) -> None:
        """Scan for paired Bluetooth devices and send to settings screen."""
        devices = NeuroSkyStream.scan_paired_devices()
        self._settings_screen.populate_bt_devices(devices)
        logger.info(f"BT scan found {len(devices)} paired devices")

    def _on_device_select(self, address: str, name: str) -> None:
        """User selected a BT device from the list."""
        self._real_stream.set_device(address, name)
        # Auto-switch to real device mode
        APP.USE_MOCK_DEVICE = False
        self._settings_screen._device_mode_cb.active = False
        self._settings_screen.update_device_status(False, meta=f"Selected: {name}")
        logger.info(f"BT device selected: {name} ({address}), switched to real mode")
        if self._current_user_id:
            self._db.set_user_setting(self._current_user_id, "bt_device_address", address)
            self._db.set_user_setting(self._current_user_id, "bt_device_name", name)

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

    def _on_copy_diagnostics(self) -> None:
        """Build a diagnostic report and show it via the soft-error dialog.

        User-initiated, so we bypass the per-label cooldown — the user
        explicitly asked for the report.
        """

        try:
            paired = NeuroSkyStream.scan_paired_devices()
        except Exception as e:
            paired = []
            logger.warning(f"Diagnostics: BT scan failed: {e}")

        try:
            paired_summary = "\n".join(
                f"  - {d.get('name') or 'Unknown'}  ({d.get('address')})"
                for d in paired
            ) or "  (none)"
        except Exception:
            paired_summary = "  (failed to enumerate)"

        current_addr = self._real_stream._device_address or "(none)"
        current_name = self._real_stream._device_name or "(none)"
        last_err = self._real_stream._last_connect_error or "(none)"
        last_packet = self._real_stream.seconds_since_last_packet
        signal = self._real_stream._latest_signal_quality
        battery = self._real_stream._battery_level
        sample_rate = APP.WHITE_NOISE_SAMPLE_RATE
        max_volume = APP.MAX_VOLUME
        use_mock = APP.USE_MOCK_DEVICE

        detail = (
            f"USE_MOCK_DEVICE: {use_mock}\n"
            f"Selected device: {current_name} ({current_addr})\n"
            f"Last connect error: {last_err}\n"
            f"Seconds since last packet: {last_packet:.1f}\n"
            f"Latest signal quality: {signal}\n"
            f"Battery level (raw): {battery}\n"
            f"Audio sample rate: {sample_rate} Hz\n"
            f"Max volume: {max_volume}\n"
            f"Paired BT devices ({len(paired)}):\n{paired_summary}\n"
        )

        report_soft_error("user_diagnostics", detail, app=self, force=True)

    def _on_session_select(self, session_id: int) -> None:
        """Load a session into the diary off the UI thread, behind a spinner.

        The heavy work (metrics fetch + formula recompute) runs on a worker
        thread; the Kivy render is dispatched back to the main thread. The
        worker is deferred one frame so the loading overlay paints first.
        """
        self.show_loading("Loading session…")
        Clock.schedule_once(lambda dt: self._load_session_async(session_id), 0)

    def _load_session_async(self, session_id: int) -> None:
        def _worker():
            try:
                with timed("diary.total"):
                    with timed("diary.get_session"):
                        session = self._db.get_session(session_id)
                    if not session:
                        self._on_main(self.hide_loading)
                        return
                    with timed("diary.compute_formulas"):
                        series, names = self._compute_session_formulas(session_id, session)
                    with timed("diary.get_metrics"):
                        metrics = self._db.get_session_metrics(session_id)
            except Exception:
                logger.exception("Diary session load failed")
                self._on_main(self.hide_loading)
                return
            self._on_main(lambda: self._render_session_detail(session, series, names, metrics))
        threading.Thread(target=_worker, daemon=True, name="DiaryLoad").start()

    def _render_session_detail(self, session, series, names, metrics) -> None:
        """Main-thread render of a loaded session (Kivy mutations only)."""
        try:
            with timed("diary.render"):
                self._diary_screen.show_session_detail(session)
                self._diary_screen.set_metrics_threshold(float(session.get("threshold_used", 50)))
                self._diary_screen.set_session_formulas(series, names)
                self._diary_screen.load_metrics_preview(metrics)
                self._diary_screen.set_program(session.get("session_program", ""))
                self._session_detail_back = self._sm.current
                self._sm.current = "diary"
        finally:
            self.hide_loading()

    def _compute_session_formulas(self, session_id: int, session: dict) -> tuple[dict, dict]:
        """Recompute the session's recorded formula series + names from its band
        powers (the snapshot active then, not today's edits). Pure DB + compute,
        no Kivy — safe to call off the main thread."""
        cf_raw = session.get("custom_formulas") or ""
        evaluators: dict[str, CustomFormulaEvaluator] = {}
        # Reset every custom key to its default name so a session without a given
        # slot doesn't inherit the previous session's label.
        names: dict[str, str] = {k: f"Custom {i + 1}" for i, k in enumerate(FORMULA_KEYS)}
        if cf_raw:
            try:
                defs = json.loads(cf_raw)
            except (ValueError, TypeError):
                defs = []
            for pos, d in enumerate(defs):
                if not isinstance(d, dict):
                    continue
                slot = d.get("slot", pos)  # explicit slot; fall back to position for old records
                if not isinstance(slot, int) or not 0 <= slot < _MAX_FORMULAS:
                    continue
                key = FORMULA_KEYS[slot]
                ev = CustomFormulaEvaluator()
                ev.set_formula(d.get("formula", "") or "")
                if ev.is_valid:
                    evaluators[key] = ev
                    names[key] = d.get("name") or f"Custom {slot + 1}"
        series = self._db.recompute_formula_series(session_id, evaluators) if evaluators else {}
        return series, names

    def _inject_session_formulas(self, session_id: int, session: dict) -> None:
        """Recompute + apply the session's recorded formulas (synchronous)."""
        series, names = self._compute_session_formulas(session_id, session)
        self._diary_screen.set_session_formulas(series, names)

    def _on_diary_back(self) -> None:
        """Return from diary detail to previous screen (usually history)."""
        back = getattr(self, "_session_detail_back", "history")
        self._switch_screen(back)

    def _on_save_notes(
        self, session_id: int, notes: str, tags: str, mood: int
    ) -> None:
        self._db.update_session_notes(session_id, notes, tags, mood)
        self._refresh_diary()
        logger.info(f"Notes saved for session {session_id}")

    def _on_delete_session(self, session_id: int) -> None:
        """Delete a session and refresh lists."""
        self._db.delete_session(session_id)
        self._refresh_diary()
        self._refresh_history(force=True)
        logger.info(f"Session {session_id} deleted")

    def _on_rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session and refresh lists."""
        self._db.rename_session(session_id, new_name)
        self._refresh_diary()
        self._refresh_history(force=True)
        logger.info(f"Session {session_id} renamed to '{new_name}'")

    def _on_export_csv(self, session_id: int, path: Optional[str] = None) -> Optional[str]:
        """Export session data as CSV file. Returns file path or None."""
        csv_data = self._db.export_session_csv(
            session_id, custom_formula=self._formula_slots[0]
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

    _history_dirty: bool = True

    def _refresh_history(self, force: bool = False) -> None:
        if not force and not self._history_dirty:
            return
        with timed("history.get_all_sessions"):
            sessions = self._db.get_all_sessions(user_id=self._current_user_id)
        # Rows build in chunks (history_screen); spinner stays up until the last
        # chunk lands so the UI isn't frozen during the ~0.9s widget build.
        self.show_loading("Loading history…")
        self._history_screen.load_sessions(sessions, on_complete=self.hide_loading)
        self._history_dirty = False

    def _mark_history_dirty(self) -> None:
        self._history_dirty = True

    def _refresh_diary(self) -> None:
        sessions = self._db.get_all_sessions(user_id=self._current_user_id)
        self._diary_screen.populate_sessions(sessions)

    def _on_user_switch(self, user_id: Optional[int]) -> None:
        """Switch the active user profile."""
        # Save current user's settings before switching
        self._save_user_settings()
        self._current_user_id = user_id
        if user_id:
            user = self._db.get_user(user_id)
            name = user["name"] if user else "Unknown"
            self._db.set_setting("last_user_id", str(user_id))
            self._load_user_settings(user_id)
            logger.info(f"Switched to user: {name} (id={user_id})")
        else:
            logger.info("Switched to: All Users")
        self._mark_history_dirty()
        self._refresh_profile()

    def _on_history_view_mode_change(self, mode: str) -> None:
        """Persist the user's preferred History view layout."""
        if not self._current_user_id:
            return
        self._db.set_user_setting(self._current_user_id, "history_view_mode", mode)

    def _count_sessions_for_user(self, user_id: int) -> int:
        return len(self._db.get_all_sessions(user_id=user_id))

    # --- Data Backup ---

    def _is_android(self) -> bool:
        return hasattr(sys, "getandroidapilevel")

    def _on_backup_pressed(self) -> None:
        """Backup the live DB to a user-visible location."""


        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        filename = f"meditation_backup_{ts}.db"

        if self._is_android():
            target_dir = "/sdcard/Documents/EEGMeditation"
            try:
                os.makedirs(target_dir, exist_ok=True)
            except (PermissionError, OSError) as e:
                report_soft_error(
                    "backup_failed", f"Could not create {target_dir}: {e}",
                )
                return
            target_path = os.path.join(target_dir, filename)
            self._run_backup_async(target_path)
        else:
            self._open_backup_save_picker(filename)

    def _run_backup_async(self, target_path: str) -> None:



        self._settings_screen.show_backup_status("Backing up…")

        def _worker():
            try:
                _backup.make_backup(self._db, target_path)
            except (PermissionError, OSError) as exc:
                err_msg = f"Backup to {target_path} failed: {exc}"
                Clock.schedule_once(
                    lambda dt, _msg=err_msg: report_soft_error("backup_failed", _msg),
                )
                return
            Clock.schedule_once(lambda dt: self._settings_screen.show_backup_status(
                f"Saved to {target_path}",
            ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_restore_pressed(self) -> None:
        """Pick a backup file and restore it."""
        if self._is_android():
            self._open_restore_picker_android()
        else:
            self._open_restore_picker_desktop()

    def _open_restore_picker_android(self) -> None:


        target_dir = "/sdcard/Documents/EEGMeditation"
        try:
            files = sorted(
                f for f in os.listdir(target_dir) if f.endswith(".db")
            )
        except FileNotFoundError:
            files = []
        except (PermissionError, OSError) as e:
            report_soft_error(
                "restore_failed", f"Could not list {target_dir}: {e}",
            )
            return

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        popup = Popup(title="Pick a backup", content=content, size_hint=(0.9, 0.7))

        if not files:
            content.add_widget(Label(
                text="No backup files found in\nDocuments/EEGMeditation/",
                halign="center", valign="middle", color=C.TEXT_MUTED,
            ))
        else:
            for fname in files:
                full = os.path.join(target_dir, fname)
                btn = StyledButton(
                    text=fname,
                    bg_color=C.BG_CARD,
                    text_color=C.TEXT,
                    font_size=F.BODY,
                    bold=False,
                    size_hint_y=None,
                    height=dp(44),
                )

                def _make_handler(_full, _popup):
                    def _on_release(*_a):
                        _popup.dismiss()
                        self._confirm_restore(_full)
                    return _on_release

                btn.bind(on_release=_make_handler(full, popup))
                content.add_widget(btn)

        cancel = StyledButton(
            text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_MUTED,
            size_hint_y=None, height=dp(40),
        )
        cancel.bind(on_release=popup.dismiss)
        content.add_widget(cancel)
        popup.open()

    def _open_restore_picker_desktop(self) -> None:


        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        chooser = FileChooserListView(
            path=os.path.dirname(APP.DB_PATH),
            filters=["*.db"],
            size_hint_y=0.85,
        )
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        ok = StyledButton(text="Restore", bg_color=C.PRIMARY)
        cancel = StyledButton(
            text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_MUTED,
        )
        btn_row.add_widget(ok)
        btn_row.add_widget(cancel)
        content.add_widget(chooser)
        content.add_widget(btn_row)
        popup = Popup(title="Pick a backup", content=content, size_hint=(0.9, 0.9))

        def _do_pick(*_a):
            if not chooser.selection:
                return
            popup.dismiss()
            self._confirm_restore(chooser.selection[0])

        ok.bind(on_release=_do_pick)
        cancel.bind(on_release=popup.dismiss)
        popup.open()

    def _confirm_restore(self, source_path: str) -> None:
        """Validate, then show confirm dialog → on OK, replace + restart."""


        ok, msg = validate_backup(source_path)
        if not ok:
            report_soft_error(
                "restore_invalid",
                f"Selected file is not a valid backup: {msg}",
                force=True,
            )
            return

        n = self._db.get_record_counts()["sessions"]
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        content.add_widget(Label(
            text=(
                f"Replace current database with backup?\n\n"
                f"Your current sessions ({n}) will be replaced.\n"
                f"This cannot be undone."
            ),
            halign="center", valign="middle", color=C.TEXT,
        ))
        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok_btn = StyledButton(text="Restore", bg_color=C.DANGER)
        cancel_btn = StyledButton(
            text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_MUTED,
        )
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)
        popup = Popup(title="Restore database", content=content, size_hint=(0.85, 0.5))

        def _do_restore(*_a):
            popup.dismiss()
            self._do_restore_and_restart(source_path)

        ok_btn.bind(on_release=_do_restore)
        cancel_btn.bind(on_release=popup.dismiss)
        popup.open()

    def _do_restore_and_restart(self, source_path: str) -> None:


        try:
            self._db.close()
        except Exception:
            logger.exception("DB close before restore failed")
            return

        try:
            restore_backup(source_path, APP.DB_PATH)
        except (PermissionError, OSError) as e:
            report_soft_error(
                "restore_failed", f"Restore from {source_path} failed: {e}",
            )
            self._db = DatabaseManager(db_path=APP.DB_PATH)
            return
        except Exception as e:
            report_soft_error("restore_failed", f"Restore failed: {e}")
            self._db = DatabaseManager(db_path=APP.DB_PATH)
            return

        # DB is now closed and the file replaced. Tell on_stop to skip
        # _save_user_settings (which would crash on a closed conn anyway,
        # and would also clobber the freshly-restored state).
        self._restoring = True

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        content.add_widget(Label(
            text="Database restored.\n\nThe app will now exit — please relaunch.",
            halign="center", valign="middle", color=C.TEXT,
        ))
        ok = StyledButton(text="OK", bg_color=C.ACCENT)
        content.add_widget(ok)
        popup = Popup(
            title="Restore complete", content=content,
            size_hint=(0.8, 0.4), auto_dismiss=False,
        )

        def _quit(*_a):
            popup.dismiss()
            App.get_running_app().stop()

        ok.bind(on_release=_quit)
        popup.open()

    def _open_backup_save_picker(self, default_filename: str) -> None:


        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        chooser = FileChooserListView(
            path=os.path.dirname(APP.DB_PATH),
            filters=["*.db"],
            size_hint_y=0.7,
        )
        name_input = TextInput(
            text=default_filename,
            multiline=False,
            size_hint_y=None,
            height=dp(40),
        )
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        ok = StyledButton(text="Save", bg_color=C.ACCENT)
        cancel = StyledButton(text="Cancel", bg_color=C.BG_CARD,
                              text_color=C.TEXT_MUTED)
        btn_row.add_widget(ok)
        btn_row.add_widget(cancel)
        content.add_widget(chooser)
        content.add_widget(name_input)
        content.add_widget(btn_row)
        popup = Popup(title="Save backup", content=content, size_hint=(0.9, 0.9))

        def _do_save(*_a):
            target = os.path.join(chooser.path, name_input.text.strip())
            popup.dismiss()
            self._run_backup_async(target)

        ok.bind(on_release=_do_save)
        cancel.bind(on_release=popup.dismiss)
        popup.open()

    def _on_pick_existing_user(self, user_id: int, source: str) -> None:
        """User picked an existing profile from a UserPickerForm.

        source ∈ {'first_run', 'wizard', 'settings'}.
        - 'settings' → just switch user.
        - 'first_run' / 'wizard' → if a saved bt_device_address exists,
          run the full wizard-complete flow with it (skip step 2).
          Otherwise: wizard advances to step 2; first_run pop falls
          through to wizard-complete with no device.
        """
        user = self._db.get_user(user_id)
        if not user:
            logger.warning(f"_on_pick_existing_user: user {user_id} not found")
            return
        name = user["name"]

        if source == "settings":
            self._on_user_switch(user_id)
            return

        addr = self._db.get_user_setting(user_id, "bt_device_address")
        dev_name = self._db.get_user_setting(user_id, "bt_device_name") or name
        if addr:
            logger.info(f"Existing user {name} has saved device — skipping step 2")
            self._on_wizard_complete(name, addr, dev_name)
            return

        if source == "wizard":
            self._current_user_id = user_id
            self._db.set_setting("last_user_id", str(user_id))
            self._wizard_screen._user_name = name
            self._wizard_screen._advance_to_step2()
        else:  # first_run
            self._on_wizard_complete(name, None, None)

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
        """Delete a user profile."""
        if self._current_user_id == user_id:
            self._current_user_id = None
        self._db.delete_user(user_id)
        self._refresh_profile()

    def _refresh_profile(self) -> None:
        users = self._db.get_all_users()
        self._profile_screen.populate_users(users, self._current_user_id)
        self._settings_screen.populate_users(users, self._current_user_id)

    def _save_user_settings(self) -> None:
        """Persist current UI settings for the active user."""
        uid = self._current_user_id
        if not uid:
            return
        # Sync timer settings from the UI into the headless model.
        self._timer_state.set_enabled(self._settings_screen.timer_enabled)
        self._timer_state.set_duration(self._settings_screen.timer_minutes)
        self._timer_state.set_custom_sound_path(self._settings_screen.timer_sound_path)
        self._db.set_user_setting(uid, "timer_enabled", str(self._settings_screen.timer_enabled))
        self._db.set_user_setting(uid, "timer_minutes", str(self._settings_screen.timer_minutes))
        self._db.set_user_setting(uid, "timer_sound", self._timer_state.custom_sound_path)
        self._db.set_user_setting(uid, "sinking_alert", str(self._audio.sinking_alert_enabled))
        self._db.set_user_setting(uid, "subtle_alert", str(self._audio.subtle_alert_enabled))
        self._db.set_user_setting(uid, "disconnect_alert", str(self._audio.disconnect_alert_enabled))
        self._db.set_user_setting(uid, "threshold", str(self._settings_screen.threshold))
        self._db.set_user_setting(uid, "use_mock", str(APP.USE_MOCK_DEVICE))
        self._db.set_user_setting(
            uid, "line_width", str(self._settings_screen._line_width_slider.value)
        )
        self._db.set_user_setting(
            uid, "rotation", str(self._settings_screen._current_rotation)
        )
        self._persist_active_formulas(uid)
        self._persist_session_program(uid)
        self._db.set_user_setting(uid, "audio_formula_index", str(self._audio_formula_index))
        # Save zoom level as viewport duration in seconds
        graph = self._live_screen.graph
        zoom_seconds = graph.viewport_points / graph._sample_rate
        self._db.set_user_setting(uid, "graph_zoom_seconds", str(zoom_seconds))
        # Per-graph series selection (the on-graph picker is the source of truth).
        for g in self._all_graphs():
            if g.graph_id and len(g.series_keys()) > 1:
                self._db.set_user_json_setting(
                    uid, f"graph_series_{g.graph_id}", g.visible_keys()
                )
        self._db.set_user_setting(uid, "audio_metric", self._audio_metric_key)
        self._db.set_user_setting(uid, "marker_hotkey", self._settings_screen.marker_hotkey)
        self._db.set_user_setting(
            uid, "stats_view_mode", getattr(self._live_screen, "_stats_mode", "live")
        )
        logger.debug(f"Saved settings for user {uid}")

    def _restore_graph_series(self, user_id: int) -> None:
        """Apply each graph's persisted series selection (graph_series_<id>).

        set_visible drives each graph's own legend refresh. The live metrics graph
        migrates the pre-F2 toggle_<key> rows when it has no JSON yet; other graphs
        default to all-visible (their pre-picker behavior)."""
        for graph in self._all_graphs():
            if not graph.graph_id or len(graph.series_keys()) <= 1:
                continue
            series = self._db.get_user_json_setting(user_id, f"graph_series_{graph.graph_id}")
            if series is not None:
                sel = set(series)
            elif graph is self._live_screen.graph:
                sel = self._legacy_live_series(user_id)
            else:
                sel = set(graph.series_keys())
            for key in graph.series_keys():
                on = key in sel
                ev = self._formula_for_key(key)
                if ev is not None and graph is self._live_screen.graph:
                    on = on and ev.is_valid
                graph.set_visible(key, on)

    def _legacy_live_series(self, user_id: int) -> set[str]:
        """Pre-F2 fallback for the live metrics graph: per-metric toggle_<key> rows
        + custom_formula_visible, defaulting to the first-run _graph_toggles set."""
        defaults = self._settings_screen._graph_toggles
        sel: set[str] = set()
        for key in self._live_screen.graph.series_keys():
            if key in FORMULA_KEYS:  # custom slots never had pre-F2 toggle_ rows
                continue
            saved = self._db.get_user_setting(user_id, f"toggle_{key}")
            active = (saved == "True") if saved is not None else defaults.get(key, True)
            if active:
                sel.add(key)
        if self._db.get_user_setting(user_id, "custom_formula_visible") == "True":
            sel.add("custom_formula")
        return sel

    def _load_user_settings(self, user_id: int) -> None:
        """Restore persisted settings for a user."""
        g = self._db.get_user_setting

        timer_on = g(user_id, "timer_enabled")
        if timer_on is not None:
            active = timer_on == "True"
            self._timer_state.set_enabled(active)
            self._settings_screen.timer_enabled = active

        timer_min = g(user_id, "timer_minutes")
        if timer_min is not None:
            try:
                val = int(timer_min)
                self._timer_state.set_duration(val)
                self._settings_screen.timer_minutes = val
            except (ValueError, TypeError):
                pass

        timer_sound = g(user_id, "timer_sound")
        if timer_sound is not None:
            self._timer_state.set_custom_sound_path(timer_sound)
            self._settings_screen.timer_sound_path = timer_sound

        sink = g(user_id, "sinking_alert")
        if sink is not None:
            val = sink == "True"
            self._audio.sinking_alert_enabled = val
            self._settings_screen._sinking_alert_cb.active = val

        subtle = g(user_id, "subtle_alert")
        if subtle is not None:
            val = subtle == "True"
            self._audio.subtle_alert_enabled = val
            self._settings_screen._subtle_alert_cb.active = val

        disc = g(user_id, "disconnect_alert")
        if disc is not None:
            val = disc == "True"
            self._audio.disconnect_alert_enabled = val
            self._settings_screen._disconnect_alert_cb.active = val

        threshold = g(user_id, "threshold")
        if threshold is not None:
            try:
                tval = int(threshold)
                self._settings_screen._threshold_slider.value = tval
                self._metrics_engine.meditation_threshold = tval
                self._audio.set_threshold(tval)
            except (ValueError, TypeError):
                pass

        # Load formulas BEFORE _restore_graph_series so the per-slot validity gate
        # sees real is_valid; the picker selection (graph_series_*) decides visibility.
        self._apply_active_formulas(self._read_active_formulas_with_migration(user_id))
        self._load_session_program(user_id)
        self._settings_screen.load_program(self._session_program_segments, self._timer_mode)
        self._settings_screen.set_saved_programs(self._db.get_saved_programs(user_id))
        self._push_formula_names_to_graph()
        idx = g(user_id, "audio_formula_index")
        if idx is not None:
            try:
                self._audio_formula_index = max(0, min(int(idx), _MAX_FORMULAS - 1))
            except (ValueError, TypeError):
                pass
        # Reflect every slot's name+formula into the Settings inputs.
        for i in range(_MAX_FORMULAS):
            self._settings_screen.set_formula_slot(i, self._formula_names[i], self._formula_slots[i].formula)

        self._restore_graph_series(user_id)

        # Skip BT/mock restore if --serial override is active
        if not self.serial_device_override:
            bt_addr = g(user_id, "bt_device_address")
            bt_name = g(user_id, "bt_device_name")
            if bt_addr:
                self._real_stream.set_device(bt_addr, bt_name or bt_addr)
                self._settings_screen.update_device_status(
                    False, meta=f"Saved device: {bt_name or bt_addr}"
                )

            use_mock = g(user_id, "use_mock")
            if use_mock is not None:
                val = use_mock == "True"
                APP.USE_MOCK_DEVICE = val
                self._settings_screen._device_mode_cb.active = val
            elif bt_addr:
                APP.USE_MOCK_DEVICE = False
                self._settings_screen._device_mode_cb.active = False

        # Update live screen device label to match current mode
        if APP.USE_MOCK_DEVICE:
            self._live_screen.update_device_status(False, device_name="Mock EEG")
        elif self._real_stream._device_address:
            name = self._real_stream._device_name or "Real EEG"
            self._live_screen.update_device_status(False, device_name=name)

        lw = g(user_id, "line_width")
        if lw is not None:
            try:
                lw_val = float(lw)
                self._settings_screen._line_width_slider.value = lw_val
                self._on_line_width_change(lw_val)
            except (ValueError, TypeError):
                pass

        rot = g(user_id, "rotation")
        if rot is not None:
            try:
                rot_val = int(rot)
                self._settings_screen._current_rotation = rot_val
                self._settings_screen._rotate_btn.text = f"Rotate Screen ({rot_val}\u00b0)"
                self._on_rotate_screen(rot_val)
            except (ValueError, TypeError):
                pass

        zoom_s = g(user_id, "graph_zoom_seconds")
        if zoom_s is not None:
            try:
                sec = float(zoom_s)
                graph = self._live_screen.graph
                graph._set_viewport(int(sec * graph._sample_rate))
            except (ValueError, TypeError):
                pass

        audio_met = g(user_id, "audio_metric")
        if audio_met is not None:
            self._audio_metric_key = audio_met
            if audio_met in FORMULA_KEYS:
                self._audio_formula_index = FORMULA_KEYS.index(audio_met)
            # Reflect audio_metric: radios use "custom_formula" key for any formula slot
            ui_key = "custom_formula" if audio_met in FORMULA_KEYS else audio_met
            self._settings_screen.audio_metric = ui_key
            self._settings_screen.audio_formula_index = self._audio_formula_index

        marker_hk = g(user_id, "marker_hotkey")
        if marker_hk is not None:
            self._settings_screen.marker_hotkey = marker_hk

        stats_mode = g(user_id, "stats_view_mode")
        if stats_mode in ("live", "aggregate"):
            try:
                self._live_screen._stats_mode = stats_mode
                self._live_screen._apply_stats_mode_styling()
            except Exception:
                pass

        history_mode = g(user_id, "history_view_mode") or "calendar"
        self._history_screen.set_view_mode(history_mode)

        # Sync live-screen preset highlight with loaded timer state
        self._live_screen.refresh_duration_preset(
            self._settings_screen.timer_enabled,
            self._settings_screen.timer_minutes,
        )
        self._refresh_saved_formulas()
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
        self._save_user_settings()
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
        if self._session_manager.state != SessionState.RUNNING:
            logger.info("on_resume: session not RUNNING → skipping graph reload")
            return
        try:
            self._reload_live_graphs_from_mirror()
            if self._ui_last_metrics:
                self._live_screen.update_stats(self._ui_last_metrics)
                self._live_screen.update_state(self._ui_last_state)
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
        _save_user_settings: the DB file has just been replaced and writing
        the current in-memory settings would clobber the imported state.
        """
        if not getattr(self, "_restoring", False):
            self._save_user_settings()
        if self._session_manager.state in (SessionState.RUNNING, SessionState.PAUSED):
            self._stop_and_save()
        self._audio.cleanup()
        self._db.close()
        logger.info("Application closed")
