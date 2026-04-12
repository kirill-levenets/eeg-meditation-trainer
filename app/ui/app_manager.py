import os
import sys
import time
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, SlideTransition

from app.analytics.aggregator import AnalyticsAggregator
from app.audio_feedback.noise import AudioEngine
from app.config import APP
from app.eeg.mock_stream_v2 import MockEEGStream
from app.eeg.neurosky_stream import NeuroSkyStream
from app.logger import logger
from app.metrics.custom_formula import CustomFormulaEvaluator
from app.metrics.engine import MetricsEngine
from app.metrics.noise_detector import PowerLineDetector
from app.session.manager import SessionManager, SessionState
from app.storage.database import DatabaseManager
from app.ui.analytics_screen import AnalyticsScreen
from app.ui.diary_screen import DiaryScreen
from app.ui.history_screen import HistoryScreen
from app.ui.live_session import LiveSessionScreen
from app.ui.profile_screen import ProfileScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import BottomNav, C, F, StyledButton
from app.ui.timer_screen import TimerScreen
from app.ui.wizard_screen import WizardScreen


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
        self._analytics: AnalyticsAggregator = AnalyticsAggregator(self._db)
        self._update_event: Optional[object] = None
        self._metrics_buffer: list[dict] = []
        self._raw_buffer: list[dict] = []
        self._flush_counter: int = 0
        self._current_session_id: Optional[int] = None
        self._current_user_id: Optional[int] = None
        self._custom_formula: CustomFormulaEvaluator = CustomFormulaEvaluator()
        self.serial_device_override: Optional[str] = None
        self._wake_lock = None

    def _acquire_wake_lock(self) -> None:
        """Keep screen on during session (Android only)."""
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
            logger.info("Wake lock acquired (screen will stay on)")
        except Exception as e:
            logger.warning(f"Failed to acquire wake lock: {e}")

    def _release_wake_lock(self) -> None:
        """Allow screen to turn off again (Android only)."""
        if not hasattr(sys, "getandroidapilevel"):
            return
        try:
            from android.runnable import run_on_ui_thread
            @run_on_ui_thread
            def _clear_flag():
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                WindowManager = autoclass("android.view.WindowManager$LayoutParams")
                activity.getWindow().clearFlags(WindowManager.FLAG_KEEP_SCREEN_ON)
            _clear_flag()
            logger.info("Wake lock released")
        except Exception as e:
            logger.warning(f"Failed to release wake lock: {e}")

    # Map bottom-nav tab keys to screen groups
    _TAB_SCREENS = {
        "session": "live_session",
        "history": "history",
        "settings": "settings",
    }

    def build(self) -> BoxLayout:
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
        self._analytics_screen = AnalyticsScreen()
        self._timer_screen = TimerScreen()

        self._wizard_screen = WizardScreen()
        self._sm.add_widget(self._live_screen)
        self._sm.add_widget(self._wizard_screen)
        self._sm.add_widget(self._history_screen)
        self._sm.add_widget(self._settings_screen)
        self._sm.add_widget(self._profile_screen)
        self._sm.add_widget(self._diary_screen)
        self._sm.add_widget(self._analytics_screen)
        self._sm.add_widget(self._timer_screen)

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

        return root

    def _link_graph_zoom(self) -> None:
        """Link zoom across all graph widgets so they share the same time scale."""
        ScrollableGraphWidget.link_zoom(
            self._live_screen.graph,
            self._live_screen.raw_graph,
            self._live_screen.band_graph,
            self._diary_screen._metrics_graph,
            self._diary_screen._raw_eeg_graph,
            self._diary_screen._freq_graph,
        )

    def _bind_callbacks(self) -> None:
        # Wizard
        self._wizard_screen.set_complete_callback(self._on_wizard_complete)
        self._wizard_screen.set_scan_callback(self._on_wizard_scan)

        self._live_screen.btn_start.bind(on_release=self._on_start)
        self._live_screen.btn_pause.bind(on_release=self._on_pause)
        self._live_screen.btn_stop.bind(on_release=self._on_stop)
        self._live_screen.btn_marker.bind(on_release=self._on_marker)
        self._live_screen.overlay_cancel_btn.bind(on_release=self._on_connect_cancel)
        self._live_screen.overlay_retry_btn.bind(on_release=self._on_connect_retry)
        self._live_screen.summary_save_btn.bind(on_release=self._on_summary_save)
        self._live_screen.summary_history_btn.bind(on_release=self._on_summary_history)
        self._live_screen.summary_close_btn.bind(on_release=self._on_summary_close)

        # Tap on graph to set marker (Android — no keyboard available)
        from kivy.utils import platform as kivy_platform
        if kivy_platform == "android":
            self._live_screen.graph.set_tap_callback(self._on_marker)

        self._settings_screen.set_threshold_callback(self._on_threshold_change)
        self._settings_screen.set_toggle_callback(self._on_toggle_change)
        self._settings_screen.set_test_audio_callback(self._on_test_audio)
        self._settings_screen.set_sinking_alert_callback(self._on_sinking_alert_toggle)
        self._settings_screen.set_subtle_alert_callback(self._on_subtle_alert_toggle)
        self._settings_screen.set_disconnect_alert_callback(self._on_disconnect_alert_toggle)
        self._settings_screen.set_device_mode_callback(self._on_device_mode_toggle)
        self._settings_screen.set_scan_devices_callback(self._on_scan_devices)
        self._settings_screen.set_device_select_callback(self._on_device_select)
        self._settings_screen.set_line_width_callback(self._on_line_width_change)
        self._settings_screen.set_rotate_screen_callback(self._on_rotate_screen)
        self._settings_screen.set_custom_formula_callback(self._on_custom_formula_change)
        self._settings_screen.set_save_formula_callback(self._on_save_formula)
        self._settings_screen.set_load_formula_callback(self._on_load_formula)
        self._settings_screen.set_delete_formula_callback(self._on_delete_formula)
        self._settings_screen.set_export_formulas_callback(self._on_export_formulas)
        self._settings_screen.set_custom_formula_visible_callback(
            self._on_custom_formula_visible_toggle
        )
        self._settings_screen.set_audio_metric_callback(self._on_audio_metric_change)
        self._settings_screen.set_theme_callback(self._on_theme_change)

        # Keyboard hotkey for marker
        Window.bind(on_key_down=self._on_key_down)

        # Hide custom formula on graph until enabled via checkbox
        self._live_screen.graph.set_visible("custom_formula", False)
        self._audio_metric_key: str = "shamatha_score"

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

        self._analytics_screen.btn_daily.bind(
            on_release=lambda x: self._load_analytics("daily")
        )
        self._analytics_screen.btn_weekly.bind(
            on_release=lambda x: self._load_analytics("weekly")
        )
        self._analytics_screen.btn_monthly.bind(
            on_release=lambda x: self._load_analytics("monthly")
        )

        self._timer_screen.set_test_sound_callback(self._on_test_timer_sound)

        self._profile_screen.set_user_switch_callback(self._on_user_switch)
        self._profile_screen.set_user_create_callback(self._on_user_create)
        self._profile_screen.set_user_delete_callback(self._on_user_delete)

        # Profile section in settings
        self._settings_screen.set_profile_callbacks(
            on_switch=self._on_user_switch,
            on_create=self._on_user_create,
            on_delete=self._on_user_delete,
        )

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

        Uses Popup instead of the wizard Screen because Kivy TextInput
        doesn't get keyboard focus inside a Screen on some Android
        devices and on early-display screens.
        """
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))

        welcome = Label(
            text="Welcome! Enter your name\nto create a profile:",
            font_size=F.BODY, color=C.TEXT,
            size_hint_y=None, height=dp(48),
            halign="center",
        )
        welcome.bind(size=welcome.setter("text_size"))
        content.add_widget(welcome)

        from kivy.uix.textinput import TextInput as _TI
        name_input = _TI(
            hint_text="Your name...",
            multiline=False,
            font_size=F.H2,
            size_hint_y=None,
            height=dp(48),
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
        )
        content.add_widget(name_input)

        error_label = Label(
            text="", font_size=F.SMALL, color=C.DANGER,
            size_hint_y=None, height=dp(20),
        )
        content.add_widget(error_label)

        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok_btn = StyledButton(
            text="Create Profile", bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM,
        )
        btn_row.add_widget(ok_btn)
        content.add_widget(btn_row)

        popup = Popup(
            title="First-time Setup",
            content=content,
            size_hint=(0.85, 0.45),
            auto_dismiss=False,
        )

        def _on_ok(*_args):
            name = name_input.text.strip()
            if not name or len(name) < 2:
                error_label.text = "Name must be at least 2 characters"
                return
            popup.dismiss()
            # Reuse the existing wizard-complete flow (with no device)
            self._on_wizard_complete(name, None, None)

        ok_btn.bind(on_release=_on_ok)
        name_input.bind(on_text_validate=_on_ok)
        popup.open()

    def _on_wizard_complete(self, user_name: str, device_addr, device_name) -> None:
        """Wizard finished: create user, optionally set device, go to session."""
        if not user_name or len(user_name.strip()) < 2:
            logger.warning(f"Wizard complete with invalid name: '{user_name}', ignoring")
            return
        # Create user
        try:
            self._db.create_user(user_name)
        except Exception as e:
            logger.warning(f"Wizard user create failed: {e}")
        users = self._db.get_all_users()
        for u in users:
            if u["name"] == user_name:
                self._current_user_id = u["id"]
                self._db.set_setting("last_user_id", str(u["id"]))
                break

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
        import threading

        def _run():
            from kivy.clock import Clock as _Clock
            devices = NeuroSkyStream.scan_paired_devices()
            _Clock.schedule_once(lambda dt: self._wizard_screen.populate_devices(devices))

        threading.Thread(target=_run, daemon=True).start()

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
            # Auto-select first MindWave device
            for dev in devices:
                name = (dev.get("name") or "").lower()
                if "mindwave" in name or "neurosky" in name:
                    self._on_device_select(dev["address"], dev["name"])
                    logger.info(f"Auto-selected BT device: {dev['name']}")
                    return
            # No MindWave found — populate settings list for manual pick
            self._settings_screen.populate_bt_devices(devices)

        import threading

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
        elif name == "analytics":
            self._refresh_analytics()
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

        import threading

        def _scan_and_connect():
            devices = NeuroSkyStream.scan_paired_devices()
            mindwave = None
            for dev in devices:
                name = (dev.get("name") or "").lower()
                if "mindwave" in name or "neurosky" in name:
                    mindwave = dev
                    break

            def _on_main_thread(dt):
                if mindwave:
                    self._on_device_select(mindwave["address"], mindwave["name"])
                    self._eeg_stream = self._real_stream
                    self._live_screen.update_overlay(
                        f"Found {mindwave['name']}\nConnecting..."
                    )
                    self._start_session_common()
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

    def _start_session_common(self) -> None:
        """Shared session startup logic after device is resolved."""
        threshold = self._settings_screen.threshold
        self._metrics_engine.meditation_threshold = threshold
        self._audio.set_threshold(threshold)
        self._metrics_engine.reset()
        self._noise_detector = PowerLineDetector() if not APP.USE_MOCK_DEVICE else None
        self._metrics_buffer = []
        self._raw_buffer = []
        self._flush_counter = 0
        self._tick_count = 0
        self._current_session_id = None
        self._bt_connected_notified = False
        self._pending_marker = False
        self._bt_connect_start = time.time()

        self._live_screen.graph.clear_data()
        self._live_screen.raw_graph.clear_data()
        self._live_screen.band_graph.clear_data()
        self._live_screen.graph.set_threshold(float(threshold), "shamatha_score")
        self._live_screen.hide_alert()
        self._live_screen.set_controls_running()

        self._acquire_wake_lock()

        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.start()
            self._waiting_for_bt = False
            self._session_manager.start(threshold=threshold)
            self._audio.start()
            self._timer_screen.start_countdown()
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
            self._timer_screen.start_countdown()
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

        self._update_event = Clock.schedule_interval(
            self._update_tick, APP.UPDATE_FREQUENCY
        )
        self._tick_count = 0
        logger.info("Session started via UI")

    def _on_connect_cancel(self, *args) -> None:
        """Cancel button on connection overlay."""
        self._live_screen.hide_overlay()
        if self._waiting_for_bt or getattr(self, '_update_event', None):
            self._real_stream.stop()
            self._waiting_for_bt = False
            if self._update_event:
                self._update_event.cancel()
                self._update_event = None
            self._release_wake_lock()
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
        sid = self._live_screen.summary_session_id
        notes = self._live_screen.summary_notes
        if sid and notes:
            self._db.update_session_notes(sid, notes)
            self._mark_history_dirty()
            logger.info(f"Quick notes saved for session {sid}")
        self._live_screen.hide_summary()

    def _on_summary_history(self, *args) -> None:
        """Navigate to history from summary."""
        self._live_screen.hide_summary()
        self._switch_screen("history")

    def _on_summary_close(self, *args) -> None:
        """Close summary without saving notes."""
        self._live_screen.hide_summary()

    def _on_pause(self, *args) -> None:
        if self._session_manager.state == SessionState.RUNNING:
            self._session_manager.pause()
            self._live_screen.set_controls_paused()
            self._audio.stop()
            if self._update_event:
                self._update_event.cancel()
            logger.info("Session paused")
        elif self._session_manager.state == SessionState.PAUSED:
            self._session_manager.resume()
            self._live_screen.set_controls_running()
            self._audio.start()
            self._update_event = Clock.schedule_interval(
                self._update_tick, APP.UPDATE_FREQUENCY
            )
            logger.info("Session resumed")

    def _on_stop(self, *args) -> None:
        # If still waiting for BT, session never started — just clean up
        if getattr(self, '_waiting_for_bt', False):
            if self._update_event:
                self._update_event.cancel()
                self._update_event = None
            self._waiting_for_bt = False
            self._eeg_stream.stop()
            self._live_screen.set_controls_idle()
            self._live_screen.update_device_status(False)
            self._live_screen.update_state("Cancelled")
            self._timer_screen.reset()
            self._release_wake_lock()
            logger.info("Session cancelled during BT connection wait")
            return

        # Pause the update loop while the dialog is open
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None

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

    def _stop_and_save(self) -> None:
        """Stop session and save data immediately (no dialog)."""
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None

        stats = self._session_manager.stop()
        # Keep real BT connection alive between sessions to avoid EBUSY on reconnect.
        # Only the mock stream gets stopped here; real stream stays connected.
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.stop()
        self._audio.stop()

        if stats:
            if self._current_session_id is not None:
                self._db.update_session(self._current_session_id, stats)
            else:
                self._current_session_id = self._db.save_session(
                    stats, user_id=self._current_user_id,
                    session_name=self._make_session_name(),
                )
            if self._metrics_buffer:
                self._db.save_metrics_batch(self._current_session_id, self._metrics_buffer)
                self._metrics_buffer = []

        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._live_screen.update_state("FINISHED")
        self._timer_screen.reset()
        self._session_manager.reset()
        self._release_wake_lock()
        self._mark_history_dirty()

        if stats and self._current_session_id:
            self._live_screen.show_summary(self._current_session_id, stats)
        logger.info("Session stopped and saved")

    def _cancel_stop(self, popup) -> None:
        """Resume the session after cancelling stop."""
        popup.dismiss()
        self._update_event = Clock.schedule_interval(
            self._update_tick, APP.UPDATE_FREQUENCY
        )
        logger.info("Stop cancelled, session resumed")

    def _finish_stop(self, popup, save: bool) -> None:
        """Finish stopping the session, optionally saving data."""
        popup.dismiss()

        stats = self._session_manager.stop()
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream.stop()
        self._audio.stop()

        if save and stats:
            if self._current_session_id is not None:
                self._db.update_session(self._current_session_id, stats)
            else:
                self._current_session_id = self._db.save_session(
                    stats, user_id=self._current_user_id,
                    session_name=self._make_session_name(),
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
        self._timer_screen.reset()
        self._session_manager.reset()
        self._release_wake_lock()
        self._mark_history_dirty()

        if save and stats and self._current_session_id:
            self._live_screen.show_summary(self._current_session_id, stats)

    _BT_CONNECT_TIMEOUT = 30.0  # seconds before BT socket gives up
    _BT_SIGNAL_TIMEOUT = 8.0   # seconds to wait for EEG packets after connected
    _STALE_DATA_THRESHOLD = 10.0  # seconds with no new packets before warning

    def _check_stale_data(self) -> None:
        """Auto-stop session when the real device stops sending EEG data."""
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
                self._live_screen.show_alert(
                    "No new EEG data for 10s.\n"
                    "Session stopped. Check headset."
                )
                self._stop_and_save()
        else:
            self._stale_data_warned = False

    def _handle_bt_wait(self) -> None:
        """Handle the BT connection wait phase (called from _update_tick)."""
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
                    self._audio.start()
                    self._audio.play_connect_sound()
                    self._timer_screen.start_countdown()
                    self._live_screen.update_device_status(
                        True, device_name=name
                    )
                    self._live_screen.update_state("Running")
                    self._live_screen.set_start_time(time.time())
                    self._live_screen.hide_overlay()
                    self._settings_screen.update_device_status(True, name=name)
                    logger.info(f"BT device {name} connected, session started")
                elif signal_elapsed > self._BT_SIGNAL_TIMEOUT and not has_packets:
                    # No packets — ThinkGear didn't start streaming.
                    # Don't try RFCOMM reconnect: closing the socket triggers
                    # EBUSY that blocks reconnection for 60+ seconds.
                    # The only reliable fix is a headset power cycle.
                    self._waiting_for_bt = False
                    self._bt_signal_start = None
                    self._real_stream.stop()
                    if self._update_event:
                        self._update_event.cancel()
                        self._update_event = None
                    self._live_screen.set_controls_idle()
                    self._live_screen.update_device_status(False, device_name=name)
                    self._live_screen.show_overlay_retry(
                        f"Connected to {name} but\n"
                        "headset not streaming.\n"
                        "Try replacing the battery,\n"
                        "or turn OFF, wait 5 sec, turn ON."
                    )
                    self._release_wake_lock()
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
                    self._live_screen.update_overlay(
                        f"Connected to {name}\n"
                        f"{wait_msg}\n"
                        f"{sensor_info}"
                    )
        elif not self._real_stream._running:
            # Connection thread ended with error
            self._waiting_for_bt = False
            self._bt_signal_start = None
            if self._update_event:
                self._update_event.cancel()
                self._update_event = None
            self._live_screen.set_controls_idle()
            self._live_screen.update_device_status(False)
            hint = self._real_stream._last_connect_error or "Check device is on and paired."
            self._live_screen.show_overlay_retry(
                f"Connection to {name} failed.\n{hint}"
            )
            logger.error("BT connection failed, session aborted")
        elif elapsed > self._BT_CONNECT_TIMEOUT:
            # Timeout waiting for BT socket
            self._waiting_for_bt = False
            self._bt_signal_start = None
            self._real_stream.stop()
            if self._update_event:
                self._update_event.cancel()
                self._update_event = None
            self._live_screen.set_controls_idle()
            self._live_screen.update_device_status(False)
            self._live_screen.show_overlay_retry(
                f"Connection to {name} timed out.\n"
                "Make sure the device is turned on\nand in range."
            )
            self._release_wake_lock()
            logger.error("BT connection timed out")
        else:
            # Still waiting for BT socket — show countdown
            remaining = int(self._BT_CONNECT_TIMEOUT - elapsed)
            self._live_screen.update_overlay(
                f"Connecting to {name}...\nTimeout in {remaining}s"
            )

    def _update_tick(self, dt: float) -> None:
        """Main 2 Hz processing loop."""
        if getattr(self, '_waiting_for_bt', False):
            self._handle_bt_wait()
            return

        if self._session_manager.state != SessionState.RUNNING:
            return

        # Auto-stop when session reaches max duration
        if self._session_manager.elapsed_seconds >= APP.SESSION_MAX_SECONDS:
            logger.info(f"Session reached max duration ({APP.SESSION_MAX_SECONDS}s), auto-stopping")
            self._audio.play_disconnect_alert()
            self._live_screen.show_alert(
                f"Session recording limit reached ({APP.SESSION_MAX_SECONDS // 3600}h). "
                "Session saved. Start a new one to continue."
            )
            self._stop_and_save()
            return

        # Update settings status when real BT device connects
        if (not self._bt_connected_notified
                and not APP.USE_MOCK_DEVICE
                and self._real_stream.is_connected):
            self._bt_connected_notified = True
            name = self._real_stream._device_name or "Real EEG"
            self._settings_screen.update_device_status(True, name=name)
            logger.info(f"Settings updated: {name} connected")

        # Detect BT disconnect during session
        if (not APP.USE_MOCK_DEVICE
                and self._bt_connected_notified
                and not self._real_stream.is_connected):
            self._bt_connected_notified = False
            name = self._real_stream._device_name or "Real EEG"
            self._live_screen.update_device_status(
                False, device_name=name, connecting=True
            )
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
            self._live_screen.show_alert(
                f"Low headset battery ({pct}%).\n"
                "Replace battery soon to avoid\n"
                "connection problems."
            )
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
                    self._live_screen.show_alert(
                        f"Warning: {freq} Hz power line noise detected. "
                        f"Check notch filter setting or move away from electrical equipment."
                    )
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

        # Evaluate custom formula if active
        if self._custom_formula.is_valid:
            formula_vars = {**raw_sample, **metrics}
            bands = self._metrics_engine.derive_bands(raw_sample)
            formula_vars.update(bands)
            # Add sqrt-normalized relative bands (s_ prefix)
            sqrt_bands = self._metrics_engine.compute_sqrt_relative_bands(raw_sample)
            formula_vars.update({f"s_{k}": v for k, v in sqrt_bands.items()})
            self._custom_formula.push_variables(formula_vars)
            metrics["custom_formula"] = self._custom_formula.evaluate(formula_vars)

        self._session_manager.add_metric(metrics)
        # Merge raw + computed for full storage
        full_record = {**raw_sample, **metrics}
        self._metrics_buffer.append(full_record)
        self._raw_buffer.append(raw_sample)

        self._audio.update(metrics.get(self._audio_metric_key, 0))
        if self._tick_count > 10:
            self._audio.update_sinking(metrics.get("sinking", 0))
            self._audio.update_subtle_distraction(metrics.get("subtle_distraction", 0))

        self._live_screen.graph.add_point(metrics)
        self._live_screen.update_stats(metrics)
        self._live_screen.update_state(metrics.get("state", "Neutral"))
        self._live_screen.update_timer(self._session_manager.elapsed_formatted)

        self._live_screen.add_raw_sample(raw_sample)

        # Handle pending marker (after points added so indices are current)
        if self._pending_marker:
            self._pending_marker = False
            full_record["marker"] = 1
            self._live_screen.graph.add_marker()
            self._live_screen.raw_graph.add_marker()
            self._live_screen.band_graph.add_marker()

        # Timer countdown
        if self._timer_screen.tick(APP.UPDATE_FREQUENCY):
            logger.info("Timer expired, auto-stopping session")
            self._audio.play_timer_sound(self._timer_screen.custom_sound_path)
            self._stop_and_save()
            return

        # Flush buffer to DB every 60 seconds
        self._flush_counter += 1
        ticks_per_flush = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY)
        if self._flush_counter >= ticks_per_flush and self._metrics_buffer:
            if self._current_session_id is None:
                stats_partial = self._session_manager.compute_statistics()
                self._current_session_id = self._db.save_session(
                    stats_partial, user_id=self._current_user_id,
                    session_name=self._make_session_name(),
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

    def _on_marker(self, *args) -> None:
        """Place a marker at the current position in the session."""
        if self._session_manager.state == SessionState.RUNNING:
            self._pending_marker = True
            logger.info("Marker placed")

    def _on_threshold_change(self, value: int) -> None:
        self._metrics_engine.meditation_threshold = value
        self._audio.set_threshold(value)
        self._live_screen.graph.set_threshold(float(value), "shamatha_score")
        logger.debug(f"Threshold changed to {value}")

    def _on_toggle_change(self, metric: str, active: bool) -> None:
        self._live_screen.graph.set_visible(metric, active)
        if metric == "sinking":
            self._audio.sinking_alert_enabled = active
            self._settings_screen._sinking_alert_cb.active = active
        logger.debug(f"Graph toggle: {metric}={'on' if active else 'off'}")

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
        from kivy.core.window import Window
        Window.rotation = rotation
        logger.info(f"Screen rotation set to {rotation}")

    def _on_custom_formula_visible_toggle(self, active: bool) -> None:
        """Toggle custom formula line visibility on graph."""
        show = active and self._custom_formula.is_valid
        self._live_screen.graph.set_visible("custom_formula", show)
        logger.debug(f"Custom formula visibility: {show}")

    def _on_audio_metric_change(self, key: str) -> None:
        """Switch which metric drives the audio threshold feedback."""
        self._audio_metric_key = key
        logger.info(f"Audio threshold metric changed to: {key}")

    def _on_theme_change(self, theme_name: str) -> None:
        """Save selected theme."""
        self._db.set_setting("theme", theme_name)
        logger.info(f"Theme changed to: {theme_name}")

    def _on_custom_formula_change(self, formula: str) -> None:
        """Handle custom formula change from settings."""
        if not formula:
            self._custom_formula.set_formula("")
            self._live_screen.graph.set_visible("custom_formula", False)
            self._settings_screen.set_formula_status("Formula cleared")
            logger.info("Custom formula cleared")
            return
        ok, err = self._custom_formula.set_formula(formula)
        if ok:
            show = self._settings_screen.custom_formula_visible
            self._live_screen.graph.set_visible("custom_formula", show)
            self._settings_screen.set_formula_status("Formula active")
            logger.info(f"Custom formula applied: {formula}")
        else:
            self._live_screen.graph.set_visible("custom_formula", False)
            self._settings_screen.set_formula_status(f"Error: {err}", is_error=True)

    def _on_save_formula(self, formula: str) -> None:
        """Save the current formula to the user's saved list."""
        if not self._current_user_id:
            self._settings_screen.set_formula_status("No user selected", is_error=True)
            return
        # Use a truncated version as the name
        name = formula[:40] + ("..." if len(formula) > 40 else "")
        ok = self._db.add_saved_formula(self._current_user_id, name, formula)
        if ok:
            self._settings_screen.set_formula_status("Formula saved")
            self._refresh_saved_formulas()
            logger.info(f"Formula saved: {formula}")
        else:
            self._settings_screen.set_formula_status("Limit reached (50 max)", is_error=True)

    def _on_load_formula(self, index: int) -> None:
        """Load a saved formula into the input and apply it."""
        if not self._current_user_id:
            return
        formulas = self._db.get_saved_formulas(self._current_user_id)
        if 0 <= index < len(formulas):
            formula = formulas[index]["formula"]
            self._settings_screen._formula_input.text = formula
            self._on_custom_formula_change(formula)

    def _on_delete_formula(self, index: int) -> None:
        """Delete a saved formula."""
        if not self._current_user_id:
            return
        self._db.remove_saved_formula(self._current_user_id, index)
        self._refresh_saved_formulas()
        self._settings_screen.set_formula_status("Formula deleted")
        logger.info(f"Saved formula #{index} deleted")

    def _on_export_formulas(self) -> None:
        """Export saved formulas to a text file."""
        if not self._current_user_id:
            self._settings_screen.set_formula_status("No user selected", is_error=True)
            return
        formulas = self._db.get_saved_formulas(self._current_user_id)
        if not formulas:
            self._settings_screen.set_formula_status("No formulas to export", is_error=True)
            return
        export_dir = os.path.dirname(self._db._db_path)
        path = os.path.join(export_dir, f"formulas_user_{self._current_user_id}.txt")
        with open(path, "w") as f:
            for entry in formulas:
                f.write(f"{entry['formula']}\n")
        self._settings_screen.set_formula_status(f"Exported to {os.path.basename(path)}")
        logger.info(f"Exported {len(formulas)} formulas to {path}")

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
        logger.debug(f"Test timer sound, path='{self._timer_screen.custom_sound_path}'")
        self._audio.play_timer_sound(self._timer_screen.custom_sound_path)

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

    def _on_session_select(self, session_id: int) -> None:
        session = self._db.get_session(session_id)
        if session:
            self._diary_screen.show_session_detail(session)
            threshold_used = session.get("threshold_used", 50)
            self._diary_screen.set_metrics_threshold(float(threshold_used))
            metrics = self._db.get_session_metrics(session_id)
            self._diary_screen.load_metrics_preview(metrics)
            # Navigate to diary detail view; remember where we came from
            self._session_detail_back = self._sm.current
            self._sm.current = "diary"

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
            session_id, custom_formula=self._custom_formula
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
        sessions = self._db.get_all_sessions(user_id=self._current_user_id)
        self._history_screen.load_sessions(sessions)
        self._history_dirty = False

    def _mark_history_dirty(self) -> None:
        self._history_dirty = True

    def _refresh_diary(self) -> None:
        sessions = self._db.get_all_sessions(user_id=self._current_user_id)
        self._diary_screen.populate_sessions(sessions)

    def _refresh_analytics(self) -> None:
        summary = self._analytics.get_summary()
        self._analytics_screen.update_summary(summary)
        self._analytics_screen.update_storage_info(
            self._db.get_db_size_bytes(),
            self._db.get_record_counts(),
        )
        self._load_analytics("daily")

    def _load_analytics(self, period: str) -> None:
        if period == "daily":
            data = self._analytics.get_daily_stats(days=30)
        elif period == "weekly":
            data = self._analytics.get_weekly_stats(weeks=12)
        else:
            data = self._analytics.get_monthly_stats(months=12)
        self._analytics_screen.show_trend(data, "avg_shamatha", f"Shamatha ({period})")

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

    def _on_user_create(self, name: str) -> None:
        """Create a new user and refresh the profile list."""
        try:
            self._db.create_user(name)
        except Exception as e:
            logger.warning(f"Could not create user '{name}': {e}")
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
        # Sync timer from settings screen to timer screen
        self._timer_screen._enable_cb.active = self._settings_screen.timer_enabled
        self._timer_screen._set_duration(self._settings_screen.timer_minutes)
        self._db.set_user_setting(uid, "timer_enabled", str(self._settings_screen.timer_enabled))
        self._db.set_user_setting(uid, "timer_minutes", str(self._settings_screen.timer_minutes))
        self._db.set_user_setting(uid, "timer_sound", self._timer_screen.custom_sound_path)
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
        self._db.set_user_setting(
            uid, "custom_formula", self._custom_formula.formula
        )
        # Save zoom level as viewport duration in seconds
        graph = self._live_screen.graph
        zoom_seconds = graph.viewport_points / graph._sample_rate
        self._db.set_user_setting(uid, "graph_zoom_seconds", str(zoom_seconds))
        toggles = self._settings_screen.graph_toggles
        for key, active in toggles.items():
            self._db.set_user_setting(uid, f"toggle_{key}", str(active))
        self._db.set_user_setting(
            uid, "custom_formula_visible",
            str(self._settings_screen.custom_formula_visible),
        )
        self._db.set_user_setting(uid, "audio_metric", self._audio_metric_key)
        self._db.set_user_setting(uid, "marker_hotkey", self._settings_screen.marker_hotkey)
        logger.debug(f"Saved settings for user {uid}")

    def _load_user_settings(self, user_id: int) -> None:
        """Restore persisted settings for a user."""
        g = self._db.get_user_setting

        timer_on = g(user_id, "timer_enabled")
        if timer_on is not None:
            active = timer_on == "True"
            self._timer_screen._enable_cb.active = active
            self._settings_screen.timer_enabled = active

        timer_min = g(user_id, "timer_minutes")
        if timer_min is not None:
            try:
                val = int(timer_min)
                self._timer_screen._set_duration(val)
                self._settings_screen.timer_minutes = val
            except (ValueError, TypeError):
                pass

        timer_sound = g(user_id, "timer_sound")
        if timer_sound is not None:
            self._timer_screen._sound_path_input.text = timer_sound

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

        for key, cb in self._settings_screen._checkboxes.items():
            saved = g(user_id, f"toggle_{key}")
            if saved is not None:
                active = saved == "True"
                cb.active = active
                self._live_screen.graph.set_visible(key, active)

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

        saved_formula = g(user_id, "custom_formula")
        if saved_formula:
            self._settings_screen._formula_input.text = saved_formula
            self._on_custom_formula_change(saved_formula)
        else:
            self._settings_screen._formula_input.text = ""
            self._on_custom_formula_change("")

        cf_vis = g(user_id, "custom_formula_visible")
        if cf_vis is not None:
            self._settings_screen.custom_formula_visible = cf_vis == "True"
            self._on_custom_formula_visible_toggle(cf_vis == "True")

        audio_met = g(user_id, "audio_metric")
        if audio_met is not None:
            self._settings_screen.audio_metric = audio_met
            self._audio_metric_key = audio_met

        marker_hk = g(user_id, "marker_hotkey")
        if marker_hk is not None:
            self._settings_screen.marker_hotkey = marker_hk

        self._refresh_saved_formulas()
        logger.debug(f"Loaded settings for user {user_id}")

    def on_pause(self) -> bool:
        """Called when app is paused (Android home/switch). Save settings
        because the OS may kill the process without calling on_stop."""
        self._save_user_settings()
        return True

    def on_stop(self) -> None:
        """Cleanup on app exit.

        We intentionally do NOT call _real_stream.stop() here.  Letting the
        process exit naturally allows the kernel to close the RFCOMM socket
        while BlueZ may keep the ACL link alive.  This means the *next* app
        launch can open a fresh RFCOMM on the existing ACL link and the
        ThinkGear ASIC will resume streaming immediately — avoiding the
        "connected but no packets" problem caused by a stale ACL.
        """
        self._save_user_settings()
        if self._session_manager.state in (SessionState.RUNNING, SessionState.PAUSED):
            self._stop_and_save()
        self._audio.cleanup()
        self._db.close()
        logger.info("Application closed")
