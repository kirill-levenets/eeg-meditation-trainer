import os
import sqlite3

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import ScreenManager, SlideTransition

from app import android_jni
from app.audio_feedback.noise import AudioEngine
from app.config import APP
from app.crash_handler import (
    flush_pre_app_errors,
    install_crash_handler,
    report_soft_error,
)
from app.eeg.neurosky_stream import NeuroSkyStream
from app.logger import logger
from app.metrics.formula_slots import (
    FORMULA_KEYS,
    FormulaSlots,
)
from app.session.manager import SessionState
from app.session.running_session import RunningSession
from app.session.session_program import (
    PROGRAM_FORMULA_KEYS,
)
from app.settings.registry import (
    BOOL,
    INT,
    STR,
    Setting,
    held,
    kept,
)
from app.storage.database import DatabaseManager
from app.ui import render_stats
from app.ui.app_context import AppContext, SessionAccess
from app.ui.audio_metric import AudioMetric
from app.ui.backup_flow import BackupFlow
from app.ui.diary_screen import DiaryScreen
from app.ui.formula_settings import FormulaSettings
from app.ui.graph_fullscreen import GraphFullscreen
from app.ui.graph_series import FIRST_RUN_LIVE_SERIES, GraphSeries
from app.ui.graph_set import GraphSet
from app.ui.headset import Headset
from app.ui.history_flow import HistoryFlow
from app.ui.history_screen import HistoryScreen
from app.ui.hooks import wire
from app.ui.live_session import LiveSessionScreen
from app.ui.navigation import Navigation, ScreenHooks
from app.ui.power_exemption import PowerExemption
from app.ui.profiles import ProfileGate, Profiles
from app.ui.program_settings import ProgramSettings
from app.ui.session_controls import SessionControls
from app.ui.session_detail_flow import SessionDetailFlow
from app.ui.session_settings import SessionSettings
from app.ui.settings_screen import (
    SettingsScreen,
)
from app.ui.shown_session import ShownSession
from app.ui.sound_sources import SoundSources
from app.ui.startup import (
    line_colours_setting,
    resolve_startup_user,
    startup_text_size,
    startup_theme,
    text_size_setting,
    theme_seed,
    theme_setting,
)
from app.ui.theme import C, F, fill_background
from app.ui.toast import android_toast, show_toast
from app.ui.user_settings import UserSettings
from app.ui.widgets.bottom_nav import BottomNav
from app.ui.widgets.loading_overlay import LoadingOverlay
from app.ui.widgets.popups import confirm_popup, make_message_popup
from app.ui.widgets.styled_button import StyledButton


class EEGMeditationApp(App):
    """Main Kivy application for EEG Meditation Trainer."""

    title = APP.APP_NAME
    icon = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "assets", "icons", "icon_128.png",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._real_stream: NeuroSkyStream = NeuroSkyStream()
        self._db: DatabaseManager = DatabaseManager()
        self._audio: AudioEngine = AudioEngine()
        self._current_user_id: int | None = None
        self._user_settings = UserSettings(self._db, user_id=lambda: self._current_user_id)
        self._formulas: FormulaSlots = FormulaSlots()
        self.serial_device_override: str | None = None

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

        float_root = self._build_screens()
        self._build_flows()
        self._bind_callbacks()
        # After _bind_callbacks (it sets the fields get() snapshots as defaults), before any user load.
        self._register_settings()
        resolved_user = self._restore_last_user()
        self._profiles.refresh()
        # The gate is on a resolved user, not on users existing: a reinstall, a restored DB, a deleted active profile or
        # a corrupt last_user_id leave users but none current. The nav is disabled at once: no cold-start tap window.
        if resolved_user is None:
            self._gate.open(0.5)
        return float_root

    def _build_screens(self) -> FloatLayout:
        """The four screens under the bottom nav, with the app-wide overlays (loading, a fullscreen graph) above them."""
        root = BoxLayout(orientation="vertical")
        fill_background(root, C.BG_DARK)
        self._sm = ScreenManager(transition=SlideTransition())
        self._live_screen = LiveSessionScreen()
        self._settings_screen = SettingsScreen()
        self._history_screen = HistoryScreen()
        self._diary_screen = DiaryScreen()
        for screen in (self._live_screen, self._history_screen, self._settings_screen, self._diary_screen):
            self._sm.add_widget(screen)
        root.add_widget(self._sm)
        self._bottom_nav = BottomNav(tabs=[(label, key) for label, key, _screen in Navigation.TABS],
                                     callback=lambda key: self._nav.on_tab(key))
        root.add_widget(self._bottom_nav)
        float_root = FloatLayout()
        self._float_root = float_root
        self._fullscreen = GraphFullscreen(float_root)
        self._loading_overlay = LoadingOverlay()
        float_root.add_widget(root)
        float_root.add_widget(self._loading_overlay)
        return float_root

    def _build_flows(self) -> None:
        """The objects that own each concern, each given the app context and the screens it works on."""
        self._headset = Headset(self._ctx, self._real_stream, self._settings_screen.device, self._live_screen.header,
                                serial_override=lambda: self.serial_device_override)
        self._headset.load_aliases()
        self._session = RunningSession(self._ctx, self._audio, self._headset, on_event=lambda event: self._controls.on_event(event))
        self._sounds = SoundSources(self._ctx, self._audio, self._settings_screen.audio, self._settings_screen.timer)
        self._audio_metric = AudioMetric(self._ctx, self._session.program_run, self._settings_screen.metric)
        self._program_settings = ProgramSettings(
            self._ctx, self._settings_screen.timer, self._live_screen,
            show_saved_series=lambda uid: self._graph_series.apply_saved(self._live_screen.graph, uid))
        self._session_settings = SessionSettings(self._ctx, self._settings_screen, self._program_settings, self._formulas)
        self._formula_settings = FormulaSettings(self._ctx, self._settings_screen.formulas, self._live_screen.graph,
                                                 self._formulas, scoring_locked=self._audio_metric.formula_scoring_locked)
        self._power = PowerExemption(self._ctx, self._settings_screen.device)
        self._graphs = GraphSet(self._live_screen, self._diary_screen, self._settings_screen.display)
        self._graph_series = GraphSeries(self._ctx, self._live_screen.graph, self._formulas, self._formula_settings,
                                         graphs=self._graphs.all)
        self._history = HistoryFlow(self._ctx, self._history_screen, self._formulas, self._loading_overlay,
                                    on_sessions_deleted=lambda ids: self._shown.on_sessions_deleted(ids))
        self._shown = ShownSession(self._ctx, self._live_screen, self._audio, self._history, self._session)
        self._controls = SessionControls(self._ctx, self._session, self._shown, self._session_settings, self._headset,
                                         self._sounds)
        self._detail = SessionDetailFlow(self._ctx, self._diary_screen, self._history_screen, self._sm,
                                         self._graph_series)
        self._gate = ProfileGate(
            self._ctx, self._bottom_nav, refresh_profiles=lambda: self._profiles.refresh(),
            scan_for_new_profile=self._headset.scan_for_new_profile, offer_power_exemption=self._power.offer_once)
        self._profiles = Profiles(self._ctx, self._settings_screen.profile, self._gate, deactivate=self._deactivate_user,
                                  on_deleted=self._on_profile_deleted)
        self._backup_flow = BackupFlow(self._ctx, self._settings_screen.backup, user_name=self._profiles.current_name,
                                       checkpoint=self._session.checkpoint_or_report,
                                       on_db_replaced=self._on_db_replaced)
        # Entering History reloads a stale list; the Session screen's duration picker shows a Timer change.
        self._nav = Navigation(self._ctx, self._sm, self._bottom_nav, gate=self._gate, fullscreen=self._fullscreen,
                               screens={"history": ScreenHooks(entering=self._history.refresh,
                                                                # resumed on another day: the chart and totals move on
                                                                resumed=self._history_screen.on_pre_enter),
                                        "live_session": ScreenHooks(entering=self._program_settings.sync_picker),
                                        "diary": ScreenHooks(back=self._detail.on_diary_back)})

    def _make_context(self) -> AppContext:
        """What every flow reaches the app through; the callables read the app when called, so they see the profile and
        the session as they are then."""
        session = SessionAccess(live=lambda: self._session.live(), running_id=lambda: self._session.running_id(),
                                refused=lambda doing, why="": self._controls.refused(doing, why), discard=lambda: self._controls.discard(),
                                set_formula=lambda idx, name, formula: self._session.set_formula(idx, name, formula))
        return AppContext(db=self._db, user_id=lambda: self._current_user_id, activate_user=self._activate_user,
                          require_user=self._require_user, on_main=self._on_main,
                          switch_screen=lambda name: self._nav.switch(name),
                          info=self._info_popup, toast=self._toast, confirm=self._confirm_action,
                          setting=lambda key: self._user_settings.value(key),
                          change_setting=lambda key, value: self._user_settings.change(key, value),
                          setting_changed=lambda key: self._user_settings.changed(key),
                          after_settle=lambda name, fn: self._user_settings.after_settle(name, fn),
                          save_settings=self._save_user_settings, session=session)

    def _bind_callbacks(self) -> None:
        """Every screen's handlers, and the keys: the marker hotkey and Android's back button."""
        self._wire_session_screen()
        self._wire_settings_screen()
        self._wire_history_screens()
        Window.bind(on_key_down=self._on_key_down)
        Window.bind(on_keyboard=self._nav.on_keyboard)

    def _wire_session_screen(self) -> None:
        """The Session screen's controls, its end card, its graphs' glyphs and the series its graph starts with."""
        self._live_screen.btn_start.bind(on_release=lambda _b: self._controls.start())
        self._live_screen.btn_pause.bind(on_release=lambda _b: self._controls.toggle_pause())
        self._live_screen.btn_stop.bind(on_release=lambda _b: self._controls.stop())
        self._live_screen.btn_marker.bind(on_release=lambda _b: self._controls.mark())
        wire(
            self._live_screen.duration,
            on_preset=self._program_settings.on_duration_preset,
            on_program_pick=self._program_settings.on_load,
        )
        self._live_screen.connect_overlay.cancel_btn.bind(on_release=lambda _b: self._controls.cancel())
        self._live_screen.connect_overlay.retry_btn.bind(on_release=lambda _b: self._controls.retry())
        self._live_screen.end_card.ok_btn.bind(on_release=self._shown.on_ok)
        self._live_screen.end_card.save_notes_btn.bind(on_release=self._shown.on_save_notes)
        self._live_screen.end_card.delete_btn.bind(on_release=self._shown.on_delete)

        # Tap on graph to set marker (Android — no keyboard available)
        if android_jni.on_android():
            wire(self._live_screen.graph, on_tap=lambda *_a: self._controls.mark())
        wire(self._live_screen, on_lines_shown=self._session.set_shown)
        wire(self._live_screen.stats, on_mode=lambda _mode: self._user_settings.changed("stats_view_mode"))

        # Shared fullscreen-expand + series-picker glyphs on every graph
        self._graphs.wire_glyphs(self._fullscreen.present, self._graph_series.present_picker)
        # The formula series stay hidden until a formula is shown through the picker, the program ones while no program
        # with formula segments runs; a new profile starts on Shamatha alone (a profile load applies its own).
        for key in (*FORMULA_KEYS, *PROGRAM_FORMULA_KEYS):
            self._live_screen.graph.set_visible(key, False)
        for key, active in FIRST_RUN_LIVE_SERIES.items():
            self._live_screen.graph.set_visible(key, active)

    def _wire_settings_screen(self) -> None:
        """Settings' own folds: the profile, the backup, the threshold and the sound's metric, the theme."""
        ss = self._settings_screen
        wire(ss.profile, on_switch=self._profiles.on_switch, on_create=self._profiles.on_create,
             on_delete=self._profiles.on_delete, session_counter=self._profiles.count_sessions)
        wire(ss.backup, on_backup=self._backup_flow.on_backup_pressed, on_restore=self._backup_flow.on_restore_pressed)
        wire(ss.threshold, on_change=self._controls.on_threshold_slider)
        wire(ss.metric, on_metric_change=self._audio_metric.on_change,
             on_formula_index=self._audio_metric.on_formula_index)
        wire(ss.theme, on_change=lambda _name: self._user_settings.changed("theme"))  # the selector applied it to C
        self._wire_settings_sections()

    def _wire_settings_sections(self) -> None:
        """The folds the app's parts own: sounds, the headset, the display, formulas and the timer."""
        ss = self._settings_screen
        wire(ss.audio, on_test_audio=self._sounds.on_test_audio,
             on_alert_toggle=lambda key, on: self._user_settings.change(key, on),
             on_feedback_source_change=self._sounds.on_feedback_source_change,
             on_reward_source_change=self._sounds.on_reward_source_change)
        wire(ss.device, on_device_mode_toggle=self._headset.on_mode_toggle, on_scan_devices=self._headset.on_scan,
             on_device_select=self._headset.on_select, device_state=self._headset.state,
             on_device_rename=self._headset.on_rename, on_copy_diagnostics=self._headset.on_copy_diagnostics,
             on_battery_settings=self._power.on_battery_settings, on_maker_settings=self._power.on_maker_settings)
        wire(ss.display, on_text_size=lambda _size: self._user_settings.changed("text_size"),
             on_line_colours=lambda _name: self._user_settings.changed("line_colours"),
             on_line_width_change=lambda width: self._user_settings.change("line_width", width),
             on_rotate_screen=lambda rotation: self._user_settings.change("rotation", rotation))
        wire(ss.formulas, on_formula_slot_change=self._formula_settings.on_slot_change,
             on_save_formula=self._formula_settings.on_save, on_load_formula=self._formula_settings.on_load,
             on_delete_formula=self._formula_settings.on_delete, on_export_formulas=self._formula_settings.on_export)
        wire(ss.timer, on_program_mode=self._program_settings.on_mode_change,
             on_program_changed=self._program_settings.on_changed, on_program_save=self._program_settings.on_save,
             on_program_load=self._program_settings.on_load, on_program_delete=self._program_settings.on_delete,
             on_test_timer_sound=self._sounds.on_test_timer_sound,
             on_stop_timer_sound=self._sounds.on_stop_test_timer_sound,
             on_timer_sound_change=self._sounds.on_timer_sound_change)

    def _wire_history_screens(self) -> None:
        """History's list and chart, and a session's detail."""
        wire(
            self._diary_screen,
            on_save_notes=self._history.save_notes,
            on_export_csv=self._history.on_export_csv,
            on_back=self._detail.on_diary_back,
            on_band_view_change=self._detail.persist_band_view,
            on_band_collapse=lambda _collapsed: self._user_settings.changed("band_power_collapsed"),
        )

        wire(
            self._history_screen,
            on_delete_sessions=self._history.delete_sessions,
            on_export_sessions=self._history.on_export_sessions_csv,
            on_chart_collapse=lambda _collapsed: self._user_settings.changed("history_chart_collapsed"),
        )
        wire(self._history_screen.session_list, on_open=self._detail.on_session_select,
             on_rename=self._history.on_rename_session)
        wire(self._history_screen.chart_area, on_view_mode_change=self._history.on_view_mode_change)
        wire(self._diary_screen.what_if, on_collapse=lambda _collapsed: self._user_settings.changed("what_if_collapsed"))

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

    def _restore_last_user(self) -> int | None:
        """Restore the last selected user; return the resolved uid, or None when
        the app must prompt (no/stale/corrupt last_user_id). build() opens the
        blocking user gate on None — the app is never left usable with no user."""
        uid = resolve_startup_user(self._db)
        if uid is None:
            return None
        self._activate_user(uid)
        logger.info(f"Restored last user id={uid}")
        return uid

    def _on_main(self, fn) -> None:
        """Queue callable on Kivy's main thread.

        Thread-safe per Kivy docs.  During Kivy pause (screen locked) the
        call is buffered and executed when the app resumes.
        """
        Clock.schedule_once(lambda dt: fn(), 0)

    # ------------------------------------------------------------------

    def _flush_on_leave(self) -> None:
        """Persist what the user changed but hasn't saved, before the app pauses or exits."""
        self._leaving = True
        try:
            if getattr(self, "_shown", None) is not None:
                self._shown.flush_notes()
            self._session.checkpoint_or_report()  # Android may kill a backgrounded app before the next 60 s checkpoint
            # Only on screen: leaving it already saved (or reported a failed save), and a retry on every pause
            # repeated the error, e.g. for a session deleted since.
            if getattr(self, "_diary_screen", None) is not None and self._sm.current == self._diary_screen.name:
                self._diary_screen.flush_notes()
            self._save_user_settings()
        finally:
            self._leaving = False

    def _on_key_down(self, _window, key, _scancode, codepoint, _modifiers) -> bool:
        """The marker hotkey places a marker; any other key goes on to Kivy."""
        if not self._settings_screen.display.is_marker_key(key, codepoint):
            return False
        self._controls.mark()
        return True

    _leaving = False  # set while _flush_on_leave runs: nothing the app draws is seen any more

    def _toast(self, message: str) -> None:
        """A short confirmation above any popup; while the app is leaving, Android's own toast, the one thing still
        seen then."""
        if self._leaving and android_jni.on_android():
            android_toast(message)
        else:
            show_toast(message)

    def _require_user(self, action: str) -> int | None:
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

    def _confirm_action(self, title, message, ok_text, on_ok, ok_color=None, on_cancel=None):
        """on_cancel runs on every close that isn't OK: Cancel, a tap outside, or Android back. Returns the popup."""
        return confirm_popup(title, message, ok_text, on_ok, ok_color=ok_color, on_cancel=on_cancel)

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

    def _register_settings(self) -> None:
        """Every per-user setting, each defined by what holds it; once in build() before any user load, as a kept
        setting's default is its holder's value now. A profile load applies them in this order."""
        ss = self._settings_screen

        def set_threshold(v):
            ss.threshold.value = v
            self._controls.apply_threshold(v)

        self._user_settings.register([
            *self._program_settings.settings(), *self._alert_settings(), *self._fold_settings(),
            kept("threshold", INT, lambda: ss.threshold.value, set_threshold, settle=True),
            *self._headset.settings(), *self._audio_metric.settings(), *self._sounds.settings(),
            *self._history.settings(), *self._graphs.settings(), *self._display_settings()])

    def _alert_settings(self) -> list[Setting]:
        """Settings › Audio's alert toggles, each held by the profile's settings: its apply turns the engine's alert
        (`<key>_enabled`) and its checkbox."""
        boxes, engine = self._settings_screen.audio.alerts, self._audio

        def alert(key: str) -> Setting:
            switch = f"{key}_enabled"
            if not hasattr(type(engine), switch):  # a set would make a new attribute: the toggle would reach nothing
                raise AttributeError(f"AudioEngine has no {switch}: each alert in settings_sections/audio.py ALERTS needs one")

            def apply(v):
                setattr(engine, switch, v)
                boxes[key].active = v
            return held(key, BOOL, boxes[key].active, apply)

        return [alert(key) for key in boxes]

    def _fold_settings(self) -> list[Setting]:
        """What each screen keeps folded: History's chart, a session detail's What-if and band power."""
        hs, ds = self._history_screen, self._diary_screen
        return [kept("history_chart_collapsed", BOOL, lambda: hs.chart_collapsed, hs.set_chart_collapsed),
                kept("what_if_collapsed", BOOL, lambda: ds.what_if.collapsed, ds.what_if.set_collapsed),
                kept("band_power_collapsed", BOOL, lambda: ds.band_collapsed, ds.set_band_collapsed)]

    def _display_settings(self) -> list[Setting]:
        display, ls = self._settings_screen.display, self._live_screen

        def apply_rotation(v):
            display._current_rotation = v
            display._rotate_btn.text = f"Rotate Screen ({v}°)"
            Window.rotation = v

        return [held("rotation", INT, display._current_rotation, apply_rotation),
                kept("marker_hotkey", STR, lambda: display.marker_hotkey,
                     lambda v: setattr(self._settings_screen, "marker_hotkey", v)),
                kept("stats_view_mode", STR, lambda: ls.stats.mode, ls.stats.set_mode),
                # Its default is the seed, not the startup profile's theme the UI was built in.
                theme_setting(self._theme_seed), text_size_setting(), line_colours_setting()]

    def _save_user_settings(self) -> None:
        """Persist current UI settings for the active user."""
        uid = self._current_user_id
        if not uid:
            return  # silent-ok: batch persistence; no active user = nothing to save
        try:
            self._user_settings.save(uid)  # all scalar per-user settings + theme
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
        with self._user_settings.loading():  # the values it applies are not persisted back
            self._load_user_settings_inner(user_id)

    def _load_user_settings_inner(self, user_id: int) -> None:
        # Always applies a value (default if absent), so no user inherits the previous user's settings.
        self._user_settings.load(user_id)

        # Load formulas BEFORE GraphSeries.restore so the per-slot validity gate
        # sees real is_valid; the picker selection (graph_series_*) decides visibility.
        self._formula_settings.load(user_id)
        self._program_settings.load(user_id)  # its saved-programs list goes to both UIs at the end (refresh_saved)

        self._graph_series.restore(user_id)

        self._headset.load(user_id)  # after store.load, which applies use_mock

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
        session's runner and the foreground service even while the UI is paused.
        Per Kivy docs returning False here would *stop* the app, not prevent
        the pause — so we always return True.

        Also sets the session's `ui_paused` so its runner skips per-tick UI work
        (graph add_point, stats updates). Otherwise N minutes of locked
        screen accumulates ~120·N Clock callbacks, each redrawing the
        whole graph; on resume they all fire in a burst and the render
        loop chokes (black-screen / app freeze).
        """
        self._session.ui_paused = True
        logger.info("on_pause fired: the screen is locked")
        # Skip the flush during a restore's relaunch window (mirrors on_stop):
        # the DB was just replaced with the imported file, so writing the old
        # in-memory state back would clobber the freshly-restored data.
        if not getattr(self, "_restoring", False):
            self._flush_on_leave()
        return True

    def on_resume(self) -> None:
        """Android lifecycle: app foreground after a pause (screen unlock).

        The session's runner skipped per-tick UI updates while paused, so the
        graph and stats labels are stale. Drop the pause flag and force
        a single UI refresh from current session state. Anything queued
        through `_on_main` during the pause (e.g. timer-expiry finish,
        BT alerts) drains on its own from Kivy's Clock.
        """
        self._session.ui_paused = False
        logger.info("on_resume fired: the screen shows again")
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
        """The first frame after a resume: the screen shown, then a running session's graphs and readout."""
        self._nav.resumed()
        self._shown.resumed()

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
            if self._session.manager.state in (SessionState.RUNNING, SessionState.PAUSED):
                # Skipped while _restoring: the DB is already shut down, so the
                # save would silently no-op into the null connection. (The restore
                # entry points refuse to run while a session is active, so this is
                # defense-in-depth, not a data-loss path.)
                self._session.stop("user", saved=True)  # saved before the app's database closes
        # A session's ending tears down on the main thread, which is closing the app: what it held is released here,
        # and so is a start still connecting, which has no session to end.
        self._session.keep_awake.release()
        self._audio.cleanup()
        self._db.mark_shutting_down()
        self._db.close()
        logger.info("Application closed")
