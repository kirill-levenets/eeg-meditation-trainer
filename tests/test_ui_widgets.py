import unittest

from kivy.metrics import dp

from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import ThemedAccordion


class _FakeTouch:
    """Minimal touch stand-in for on_touch_down hit-testing.

    sx/sy are normalized window coords; for a parentless widget at the window
    origin, window space == widget space, so they mirror x/y.
    """

    def __init__(self, x, y, button=None):
        from kivy.core.window import Window
        self.pos = (x, y)
        self.x = x
        self.y = y
        self.sx = x / Window.width
        self.sy = y / Window.height
        self.uid = id(self)
        self.ud = {}
        self.grabbed = False
        self.grab_current = None
        if button is not None:
            self.button = button

    def grab(self, w):
        self.grabbed = True

    def ungrab(self, w):
        self.grabbed = False

    # no-ops so a touch can pass through ScrollView's transform machinery
    def push(self, *a):
        pass

    def pop(self, *a):
        pass

    def apply_transform_2d(self, *a):
        pass


class TestGraphExpandAffordance(unittest.TestCase):
    """Expand-to-fullscreen affordance on the shared graph widget."""

    def _make_graph(self):
        g = ScrollableGraphWidget(
            colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0}, viewport_seconds=10,
        )
        g.pos = (0, 0)
        g.size = (400, 300)
        return g

    def test_no_icon_without_callback(self):
        g = self._make_graph()
        self.assertIsNone(g._expand_icon_rect())

    def test_icon_rect_present_with_callback(self):
        g = self._make_graph()
        g.set_expand_callback(lambda src: None)
        rect = g._expand_icon_rect()
        self.assertIsNotNone(rect)
        x, y, w, h = rect
        # top-right, inside widget bounds
        self.assertGreater(x, g.x + g.width / 2)
        self.assertGreater(y, g.y + g.height / 2)
        self.assertLessEqual(x + w, g.x + g.width)
        self.assertLessEqual(y + h, g.y + g.height)

    def test_icon_hidden_when_too_small(self):
        g = self._make_graph()
        g.set_expand_callback(lambda src: None)
        g.size = (30, 30)
        self.assertIsNone(g._expand_icon_rect())

    def test_point_in_rect(self):
        from app.ui.touch_utils import point_in_rect
        self.assertFalse(point_in_rect(0, 0, None))
        self.assertTrue(point_in_rect(5, 5, (0, 0, 10, 10)))
        self.assertFalse(point_in_rect(20, 5, (0, 0, 10, 10)))

    def test_tap_on_icon_fires_callback_without_grab(self):
        g = self._make_graph()
        fired = []
        g.set_expand_callback(lambda src: fired.append(src))
        x, y, w, h = g._expand_icon_rect()
        touch = _FakeTouch(x + w / 2, y + h / 2)
        result = g.on_touch_down(touch)
        self.assertTrue(result)
        self.assertEqual(fired, [g])
        self.assertFalse(touch.grabbed)  # expand must not start a scroll/drag

    def test_tap_off_icon_does_not_fire_callback(self):
        g = self._make_graph()
        fired = []
        g.set_expand_callback(lambda src: fired.append(src))
        touch = _FakeTouch(g.x + 20, g.y + 20)  # bottom-left, away from icon
        g.on_touch_down(touch)
        self.assertEqual(fired, [])
        self.assertTrue(touch.grabbed)  # normal grab path

    def test_no_callback_normal_grab(self):
        g = self._make_graph()
        touch = _FakeTouch(g.x + g.width / 2, g.y + g.height / 2)
        result = g.on_touch_down(touch)
        self.assertTrue(result)
        self.assertTrue(touch.grabbed)


class TestGraphAwareScrollViewGuard(unittest.TestCase):
    """A graph whose logical bounds overflow the viewport must not steal touches
    aimed at widgets sitting outside the ScrollView (e.g. the Metrics/Raw toggle)."""

    def _make(self, viewport_h):
        from app.ui.raw_eeg_screen import GraphAwareScrollView
        sv = GraphAwareScrollView()
        sv.pos = (0, 0)
        sv.size = (400, viewport_h)
        g = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0})
        g.pos = (0, 0)
        g.size = (400, 600)  # graph logical bounds always 600 tall
        sv.add_widget(g)
        return sv, g

    def test_touch_above_viewport_not_stolen(self):
        sv, g = self._make(viewport_h=200)
        touch = _FakeTouch(200, 300)  # outside viewport (y>200) but inside graph (y<600)
        self.assertIs(sv._graph_under_touch(touch), g)  # graph bounds DO cover it
        sv.on_touch_down(touch)
        self.assertEqual(len(g._grabbed_touches), 0)  # ...but the guard stops the graph grabbing it

    def test_touch_inside_viewport_reaches_graph(self):
        sv, g = self._make(viewport_h=600)
        touch = _FakeTouch(200, 300)  # inside both
        sv.on_touch_down(touch)
        self.assertEqual(len(g._grabbed_touches), 1)  # graph received and grabbed it


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



class TestCenteredTextInput(unittest.TestCase):
    """Text is centered horizontally (halign) and vertically (symmetric padding)."""

    def test_centered_alignment(self):
        from app.ui.theme import CenteredTextInput
        ti = CenteredTextInput(size_hint=(None, None), size=(120, 40))
        ti._recenter()
        self.assertEqual(ti.halign, "center")          # horizontal
        pad = ti.padding
        self.assertEqual(pad[1], pad[3])               # vertical: top == bottom
        self.assertGreaterEqual(pad[1], 0)


class TestLegendBarActiveMarker(unittest.TestCase):
    """The 'training now' series is bolded with a marker; others are plain."""

    def test_active_item_is_bold_and_marked(self):
        from app.ui.widgets.legend import LegendBar
        bar = LegendBar()
        bar.set_items(
            [("Shamatha", (1, 1, 1, 1)), ("NS Meditation", (0, 1, 0, 1))],
            active_text="NS Meditation",
        )
        labels = {c.text: c.bold for c in bar.children}
        self.assertIn("» NS Meditation", labels)
        self.assertTrue(labels["» NS Meditation"])      # active is bold
        self.assertIn("Shamatha", labels)
        self.assertFalse(labels["Shamatha"])            # inactive is plain
        # No active_text -> nothing marked.
        bar.set_items([("Shamatha", (1, 1, 1, 1))])
        self.assertEqual([c.text for c in bar.children], ["Shamatha"])


class TestScrollableGraphSetSeriesName(unittest.TestCase):
    """set_series_name updates the label and fires the visibility callback."""

    def test_set_series_name_updates_label_and_fires_callback(self):
        fired = []
        g = ScrollableGraphWidget(
            colors={"custom_formula": (1, 0, 0, 1)},
            scales={"custom_formula": 200.0},
        )
        g.set_visibility_callback(lambda: fired.append(True))
        g.set_series_name("custom_formula", "Alpha Ratio")
        self.assertEqual(g.series_name("custom_formula"), "Alpha Ratio")
        self.assertTrue(fired)


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


class TestSettingsFormulaSlots(unittest.TestCase):
    """Settings exposes three named formula slots, each with its own
    name input, formula input, and status label."""

    def setUp(self):
        from app.ui.settings_screen import SettingsScreen
        self.screen = SettingsScreen()

    def test_settings_has_three_formula_slots(self):
        self.assertEqual(len(self.screen._formula_inputs), 3)
        self.assertEqual(len(self.screen._formula_name_inputs), 3)
        self.assertEqual(len(self.screen._formula_statuses), 3)

    def test_submit_slot_fires_callback_with_index_name_formula(self):
        captured = []
        self.screen.set_formula_slot_callback(
            lambda idx, name, formula: captured.append((idx, name, formula))
        )
        self.screen._formula_name_inputs[1].text = "  Focus  "
        self.screen._formula_inputs[1].text = "  alpha + beta  "
        self.screen._submit_slot(1)
        self.assertEqual(captured, [(1, "Focus", "alpha + beta")])

    def test_save_slot_reuses_library_callback_with_index_name_formula(self):
        captured = []
        self.screen.set_save_formula_callback(
            lambda idx, name, formula: captured.append((idx, name, formula))
        )
        self.screen._formula_name_inputs[2].text = "Calm"
        self.screen._formula_inputs[2].text = "theta / (delta + 1)"
        self.screen._save_slot(2)
        self.assertEqual(captured, [(2, "Calm", "theta / (delta + 1)")])

    def test_set_formula_slot_reflects_into_inputs(self):
        self.screen.set_formula_slot(0, "MyName", "alpha")
        self.assertEqual(self.screen._formula_name_inputs[0].text, "MyName")
        self.assertEqual(self.screen._formula_inputs[0].text, "alpha")

    def test_set_formula_slot_status_routes_to_the_right_slot(self):
        from app.ui.theme import C
        self.screen.set_formula_slot_status(1, "boom", is_error=True)
        self.assertEqual(self.screen._formula_statuses[1].text, "boom")
        self.assertEqual(tuple(self.screen._formula_statuses[1].color), tuple(C.DANGER))
        self.assertEqual(self.screen._formula_statuses[0].text, "")  # slot 0 untouched


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

    def test_collapsed_section_detaches_content_from_touch_layer(self):
        # A collapsed section must remove its content from the ScrollView so the
        # display-clipped content can't overlap sections below it in the touch
        # layer and steal taps. Regression: the collapsed User Profile picker
        # intercepted clicks aimed at the Threshold header (nested-ScrollView
        # simulated click landed inside a hidden row's rect -> grabbed the tap).
        from kivy.uix.label import Label
        acc = ThemedAccordion()
        section = acc.add_section("A", collapsed=False)
        section.add_widget(Label())
        self.assertIs(section._content.parent, section._scroll)
        section._set_collapsed(True)
        self.assertIsNone(section._content.parent)            # detached when collapsed
        section._set_collapsed(False)
        self.assertIs(section._content.parent, section._scroll)  # re-attached on expand

    def test_section_collapsed_at_construction_detaches_content(self):
        acc = ThemedAccordion()
        section = acc.add_section("A", collapsed=True)
        self.assertIsNone(section._content.parent)


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


class TestStyledButtonThemeText(unittest.TestCase):
    """Default (no text_color) StyledButton must follow the live theme text colour,
    not the frozen import-time snapshot (regression: white icons invisible on light themes)."""

    def setUp(self):
        from app.ui.theme import C
        self._C = C
        self._orig = C.current_theme if hasattr(C, "current_theme") else "Dark Blue"

    def tearDown(self):
        self._C.set_theme(self._orig if isinstance(self._orig, str) else "Dark Blue")

    def test_default_glyph_auto_contrasts_with_bg(self):
        from app.ui.theme import C, StyledButton
        C.set_theme("Dark Blue")
        on_light = StyledButton(text="X", bg_color=[0.95, 0.95, 0.95, 1])  # no text_color -> AUTO
        self.assertLess(on_light.text_color[0], 0.5)            # dark glyph on a light fill
        on_dark = StyledButton(text="Y", bg_color=[0.10, 0.10, 0.12, 1])
        self.assertGreater(on_dark.text_color[0], 0.5)          # light glyph on a dark fill
        # changing the bg re-resolves the glyph
        on_light.bg_color = [0.08, 0.08, 0.10, 1]
        self.assertGreater(on_light.text_color[0], 0.5)

    def test_explicit_text_color_preserved(self):
        from app.ui.theme import C, StyledButton
        C.set_theme("Light Cream")
        b = StyledButton(text="Y", text_color=[0.9, 0.1, 0.1, 1])
        C.set_theme("Dark Blue")
        self.assertEqual(list(b.text_color), [0.9, 0.1, 0.1, 1])  # explicit colour untouched

    def test_explicit_theme_role_tracks(self):
        from app.ui.theme import C, StyledButton
        C.set_theme("Dark Blue")
        b = StyledButton(text="Z", text_color=C.TEXT)            # explicit theme role
        self.assertGreater(b.text_color[0], 0.5)                 # light on dark
        C.set_theme("Light Cream")
        self.assertLess(b.text_color[0], 0.5)                    # tracks -> dark on light
        sec = StyledButton(text="S", text_color=C.TEXT_SECONDARY)
        sec_dark = list(sec.text_color)
        C.set_theme("Dark Blue")
        self.assertNotEqual(list(sec.text_color), sec_dark)      # secondary role tracks too

    def test_disabled_dims_but_stays_legible(self):
        # Kivy's Label draws `disabled_color` (default white@.3 -> invisible on light cards),
        # NOT `color`, while disabled — so assert the property that actually renders.
        from app.ui.theme import C, Icons, StyledButton, _contrast
        for theme in ("Dark Blue", "Light Green"):
            C.set_theme(theme)
            b = StyledButton(text="Stop", icon=Icons.STOP, bg_color=list(C.BG_CARD), disabled=True)
            bg = b._get_bg()
            self.assertNotEqual(list(b._label.disabled_color), [1, 1, 1, 0.3])     # not the Kivy default
            self.assertNotEqual(list(b._label.disabled_color), list(bg))           # not washed into the bg
            self.assertGreaterEqual(_contrast(b._label.disabled_color, bg), 3.0)   # legible while dimmed
            if b._icon_label is not None:
                self.assertEqual(list(b._icon_label.disabled_color), list(b._label.disabled_color))
            b.disabled = False
            self.assertEqual(list(b._label.color), list(b.text_color))   # restored on enable


class TestStyledButtonPressRing(unittest.TestCase):
    """Issue #33 Layer 1 (B): press shows an edge-visible ring that contrasts with the
    SURROUNDING surface (light on dark themes, dark on light) — not the button fill."""

    def setUp(self):
        from app.ui.theme import C
        self._C = C
        self._orig = C.theme_name

    def tearDown(self):
        self._C.set_theme(self._orig)

    def test_press_raises_ring(self):
        from app.ui.theme import C, StyledButton
        C.set_theme("Dark Blue")
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        self.assertEqual(b._ring_alpha, 0.0)          # idle: no ring
        b.state = "down"
        self.assertEqual(b._ring_alpha, StyledButton._RING_MAX)   # pressed: ring on, immediately

    def test_ring_color_contrasts_surface_not_fill(self):
        # A bright accent fill would give a DARK readable_fg; the ring must instead be light
        # on dark themes so its glow is visible against the card/app bg it's drawn onto.
        from app.ui.theme import C, StyledButton
        C.set_theme("Dark Blue")
        b = StyledButton(text="Save", bg_color=C.ACCENT)   # bright fill
        self.assertGreater(b._ring_rgb()[0], 0.5)          # light ring on a dark theme
        C.set_theme("Light Cream")
        self.assertLess(b._ring_rgb()[0], 0.5)             # dark ring on a light theme

    def test_ring_resets_when_disabled_while_pressed(self):
        # Disabling a pressed button before release must clear the ring, else re-enabling
        # later repaints a stuck full-opacity ring (no release event ever follows).
        from app.ui.theme import C, StyledButton
        C.set_theme("Dark Blue")
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        b.state = "down"
        self.assertEqual(b._ring_alpha, StyledButton._RING_MAX)
        b.disabled = True
        self.assertEqual(b._ring_alpha, 0.0)


class TestStyledButtonFlashConfirm(unittest.TestCase):
    """Issue #33 Layer 2 (E): flash_confirm briefly morphs the label/icon to a success
    cue, then reverts to the true original (reentrancy-safe)."""

    def test_swaps_label_then_reverts(self):
        from app.ui.theme import C, StyledButton
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        b.flash_confirm("Saved")
        self.assertTrue(b._confirming)
        self.assertEqual(b._label.text, "Saved")
        b._end_confirm()
        self.assertFalse(b._confirming)
        self.assertEqual(b._label.text, "Save")

    def test_reentrant_keeps_true_original(self):
        from app.ui.theme import C, StyledButton
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        b.flash_confirm("Saved")
        b.flash_confirm("Saved")            # tapped again mid-flash
        self.assertEqual(b._confirm_orig[0], "Save")   # not the intermediate "Saved"
        b._end_confirm()
        self.assertEqual(b._label.text, "Save")

    def test_morphs_and_restores_icon(self):
        from app.ui.theme import C, Icons, StyledButton
        b = StyledButton(text="Save", icon=Icons.PENCIL, bg_color=C.ACCENT)
        b.flash_confirm("Saved", icon=Icons.CHECK)
        self.assertEqual(b._icon_label.text, Icons.CHECK)
        b._end_confirm()
        self.assertEqual(b._icon_label.text, Icons.PENCIL)

    def test_text_only_button_renders_icon_inline(self):
        # No _icon_label to morph, so the glyph is drawn inline via Icons-font markup
        # (a bare MDI codepoint would be tofu in the label's Roboto font).
        from app.ui.theme import C, Icons, StyledButton
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        self.assertIsNone(b._icon_label)
        b.flash_confirm("Saved", icon=Icons.CHECK)
        self.assertTrue(b._label.markup)
        self.assertIn(Icons.CHECK, b._label.text)
        self.assertIn("Saved", b._label.text)
        b._end_confirm()
        self.assertFalse(b._label.markup)
        self.assertEqual(b._label.text, "Save")

    def test_tints_bg_then_restores(self):
        # Text-only buttons need a colour pop to read the confirm; MDI check glyph would
        # be tofu in the label's Roboto font, so bg tint is the font-safe cue.
        from app.ui.theme import C, StyledButton
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        orig = list(b.bg_color)
        b.flash_confirm("Saved", confirm_color=C.SHAMATHA)
        self.assertEqual(list(b.bg_color), list(C.SHAMATHA))
        b._end_confirm()
        self.assertEqual(list(b.bg_color), orig)

    def test_original_markup_state_restored(self):
        # A button that legitimately uses markup must not have it clobbered off by a confirm.
        from app.ui.theme import C, StyledButton
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        b._label.markup = True                      # pretend this button renders markup
        b.flash_confirm("Saved", icon=None)
        b._end_confirm()
        self.assertTrue(b._label.markup)            # restored, not forced False

    def test_inline_icon_falls_back_when_font_unavailable(self):
        # Without the MDI font, the inline branch must degrade to plain text, not emit a
        # [font=Icons] tag that renders tofu.
        import app.ui.theme as theme
        from app.ui.theme import C, Icons, StyledButton
        b = StyledButton(text="Save", bg_color=C.ACCENT)
        orig_flag = theme.ICONS_AVAILABLE
        theme.ICONS_AVAILABLE = False
        try:
            b.flash_confirm("Saved", icon=Icons.CHECK)
            self.assertNotIn("font=Icons", b._label.text)
            self.assertIn("Saved", b._label.text)
        finally:
            theme.ICONS_AVAILABLE = orig_flag

    def test_icon_only_button_morphs_icon(self):
        # Icon-only button (empty text) has its _label off-tree; confirm morphs the icon and
        # must not push confirm text onto the invisible label.
        from app.ui.theme import C, Icons, StyledButton
        b = StyledButton(text="", icon=Icons.PENCIL, bg_color=C.ACCENT)
        self.assertIsNone(b._label.parent)          # label never added for icon-only
        b.flash_confirm("Saved", icon=Icons.CHECK)
        self.assertEqual(b._icon_label.text, Icons.CHECK)
        self.assertEqual(b._label.text, "")         # confirm text not written to off-tree label
        b._end_confirm()
        self.assertEqual(b._icon_label.text, Icons.PENCIL)
