import unittest

from app.ui.raw_eeg_screen import ScrollableGraphWidget


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



class TestTimerEnableDisplay(unittest.TestCase):
    """Test timer countdown display updates on enable toggle."""

    def test_enable_shows_duration(self):
        from app.ui.timer_screen import TimerScreen
        timer = TimerScreen()
        timer._set_duration(15)
        timer._enable_cb.active = True
        self.assertEqual(timer._countdown_label.text, "15:00")

    def test_disable_shows_dashes(self):
        from app.ui.timer_screen import TimerScreen
        timer = TimerScreen()
        timer._enable_cb.active = True
        timer._enable_cb.active = False
        self.assertEqual(timer._countdown_label.text, "--:--")


class TestAnalyticsStorageInfo(unittest.TestCase):
    """Test analytics screen storage info display."""

    def test_update_storage_info_bytes(self):
        from app.ui.analytics_screen import AnalyticsScreen
        screen = AnalyticsScreen()
        screen.update_storage_info(500, {"sessions": 3, "metrics": 100, "users": 1})
        self.assertIn("500 B", screen._storage_label.text)
        self.assertIn("3 sessions", screen._storage_label.text)

    def test_update_storage_info_kb(self):
        from app.ui.analytics_screen import AnalyticsScreen
        screen = AnalyticsScreen()
        screen.update_storage_info(51200, {"sessions": 10, "metrics": 5000, "users": 2})
        self.assertIn("50.0 KB", screen._storage_label.text)

    def test_update_storage_info_mb(self):
        from app.ui.analytics_screen import AnalyticsScreen
        screen = AnalyticsScreen()
        screen.update_storage_info(5242880, {"sessions": 50, "metrics": 100000, "users": 3})
        self.assertIn("5.0 MB", screen._storage_label.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
