import unittest

from kivy.metrics import dp

from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import ThemedAccordion


class TestScrollableGraphWidget(unittest.TestCase):
    """Test ScrollableGraphWidget data management (no rendering)."""

    def setUp(self):
        self.graph = ScrollableGraphWidget(
            colors={"a": (1, 0, 0, 1), "b": (0, 1, 0, 1)},
            scales={"a": 100.0, "b": 200.0},
            viewport_seconds=10,
        )

    def test_initial_state(self):
        self.assertEqual(self.graph.total_points, 0)
        self.assertEqual(self.graph.max_scroll, 0)

    def test_add_points(self):
        for i in range(5):
            self.graph.add_point({"a": float(i), "b": float(i * 2)})
        self.assertEqual(self.graph.total_points, 5)

    def test_max_scroll_with_enough_data(self):
        vp = self.graph.viewport_points
        for _i in range(vp + 10):
            self.graph.add_point({"a": 1.0, "b": 2.0})
        self.assertEqual(self.graph.max_scroll, 10)

    def test_set_scroll_offset_clamped(self):
        self.graph.set_scroll_offset(999)
        self.assertEqual(self.graph._scroll_offset, 0)

    def test_clear_data(self):
        for _i in range(5):
            self.graph.add_point({"a": 1.0, "b": 2.0})
        self.graph.clear_data()
        self.assertEqual(self.graph.total_points, 0)

    def test_set_visible(self):
        self.graph.set_visible("a", False)
        self.assertFalse(self.graph._visible["a"])
        self.graph.set_visible("a", True)
        self.assertTrue(self.graph._visible["a"])

    def test_load_static_data(self):
        series = {"a": [1.0, 2.0, 3.0, 4.0], "b": [10.0, 20.0, 30.0, 40.0]}
        self.graph.load_static_data(series)
        self.assertEqual(self.graph.total_points, 4)
        self.assertEqual(self.graph._scroll_offset, 0)

    def test_show_flags_default_true(self):
        self.assertTrue(self.graph._show_value_labels)
        self.assertTrue(self.graph._show_timestamps)

    def test_show_flags_disabled(self):
        g = ScrollableGraphWidget(
            colors={"x": (1, 0, 0, 1)}, scales={"x": 100.0},
            show_value_labels=False, show_timestamps=False,
        )
        self.assertFalse(g._show_value_labels)
        self.assertFalse(g._show_timestamps)


class TestGraphTouchScroll(unittest.TestCase):
    """Test horizontal touch-drag scrolling on graph widgets."""

    def setUp(self):
        self.graph = ScrollableGraphWidget(
            colors={"a": (1, 0, 0, 1)},
            scales={"a": 100.0},
            viewport_seconds=10,
        )

    def test_touch_fields_initialized(self):
        self.assertEqual(self.graph._touch_start_x, 0.0)
        self.assertEqual(self.graph._touch_start_offset, 0)

    def test_touch_down_outside_ignored(self):
        from unittest.mock import MagicMock
        touch = MagicMock()
        touch.pos = (-100, -100)
        result = self.graph.on_touch_down(touch)
        self.assertFalse(result)


class TestGraphBipolarAndBatch(unittest.TestCase):
    """Test bipolar mode and batch point adding."""

    def test_bipolar_flag_stored(self):
        g = ScrollableGraphWidget(
            colors={"eeg": (1, 1, 1, 1)}, scales={"eeg": 100.0},
            bipolar=True,
        )
        self.assertTrue(g._bipolar)

    def test_custom_sample_rate_and_max_points(self):
        g = ScrollableGraphWidget(
            colors={"eeg": (1, 1, 1, 1)}, scales={"eeg": 100.0},
            sample_rate=128.0, max_points=7680, viewport_seconds=10,
        )
        self.assertEqual(g._sample_rate, 128.0)
        self.assertEqual(g._viewport_points, 1280)
        self.assertEqual(g._data["eeg"].maxlen, 7680)

    def test_add_points_batch(self):
        g = ScrollableGraphWidget(
            colors={"eeg": (1, 1, 1, 1)}, scales={"eeg": 100.0},
            max_points=1000,
        )
        g.add_points_batch("eeg", [1.0, 2.0, -3.0, 4.0])
        self.assertEqual(g._total_points, 4)
        self.assertEqual(list(g._data["eeg"]), [1.0, 2.0, -3.0, 4.0])

    def test_set_threshold(self):
        g = ScrollableGraphWidget(
            colors={"med": (1, 1, 1, 1)}, scales={"med": 200.0},
        )
        g.set_threshold(100.0, "med")
        self.assertEqual(g._threshold_value, 100.0)
        self.assertEqual(g._threshold_scale_key, "med")

    def test_set_threshold_none_clears(self):
        g = ScrollableGraphWidget(
            colors={"med": (1, 1, 1, 1)}, scales={"med": 200.0},
        )
        g.set_threshold(100.0, "med")
        g.set_threshold(None)
        self.assertIsNone(g._threshold_value)


class TestDiaryScreenUI(unittest.TestCase):
    """Test diary screen UI components."""

    def test_diary_preview_loads_all_graphs(self):
        from app.ui.diary_screen import DiaryScreen
        screen = DiaryScreen()
        rows = [
            {"meditation_score": 50 + i, "shamatha_score": 30 + i,
             "distraction": 20, "sinking": 10,
             "delta_raw": 300, "theta_raw": 200,
             "alpha1_raw": 400, "alpha2_raw": 350,
             "beta1_raw": 100, "beta2_raw": 80,
             "gamma1_raw": 30, "gamma2_raw": 20}
            for i in range(10)
        ]
        screen.load_metrics_preview(rows)
        self.assertEqual(screen._metrics_graph.total_points, 10)
        self.assertEqual(screen._raw_eeg_graph.total_points, 10 * 256)
        self.assertEqual(screen._freq_graph.total_points, 10)

    def test_diary_tab_switching(self):
        from app.ui.diary_screen import DiaryScreen
        screen = DiaryScreen()
        self.assertEqual(screen._active_graph_tab, "metrics")
        screen._switch_graph_tab("raw")
        self.assertEqual(screen._active_graph_tab, "raw")
        screen._switch_graph_tab("freq")
        self.assertEqual(screen._active_graph_tab, "freq")
        screen._switch_graph_tab("metrics")
        self.assertEqual(screen._active_graph_tab, "metrics")

    def test_selected_session_highlight(self):
        from app.ui.diary_screen import DiaryScreen
        from app.ui.theme import C
        screen = DiaryScreen()
        sessions = [
            {"id": 1, "date_time": "2025-01-01", "duration": 60,
             "avg_shamatha": 50},
            {"id": 2, "date_time": "2025-01-02", "duration": 120,
             "avg_shamatha": 60},
        ]
        screen.populate_sessions(sessions)
        btns = [c for c in screen._session_list_layout.children
                if hasattr(c, "session_id")]
        self.assertEqual(len(btns), 2)
        # All start with card background color
        for b in btns:
            self.assertEqual(list(b.bg_color), list(C.BG_CARD))

    def test_set_metrics_threshold(self):
        from app.ui.diary_screen import DiaryScreen
        screen = DiaryScreen()
        screen.set_metrics_threshold(80.0)
        self.assertEqual(screen._metrics_graph._threshold_value, 80.0)



class TestSettingsTimerSoundRow(unittest.TestCase):
    """Custom timer-sound row was moved from the orphan TimerScreen
    into the Settings → Timer accordion. It must round-trip through the
    `timer_sound_path` property and notify the change callback so
    TimerState stays in sync."""

    def setUp(self):
        from app.ui.settings_screen import SettingsScreen
        self.screen = SettingsScreen()

    def test_timer_sound_path_round_trip(self):
        self.screen.timer_sound_path = "/tmp/bell.wav"
        self.assertEqual(self.screen.timer_sound_path, "/tmp/bell.wav")
        self.assertEqual(self.screen._timer_sound_input.text, "/tmp/bell.wav")

    def test_path_change_callback_fires_with_stripped_value(self):
        captured = []
        self.screen.set_timer_sound_change_callback(captured.append)
        self.screen._timer_sound_input.text = "  /tmp/foo.mp3  "
        self.assertEqual(captured, ["/tmp/foo.mp3"])

    def test_test_button_invokes_callback(self):
        called = []
        self.screen.set_test_timer_sound_callback(lambda: called.append(True))
        self.screen._timer_sound_test_btn.dispatch("on_release")
        self.assertEqual(called, [True])

    def test_test_button_toggles_to_stop_then_back(self):
        # Long custom files would otherwise keep playing with no UI control
        # to interrupt them. The Test button doubles as a Stop button.
        played = []
        stopped = []
        self.screen.set_test_timer_sound_callback(lambda: played.append(True))
        self.screen.set_stop_timer_sound_callback(lambda: stopped.append(True))

        self.assertEqual(self.screen._timer_sound_test_btn.text, "Test")
        self.screen._timer_sound_test_btn.dispatch("on_release")
        self.assertEqual(self.screen._timer_sound_test_btn.text, "Stop")
        self.assertEqual(played, [True])
        self.assertEqual(stopped, [])

        # Second tap stops playback and reverts text.
        self.screen._timer_sound_test_btn.dispatch("on_release")
        self.assertEqual(self.screen._timer_sound_test_btn.text, "Test")
        self.assertEqual(stopped, [True])
        self.assertEqual(played, [True])  # unchanged

    def test_natural_playback_end_resets_button_text(self):
        self.screen.set_test_timer_sound_callback(lambda: None)
        self.screen._timer_sound_test_btn.dispatch("on_release")
        self.assertEqual(self.screen._timer_sound_test_btn.text, "Stop")
        # Sound.on_stop fires → app_manager calls notify_timer_sound_test_ended.
        self.screen.notify_timer_sound_test_ended()
        self.assertEqual(self.screen._timer_sound_test_btn.text, "Test")
        self.assertFalse(self.screen._timer_sound_test_playing)


class TestAccordionGrandchildGrowth(unittest.TestCase):
    """Regression: when content height grows AFTER the section was first
    opened (e.g. populate_bt_devices appending rows after the user opened
    the Device accordion), _scroll.height must track the new minimum_height.
    Without the bind, _scroll.height stayed at the initial snapshot and the
    ScrollView clipped all but the first row on Android."""

    def test_scroll_tracks_content_minimum_height_after_open(self):
        acc = ThemedAccordion()
        section = acc.add_section("Device", collapsed=False)

        # Simulate the snapshot taken when the section was opened with a
        # near-empty content (e.g. only a Scan button, ~36dp).
        section._content.minimum_height = dp(40)
        baseline = section._scroll.height

        # Now grandchildren get appended — _content.minimum_height grows.
        # The fix binds this directly to _update_height so _scroll.height
        # follows. Without the fix, _scroll.height stays at `baseline`.
        section._content.minimum_height = dp(220)

        self.assertGreater(
            section._scroll.height, baseline,
            "section _scroll.height did not track _content.minimum_height "
            "growth — accordion will clip newly added rows.",
        )
        self.assertEqual(section._scroll.height, dp(220))

    def test_collapsed_section_keeps_scroll_at_zero(self):
        # Collapsed sections must stay at 0 height regardless of content
        # changes (otherwise collapsed sections would expand silently).
        acc = ThemedAccordion()
        section = acc.add_section("Device", collapsed=True)
        section._content.minimum_height = dp(220)
        self.assertEqual(section._scroll.height, 0)

    def test_open_method_expands_section(self):
        acc = ThemedAccordion()
        s1 = acc.add_section("A", collapsed=False)
        s2 = acc.add_section("B", collapsed=True)
        # Opening B must collapse A (only one section open at a time).
        s2.open()
        self.assertFalse(s2._collapsed)
        self.assertTrue(s1._collapsed)


class TestSettingsDevicePicker(unittest.TestCase):
    """Multi-device routing surface on SettingsScreen."""

    def setUp(self):
        from app.ui.settings_screen import SettingsScreen
        self.screen = SettingsScreen()

    def test_focus_device_section_shows_banner_and_opens_section(self):
        # Device section starts collapsed. focus_device_section should open it
        # and set the banner text + non-zero height.
        self.assertTrue(self.screen._device_section._collapsed)
        self.screen.focus_device_section("Pick one of 3 devices")
        self.assertFalse(self.screen._device_section._collapsed)
        self.assertEqual(
            self.screen._device_picker_banner.text, "Pick one of 3 devices",
        )
        self.assertGreater(self.screen._device_picker_banner.height, 0)

    def test_update_device_status_connected_clears_banner(self):
        self.screen.focus_device_section("Pick one")
        self.assertGreater(self.screen._device_picker_banner.height, 0)
        # Once a device is connected, the prompt must disappear.
        self.screen.update_device_status(True, name="MindWave A")
        self.assertEqual(self.screen._device_picker_banner.text, "")
        self.assertEqual(self.screen._device_picker_banner.height, 0)


class TestFilterMindwave(unittest.TestCase):
    """Static helper used by both auto-scan and start-session paths."""

    def test_filter_mindwave_picks_only_matching_names(self):
        from app.ui.app_manager import EEGMeditationApp
        devices = [
            {"name": "Bose QC35", "address": "AA:00"},
            {"name": "MindWave Mobile 2", "address": "AA:01"},
            {"name": "neurosky_42", "address": "AA:02"},
            {"name": "Apple Watch", "address": "AA:03"},
            {"name": "MINDWAVE", "address": "AA:04"},
        ]
        out = EEGMeditationApp._filter_mindwave(devices)
        self.assertEqual([d["address"] for d in out], ["AA:01", "AA:02", "AA:04"])

    def test_filter_mindwave_handles_missing_name(self):
        from app.ui.app_manager import EEGMeditationApp
        out = EEGMeditationApp._filter_mindwave([
            {"address": "AA:01"},                  # no 'name' key
            {"name": None, "address": "AA:02"},    # None name
            {"name": "", "address": "AA:03"},      # empty name
        ])
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
