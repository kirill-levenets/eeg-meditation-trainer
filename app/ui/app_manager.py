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
from app.eeg.mock_stream import MockEEGStream
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
        self._eeg_stream: MockEEGStream = MockEEGStream()
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
        btn_diary = ActionButton(text="Diary")
        btn_diary.bind(on_release=lambda x: self._switch_screen("diary"))
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
        av.add_widget(btn_diary)
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
        self._refresh_profile()
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

        self._diary_screen.set_session_select_callback(self._on_session_select)
        self._diary_screen.set_save_notes_callback(self._on_save_notes)
        self._diary_screen.set_export_csv_callback(self._on_export_csv)

        self._analytics_screen.btn_daily.bind(
            on_release=lambda x: self._load_analytics("daily")
        )
        self._analytics_screen.btn_weekly.bind(
            on_release=lambda x: self._load_analytics("weekly")
        )
        self._analytics_screen.btn_monthly.bind(
            on_release=lambda x: self._load_analytics("monthly")
        )

        self._profile_screen.set_user_switch_callback(self._on_user_switch)
        self._profile_screen.set_user_create_callback(self._on_user_create)
        self._profile_screen.set_user_delete_callback(self._on_user_delete)

    def _switch_screen(self, name: str) -> None:
        self._sm.current = name
        if name == "diary":
            self._refresh_diary()
        elif name == "analytics":
            self._refresh_analytics()
        elif name == "profile":
            self._refresh_profile()

    def _on_start(self, *args) -> None:
        threshold = self._settings_screen.threshold
        self._metrics_engine.meditation_threshold = threshold
        self._audio.set_threshold(threshold)

        self._session_manager.start(threshold=threshold)
        self._eeg_stream.start()
        self._metrics_engine.reset()
        self._metrics_buffer = []
        self._raw_buffer = []
        self._flush_counter = 0
        self._current_session_id = None

        self._audio.start()
        self._timer_screen.start_countdown()
        self._live_screen.set_controls_running()
        self._live_screen.update_device_status(True)
        self._live_screen.graph.clear_data()
        self._raw_eeg_screen.raw_graph.clear_data()
        self._raw_eeg_screen.band_graph.clear_data()

        self._update_event = Clock.schedule_interval(
            self._update_tick, APP.UPDATE_FREQUENCY
        )
        logger.info("Session started via UI")

    def _on_pause(self, *args) -> None:
        if self._session_manager.state == SessionState.RUNNING:
            self._session_manager.pause()
            self._live_screen.set_controls_paused()
            self._audio.stop()
            if self._update_event:
                self._update_event.cancel()
        elif self._session_manager.state == SessionState.PAUSED:
            self._session_manager.resume()
            self._live_screen.set_controls_running()
            self._audio.start()
            self._update_event = Clock.schedule_interval(
                self._update_tick, APP.UPDATE_FREQUENCY
            )

    def _on_stop(self, *args) -> None:
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None

        stats = self._session_manager.stop()
        self._eeg_stream.stop()
        self._audio.stop()

        if stats:
            session_id = self._db.save_session(stats, user_id=self._current_user_id)
            self._current_session_id = session_id
            if self._metrics_buffer:
                self._db.save_metrics_batch(session_id, self._metrics_buffer)
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

        raw_sample = self._eeg_stream.read_sample()
        metrics = self._metrics_engine.process_sample(raw_sample)

        self._session_manager.add_metric(metrics)
        # Merge raw + computed for full storage
        full_record = {**raw_sample, **metrics}
        self._metrics_buffer.append(full_record)
        self._raw_buffer.append(raw_sample)

        self._audio.update(metrics.get("meditation_score", 0))
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

    def _on_toggle_change(self, metric: str, active: bool) -> None:
        self._live_screen.graph.set_visible(metric, active)

    def _on_test_audio(self) -> None:
        self._audio.test_audio()

    def _on_sinking_alert_toggle(self, active: bool) -> None:
        self._audio.sinking_alert_enabled = active
        logger.info(f"Sinking alert {'enabled' if active else 'disabled'}")

    def _on_disconnect_alert_toggle(self, active: bool) -> None:
        self._audio.disconnect_alert_enabled = active
        logger.info(f"Disconnect alert {'enabled' if active else 'disabled'}")

    def _on_device_mode_toggle(self, use_mock: bool) -> None:
        APP.USE_MOCK_DEVICE = use_mock
        if use_mock:
            self._settings_screen.update_device_status(False, meta="Mode: Mock Data")
        else:
            self._settings_screen.update_device_status(False, meta="Mode: Real Device")
        logger.info(f"Device mode: {'Mock' if use_mock else 'Real'}")

    def _on_session_select(self, session_id: int) -> None:
        session = self._db.get_session(session_id)
        if session:
            self._diary_screen.show_session_detail(session)
            metrics = self._db.get_session_metrics(session_id)
            self._diary_screen.load_metrics_preview(metrics)

    def _on_save_notes(
        self, session_id: int, notes: str, tags: str, mood: int
    ) -> None:
        self._db.update_session_notes(session_id, notes, tags, mood)
        self._refresh_diary()
        logger.info(f"Notes saved for session {session_id}")

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
        self._current_user_id = user_id
        if user_id:
            user = self._db.get_user(user_id)
            name = user["name"] if user else "Unknown"
            logger.info(f"Switched to user: {name} (id={user_id})")
        else:
            logger.info("Switched to: All Users")
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

    def on_stop(self) -> None:
        """Cleanup on app exit."""
        if self._session_manager.state == SessionState.RUNNING:
            self._on_stop()
        self._audio.cleanup()
        self._db.close()
        logger.info("Application closed")
