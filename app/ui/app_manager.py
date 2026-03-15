import os
from typing import Dict, List, Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.actionbar import ActionBar, ActionButton, ActionPrevious, ActionView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, SlideTransition

from app.analytics.aggregator import AnalyticsAggregator
from app.audio_feedback.noise import AudioEngine
from app.config import APP
from app.eeg.mock_stream_v2 import MockEEGStream
from app.eeg.neurosky_stream import NeuroSkyStream
from app.logger import logger
from app.metrics.engine import MetricsEngine
from app.session.manager import SessionManager, SessionState
from app.storage.database import DatabaseManager
from app.ui.analytics_screen import AnalyticsScreen
from app.ui.diary_screen import DiaryScreen
from app.ui.live_session import LiveSessionScreen
from app.ui.profile_screen import ProfileScreen
from app.ui.raw_eeg_screen import RawEEGScreen
from app.ui.settings_screen import SettingsScreen
from app.ui.timer_screen import TimerScreen


class EEGMeditationApp(App):
    """Main Kivy application for EEG Meditation Trainer."""

    title = APP.APP_NAME

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
        self._metrics_buffer: List[Dict] = []
        self._raw_buffer: List[Dict] = []
        self._flush_counter: int = 0
        self._current_session_id: Optional[int] = None
        self._current_user_id: Optional[int] = None

    def build(self) -> BoxLayout:
        root = BoxLayout(orientation="vertical")

        nav_bar = ActionBar(size_hint_y=None, height=dp(48))
        av = ActionView()
        ap = ActionPrevious(title="EEG Meditation", with_previous=False)
        av.add_widget(ap)

        btn_session = ActionButton(text="Session")
        btn_session.bind(on_release=lambda x: self._switch_screen("live_session"))
        btn_raw = ActionButton(text="Raw EEG")
        btn_raw.bind(on_release=lambda x: self._switch_screen("raw_eeg"))
        btn_settings = ActionButton(text="Settings")
        btn_settings.bind(on_release=lambda x: self._switch_screen("settings"))
        self._btn_diary = ActionButton(text="Diary")
        self._btn_diary.bind(on_release=lambda x: self._switch_screen("diary"))
        btn_analytics = ActionButton(text="Analytics")
        btn_analytics.bind(on_release=lambda x: self._switch_screen("analytics"))
        btn_timer = ActionButton(text="Timer")
        btn_timer.bind(on_release=lambda x: self._switch_screen("timer"))
        btn_profile = ActionButton(text="Profile")
        btn_profile.bind(on_release=lambda x: self._switch_screen("profile"))

        av.add_widget(btn_session)
        av.add_widget(btn_raw)
        av.add_widget(btn_settings)
        av.add_widget(btn_timer)
        av.add_widget(self._btn_diary)
        av.add_widget(btn_analytics)
        av.add_widget(btn_profile)
        nav_bar.add_widget(av)
        root.add_widget(nav_bar)

        self._sm = ScreenManager(transition=SlideTransition())

        self._live_screen = LiveSessionScreen()
        self._raw_eeg_screen = RawEEGScreen()
        self._settings_screen = SettingsScreen()
        self._diary_screen = DiaryScreen()
        self._analytics_screen = AnalyticsScreen()
        self._profile_screen = ProfileScreen()
        self._timer_screen = TimerScreen()

        self._sm.add_widget(self._profile_screen)
        self._sm.add_widget(self._live_screen)
        self._sm.add_widget(self._raw_eeg_screen)
        self._sm.add_widget(self._settings_screen)
        self._sm.add_widget(self._diary_screen)
        self._sm.add_widget(self._analytics_screen)
        self._sm.add_widget(self._timer_screen)

        root.add_widget(self._sm)

        self._bind_callbacks()
        self._restore_last_user()
        self._refresh_profile()
        self._update_diary_visibility()
        return root

    def _bind_callbacks(self) -> None:
        self._live_screen.btn_start.bind(on_release=self._on_start)
        self._live_screen.btn_pause.bind(on_release=self._on_pause)
        self._live_screen.btn_stop.bind(on_release=self._on_stop)

        self._settings_screen.set_threshold_callback(self._on_threshold_change)
        self._settings_screen.set_toggle_callback(self._on_toggle_change)
        self._settings_screen.set_test_audio_callback(self._on_test_audio)
        self._settings_screen.set_sinking_alert_callback(self._on_sinking_alert_toggle)
        self._settings_screen.set_disconnect_alert_callback(self._on_disconnect_alert_toggle)
        self._settings_screen.set_device_mode_callback(self._on_device_mode_toggle)
        self._settings_screen.set_scan_devices_callback(self._on_scan_devices)
        self._settings_screen.set_device_select_callback(self._on_device_select)

        self._diary_screen.set_session_select_callback(self._on_session_select)
        self._diary_screen.set_save_notes_callback(self._on_save_notes)
        self._diary_screen.set_export_csv_callback(self._on_export_csv)
        self._diary_screen.set_delete_session_callback(self._on_delete_session)
        self._diary_screen.set_rename_session_callback(self._on_rename_session)

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

    def _update_diary_visibility(self) -> None:
        """Disable diary nav button when no user is selected."""
        has_user = self._current_user_id is not None
        self._btn_diary.disabled = not has_user

    def _switch_screen(self, name: str) -> None:
        if name == "diary" and not self._current_user_id:
            logger.debug("Diary switch blocked: no user selected")
            return
        logger.debug(f"Screen switch: {name}")
        self._sm.current = name
        if name == "diary":
            self._refresh_diary()
        elif name == "analytics":
            self._refresh_analytics()
        elif name == "profile":
            self._refresh_profile()

    def _on_start(self, *args) -> None:
        if not self._current_user_id:
            self._live_screen.update_state("Select a user profile first")
            logger.warning("Session start blocked: no user selected")
            return
        if APP.USE_MOCK_DEVICE:
            self._eeg_stream = self._mock_stream
        else:
            if not self._real_stream._device_address:
                self._live_screen.update_state("No device selected (scan in Settings)")
                logger.warning("Session start blocked: no BT device selected")
                return
            self._eeg_stream = self._real_stream
        threshold = self._settings_screen.threshold
        self._metrics_engine.meditation_threshold = threshold
        self._audio.set_threshold(threshold)

        self._session_manager.start(threshold=threshold)
        self._eeg_stream.start()
        self._metrics_engine.reset()
        self._metrics_buffer = []
        self._raw_buffer = []
        self._flush_counter = 0
        self._tick_count = 0
        self._current_session_id = None

        self._audio.start()
        self._timer_screen.start_countdown()
        self._live_screen.set_controls_running()
        self._bt_connected_notified = False
        if APP.USE_MOCK_DEVICE:
            self._live_screen.update_device_status(True)
        else:
            self._live_screen.update_device_status(
                True, device_name=self._real_stream._device_name or "Real EEG"
            )
        self._live_screen.graph.clear_data()
        self._raw_eeg_screen.raw_graph.clear_data()
        self._raw_eeg_screen.band_graph.clear_data()

        self._live_screen.graph.set_threshold(float(threshold), "meditation_score")

        self._update_event = Clock.schedule_interval(
            self._update_tick, APP.UPDATE_FREQUENCY
        )
        self._tick_count: int = 0
        logger.info("Session started via UI")

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
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None

        stats = self._session_manager.stop()
        self._eeg_stream.stop()
        self._audio.stop()

        if stats:
            if self._current_session_id is not None:
                self._db.update_session(self._current_session_id, stats)
            else:
                self._current_session_id = self._db.save_session(
                    stats, user_id=self._current_user_id
                )
            if self._metrics_buffer:
                self._db.save_metrics_batch(self._current_session_id, self._metrics_buffer)
                self._metrics_buffer = []

        self._live_screen.set_controls_idle()
        self._live_screen.update_device_status(False)
        self._live_screen.update_state("FINISHED")
        self._timer_screen.reset()
        self._session_manager.reset()
        logger.info("Session stopped via UI")

    def _update_tick(self, dt: float) -> None:
        """Main 2 Hz processing loop."""
        if self._session_manager.state != SessionState.RUNNING:
            return

        # Update settings status when real BT device connects
        if (not self._bt_connected_notified
                and not APP.USE_MOCK_DEVICE
                and self._real_stream.is_connected):
            self._bt_connected_notified = True
            name = self._real_stream._device_name or "Real EEG"
            self._settings_screen.update_device_status(True, name=name)
            logger.info(f"Settings updated: {name} connected")

        raw_sample = self._eeg_stream.read_sample()
        metrics = self._metrics_engine.process_sample(raw_sample)

        # Log raw sample every 10 ticks (~5s at 2Hz)
        self._tick_count = getattr(self, '_tick_count', 0) + 1
        if self._tick_count % 10 == 0:
            bands = {k: f"{raw_sample.get(k, 0):.0f}" for k in
                     ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2")}
            logger.debug(f"Raw sample #{self._tick_count}: {bands}")
            native_med = raw_sample.get("meditation", -1)
            logger.debug(f"Metrics: med={metrics.get('meditation_score', 0):.0f} "
                         f"sham={metrics.get('shamatha_score', 0):.0f} "
                         f"sink={metrics.get('sinking', 0):.0f} "
                         f"dist={metrics.get('distraction', 0):.0f} "
                         f"native_med={native_med:.0f}")

        self._session_manager.add_metric(metrics)
        # Merge raw + computed for full storage
        full_record = {**raw_sample, **metrics}
        self._metrics_buffer.append(full_record)
        self._raw_buffer.append(raw_sample)

        self._audio.update(metrics.get("meditation_score", 0))
        if self._tick_count > 10:
            self._audio.update_sinking(metrics.get("sinking", 0))

        self._live_screen.graph.add_point(metrics)
        self._live_screen.update_scroll_range()
        self._live_screen.update_stats(metrics)
        self._live_screen.update_state(metrics.get("state", "Neutral"))
        self._live_screen.update_timer(self._session_manager.elapsed_formatted)

        self._raw_eeg_screen.add_raw_sample(raw_sample)

        # Timer countdown
        if self._timer_screen.tick(APP.UPDATE_FREQUENCY):
            logger.info("Timer expired, auto-stopping session")
            self._audio.play_timer_sound(self._timer_screen.custom_sound_path)
            self._on_stop()
            return

        # Flush buffer to DB every 60 seconds
        self._flush_counter += 1
        ticks_per_flush = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY)
        if self._flush_counter >= ticks_per_flush and self._metrics_buffer:
            if self._current_session_id is None:
                stats_partial = self._session_manager.compute_statistics()
                self._current_session_id = self._db.save_session(
                    stats_partial, user_id=self._current_user_id
                )
            self._db.save_metrics_batch(self._current_session_id, self._metrics_buffer)
            self._metrics_buffer = []
            self._flush_counter = 0

    def _on_threshold_change(self, value: int) -> None:
        self._metrics_engine.meditation_threshold = value
        self._audio.set_threshold(value)
        self._live_screen.graph.set_threshold(float(value), "meditation_score")
        logger.debug(f"Threshold changed to {value}")

    def _on_toggle_change(self, metric: str, active: bool) -> None:
        self._live_screen.graph.set_visible(metric, active)
        logger.debug(f"Graph toggle: {metric}={'on' if active else 'off'}")

    def _on_test_audio(self) -> None:
        logger.debug("Test audio triggered")
        self._audio.test_audio()

    def _on_sinking_alert_toggle(self, active: bool) -> None:
        self._audio.sinking_alert_enabled = active
        logger.info(f"Sinking alert {'enabled' if active else 'disabled'}")

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
        else:
            addr = self._real_stream._device_address or "none"
            self._settings_screen.update_device_status(False, meta=f"Mode: Real Device ({addr})")
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

    def _on_save_notes(
        self, session_id: int, notes: str, tags: str, mood: int
    ) -> None:
        self._db.update_session_notes(session_id, notes, tags, mood)
        self._refresh_diary()
        logger.info(f"Notes saved for session {session_id}")

    def _on_delete_session(self, session_id: int) -> None:
        """Delete a session and refresh the diary list."""
        self._db.delete_session(session_id)
        self._refresh_diary()
        logger.info(f"Session {session_id} deleted")

    def _on_rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session (updates notes field) and refresh diary."""
        self._db.rename_session(session_id, new_name)
        self._refresh_diary()
        logger.info(f"Session {session_id} renamed to '{new_name}'")

    def _on_export_csv(self, session_id: int) -> Optional[str]:
        """Export session data as CSV file. Returns file path or None."""
        csv_data = self._db.export_session_csv(session_id)
        if not csv_data:
            return None
        export_dir = os.path.dirname(self._db._db_path)
        path = os.path.join(export_dir, f"session_{session_id}.csv")
        with open(path, "w") as f:
            f.write(csv_data)
        logger.info(f"Session {session_id} exported to {path}")
        return path

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
        self._update_diary_visibility()
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

    def _save_user_settings(self) -> None:
        """Persist current UI settings for the active user."""
        uid = self._current_user_id
        if not uid:
            return
        self._db.set_user_setting(uid, "timer_enabled", str(self._timer_screen.enabled))
        self._db.set_user_setting(uid, "timer_minutes", str(self._timer_screen._duration_minutes))
        self._db.set_user_setting(uid, "timer_sound", self._timer_screen.custom_sound_path)
        self._db.set_user_setting(uid, "sinking_alert", str(self._audio.sinking_alert_enabled))
        self._db.set_user_setting(uid, "disconnect_alert", str(self._audio.disconnect_alert_enabled))
        self._db.set_user_setting(uid, "threshold", str(self._settings_screen.threshold))
        self._db.set_user_setting(uid, "use_mock", str(APP.USE_MOCK_DEVICE))
        toggles = self._settings_screen.graph_toggles
        for key, active in toggles.items():
            self._db.set_user_setting(uid, f"toggle_{key}", str(active))
        logger.debug(f"Saved settings for user {uid}")

    def _load_user_settings(self, user_id: int) -> None:
        """Restore persisted settings for a user."""
        g = self._db.get_user_setting

        timer_on = g(user_id, "timer_enabled")
        if timer_on is not None:
            active = timer_on == "True"
            self._timer_screen._enable_cb.active = active

        timer_min = g(user_id, "timer_minutes")
        if timer_min is not None:
            try:
                self._timer_screen._set_duration(int(timer_min))
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

        logger.debug(f"Loaded settings for user {user_id}")

    def on_stop(self) -> None:
        """Cleanup on app exit."""
        self._save_user_settings()
        if self._session_manager.state == SessionState.RUNNING:
            self._on_stop()
        self._audio.cleanup()
        self._db.close()
        logger.info("Application closed")
