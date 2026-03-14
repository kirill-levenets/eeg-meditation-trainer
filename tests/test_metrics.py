import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.eeg.buffer import RollingBuffer, VarianceBuffer
from app.metrics.engine import MetricsEngine


class TestSigmoid(unittest.TestCase):
    """Test sigmoid normalization function."""

    def test_midpoint_returns_half_scale(self):
        result = MetricsEngine.sigmoid(1.5, 2.0, 1.5, 100.0)
        self.assertAlmostEqual(result, 50.0, places=2)

    def test_high_input_approaches_max(self):
        result = MetricsEngine.sigmoid(10.0, 2.0, 1.5, 100.0)
        self.assertGreater(result, 99.0)

    def test_low_input_approaches_zero(self):
        result = MetricsEngine.sigmoid(-5.0, 2.0, 1.5, 100.0)
        self.assertLess(result, 1.0)

    def test_custom_max_scale(self):
        result = MetricsEngine.sigmoid(1.5, 2.0, 1.5, 200.0)
        self.assertAlmostEqual(result, 100.0, places=2)

    def test_output_always_positive(self):
        for raw in [-10, -1, 0, 0.5, 1, 5, 100]:
            result = MetricsEngine.sigmoid(raw, 2.0, 1.5)
            self.assertGreater(result, 0.0)


class TestRollingBuffer(unittest.TestCase):
    """Test signal smoothing rolling buffer."""

    def test_single_value(self):
        rb = RollingBuffer(window_size=5)
        result = rb.push("alpha", 10.0)
        self.assertAlmostEqual(result, 10.0)

    def test_full_window_average(self):
        rb = RollingBuffer(window_size=5)
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            result = rb.push("alpha", v)
        self.assertAlmostEqual(result, 30.0)

    def test_sliding_window(self):
        rb = RollingBuffer(window_size=3)
        rb.push("x", 10.0)
        rb.push("x", 20.0)
        rb.push("x", 30.0)
        result = rb.push("x", 40.0)
        self.assertAlmostEqual(result, 30.0)  # (20+30+40)/3

    def test_multiple_bands(self):
        rb = RollingBuffer(window_size=2)
        rb.push("alpha", 10.0)
        rb.push("beta", 100.0)
        a = rb.push("alpha", 20.0)
        b = rb.push("beta", 200.0)
        self.assertAlmostEqual(a, 15.0)
        self.assertAlmostEqual(b, 150.0)

    def test_reset(self):
        rb = RollingBuffer(window_size=3)
        rb.push("alpha", 100.0)
        rb.reset()
        result = rb.push("alpha", 5.0)
        self.assertAlmostEqual(result, 5.0)

    def test_push_sample(self):
        rb = RollingBuffer(window_size=2)
        sample1 = {"alpha1": 10.0, "beta1": 20.0, "timestamp": 1.0}
        sample2 = {"alpha1": 30.0, "beta1": 40.0, "timestamp": 2.0}
        rb.push_sample(sample1)
        result = rb.push_sample(sample2)
        self.assertAlmostEqual(result["alpha1"], 20.0)
        self.assertAlmostEqual(result["beta1"], 30.0)
        self.assertEqual(result["timestamp"], 2.0)


class TestVarianceBuffer(unittest.TestCase):
    """Test variance buffer for stability calculation."""

    def test_constant_values_zero_variance(self):
        vb = VarianceBuffer(max_size=10)
        for _ in range(10):
            vb.push(50.0)
        self.assertAlmostEqual(vb.variance(), 0.0)

    def test_known_variance(self):
        vb = VarianceBuffer(max_size=4)
        for v in [2.0, 4.0, 6.0, 8.0]:
            vb.push(v)
        # mean=5, variance = ((2-5)^2 + (4-5)^2 + (6-5)^2 + (8-5)^2) / 4 = 5.0
        self.assertAlmostEqual(vb.variance(), 5.0)

    def test_single_value_zero_variance(self):
        vb = VarianceBuffer(max_size=10)
        vb.push(42.0)
        self.assertAlmostEqual(vb.variance(), 0.0)

    def test_empty_zero_variance(self):
        vb = VarianceBuffer(max_size=10)
        self.assertAlmostEqual(vb.variance(), 0.0)

    def test_mean(self):
        vb = VarianceBuffer(max_size=5)
        for v in [10, 20, 30, 40, 50]:
            vb.push(v)
        self.assertAlmostEqual(vb.mean(), 30.0)

    def test_rolling_eviction(self):
        vb = VarianceBuffer(max_size=3)
        for v in [1, 2, 3, 10, 20, 30]:
            vb.push(v)
        self.assertAlmostEqual(vb.mean(), 20.0)


class TestMetricsEngine(unittest.TestCase):
    """Test full metrics pipeline."""

    def setUp(self):
        self.engine = MetricsEngine()
        self.sample = {
            "timestamp": 1.0,
            "delta": 300.0,
            "theta": 200.0,
            "alpha1": 500.0,
            "alpha2": 400.0,
            "beta1": 100.0,
            "beta2": 80.0,
            "gamma1": 30.0,
            "gamma2": 20.0,
            "attention": 50,
            "meditation": 60,
        }

    def test_derive_bands(self):
        bands = MetricsEngine.derive_bands(self.sample)
        self.assertAlmostEqual(bands["alpha"], 900.0)
        self.assertAlmostEqual(bands["beta"], 180.0)
        self.assertAlmostEqual(bands["gamma"], 50.0)
        self.assertAlmostEqual(bands["theta"], 200.0)
        self.assertAlmostEqual(bands["delta"], 300.0)

    def test_normalize_bands_sum_near_one(self):
        bands = MetricsEngine.derive_bands(self.sample)
        norms = MetricsEngine.normalize_bands(bands)
        total = (
            norms["alpha_norm"]
            + norms["beta_norm"]
            + norms["gamma_norm"]
            + norms["theta_norm"]
            + norms["delta_norm"]
        )
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_calmness_positive(self):
        bands = MetricsEngine.derive_bands(self.sample)
        calmness = self.engine.compute_calmness(bands)
        self.assertGreater(calmness, 0.0)

    def test_meditation_score_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        calmness = self.engine.compute_calmness(bands)
        score = self.engine.compute_meditation_score(calmness)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 200.0)

    def test_sinking_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        sinking = self.engine.compute_sinking(bands)
        self.assertGreater(sinking, 0.0)
        self.assertLess(sinking, 100.0)

    def test_distraction_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        distraction = self.engine.compute_distraction(bands)
        self.assertGreater(distraction, 0.0)
        self.assertLess(distraction, 100.0)

    def test_shamatha_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        calmness = self.engine.compute_calmness(bands)
        shamatha = self.engine.compute_shamatha(calmness, bands, 10.0)
        self.assertGreater(shamatha, 0.0)
        self.assertLess(shamatha, 100.0)

    def test_process_sample_returns_all_keys(self):
        result = self.engine.process_sample(self.sample)
        expected_keys = [
            "timestamp", "alpha_norm", "beta_norm", "gamma_norm",
            "theta_norm", "delta_norm", "meditation_score", "distraction",
            "subtle_distraction", "sinking", "shamatha_score", "stability",
            "state", "calmness",
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_state_classification_stable(self):
        state = self.engine.classify_state(
            meditation_score=100, stability=10, sinking=20, distraction=20
        )
        self.assertEqual(state, "Stable Focus")

    def test_state_classification_gross_distraction(self):
        state = self.engine.classify_state(
            meditation_score=20, stability=10, sinking=20, distraction=80
        )
        self.assertEqual(state, "Gross Distraction")

    def test_state_classification_sinking(self):
        state = self.engine.classify_state(
            meditation_score=20, stability=10, sinking=80, distraction=20
        )
        self.assertEqual(state, "Sinking")

    def test_state_classification_subtle(self):
        state = self.engine.classify_state(
            meditation_score=100, stability=50, sinking=20, distraction=20
        )
        self.assertEqual(state, "Subtle Distraction")

    def test_meditation_threshold_setter(self):
        self.engine.meditation_threshold = 60
        self.assertEqual(self.engine.meditation_threshold, 60)
        self.engine.meditation_threshold = 300
        self.assertEqual(self.engine.meditation_threshold, 200)
        self.engine.meditation_threshold = -10
        self.assertEqual(self.engine.meditation_threshold, 0)

    def test_reset_clears_buffers(self):
        self.engine.process_sample(self.sample)
        self.engine.reset()
        result = self.engine.process_sample(self.sample)
        self.assertAlmostEqual(result["stability"], 0.0)

    def test_subtle_distraction_zero_when_below_threshold(self):
        self.engine.meditation_threshold = 200
        result = self.engine.compute_subtle_distraction(
            meditation_score=50, stability=100
        )
        self.assertAlmostEqual(result, 0.0)

    def test_high_alpha_gives_high_calmness(self):
        high_alpha_sample = {
            "timestamp": 1.0,
            "delta": 50.0,
            "theta": 50.0,
            "alpha1": 2000.0,
            "alpha2": 2000.0,
            "beta1": 20.0,
            "beta2": 20.0,
            "gamma1": 5.0,
            "gamma2": 5.0,
            "attention": 50,
            "meditation": 80,
        }
        bands = MetricsEngine.derive_bands(high_alpha_sample)
        calmness = self.engine.compute_calmness(bands)
        self.assertGreater(calmness, 3.0)


class TestStorageIntegration(unittest.TestCase):
    """Test database operations."""

    def setUp(self):
        import tempfile
        self.db_path = os.path.join(tempfile.gettempdir(), "test_unit_meditation.db")
        from app.storage.database import DatabaseManager
        self.db = DatabaseManager(db_path=self.db_path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_save_and_retrieve_session(self):
        sid = self.db.save_session({
            "duration": 300,
            "threshold_used": 50,
            "avg_meditation": 65.0,
            "avg_shamatha": 40.0,
            "max_meditation": 180.0,
            "time_above_threshold": 150,
        })
        session = self.db.get_session(sid)
        self.assertIsNotNone(session)
        self.assertEqual(session["duration"], 300)
        self.assertAlmostEqual(session["avg_meditation"], 65.0)

    def test_save_and_retrieve_metrics(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_metrics_batch(sid, [
            {"timestamp": 0.5, "meditation_score": 55, "shamatha_score": 35},
            {"timestamp": 1.0, "meditation_score": 60, "shamatha_score": 38},
        ])
        metrics = self.db.get_session_metrics(sid)
        self.assertEqual(len(metrics), 2)

    def test_update_notes(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.update_session_notes(sid, "Test note", "tag1,tag2", 4)
        session = self.db.get_session(sid)
        self.assertEqual(session["notes"], "Test note")
        self.assertEqual(session["tags"], "tag1,tag2")
        self.assertEqual(session["mood_rating"], 4)

    def test_delete_session(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.delete_session(sid)
        session = self.db.get_session(sid)
        self.assertIsNone(session)

    def test_get_all_sessions_ordered(self):
        self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_session({"duration": 120, "threshold_used": 60})
        sessions = self.db.get_all_sessions()
        self.assertEqual(len(sessions), 2)

    def test_create_user(self):
        uid = self.db.create_user("Alice")
        user = self.db.get_user(uid)
        self.assertIsNotNone(user)
        self.assertEqual(user["name"], "Alice")

    def test_get_all_users(self):
        self.db.create_user("Alice")
        self.db.create_user("Bob")
        users = self.db.get_all_users()
        self.assertEqual(len(users), 2)

    def test_delete_user(self):
        uid = self.db.create_user("Alice")
        self.db.delete_user(uid)
        self.assertIsNone(self.db.get_user(uid))

    def test_duplicate_user_raises(self):
        self.db.create_user("Alice")
        with self.assertRaises(Exception):
            self.db.create_user("Alice")

    def test_session_with_user_id(self):
        uid = self.db.create_user("Alice")
        sid = self.db.save_session({"duration": 60, "threshold_used": 50}, user_id=uid)
        session = self.db.get_session(sid)
        self.assertEqual(session["user_id"], uid)

    def test_get_sessions_filtered_by_user(self):
        uid1 = self.db.create_user("Alice")
        uid2 = self.db.create_user("Bob")
        self.db.save_session({"duration": 60, "threshold_used": 50}, user_id=uid1)
        self.db.save_session({"duration": 120, "threshold_used": 60}, user_id=uid2)
        self.db.save_session({"duration": 180, "threshold_used": 70}, user_id=uid1)
        alice_sessions = self.db.get_all_sessions(user_id=uid1)
        self.assertEqual(len(alice_sessions), 2)
        bob_sessions = self.db.get_all_sessions(user_id=uid2)
        self.assertEqual(len(bob_sessions), 1)

    def test_save_and_retrieve_raw_metrics(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_metrics_batch(sid, [{
            "timestamp": 0.5,
            "delta": 300, "theta": 200, "alpha1": 500, "alpha2": 400,
            "beta1": 100, "beta2": 80, "gamma1": 30, "gamma2": 20,
            "meditation_score": 55, "shamatha_score": 35,
            "stability": 5.0, "calmness": 3.2,
        }])
        metrics = self.db.get_session_metrics(sid)
        self.assertEqual(len(metrics), 1)
        m = metrics[0]
        self.assertAlmostEqual(m["delta_raw"], 300)
        self.assertAlmostEqual(m["alpha1_raw"], 500)
        self.assertAlmostEqual(m["stability"], 5.0)
        self.assertAlmostEqual(m["calmness"], 3.2)

    def test_export_csv(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_metrics_batch(sid, [
            {"timestamp": 0.5, "meditation_score": 55},
            {"timestamp": 1.0, "meditation_score": 60},
        ])
        csv_str = self.db.export_session_csv(sid)
        self.assertIn("meditation_score", csv_str)
        lines = csv_str.strip().split("\n")
        self.assertEqual(len(lines), 3)  # header + 2 data rows

    def test_export_csv_empty_session(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        csv_str = self.db.export_session_csv(sid)
        self.assertEqual(csv_str, "")


class TestScrollableGraphWidget(unittest.TestCase):
    """Test ScrollableGraphWidget data management (no rendering)."""

    def setUp(self):
        from app.ui.raw_eeg_screen import ScrollableGraphWidget
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
        for i in range(vp + 10):
            self.graph.add_point({"a": 1.0, "b": 2.0})
        self.assertEqual(self.graph.max_scroll, 10)

    def test_set_scroll_offset_clamped(self):
        self.graph.set_scroll_offset(999)
        self.assertEqual(self.graph._scroll_offset, 0)

    def test_clear_data(self):
        for i in range(5):
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
        from app.ui.raw_eeg_screen import ScrollableGraphWidget
        g = ScrollableGraphWidget(
            colors={"x": (1, 0, 0, 1)}, scales={"x": 100.0},
            show_value_labels=False, show_timestamps=False,
        )
        self.assertFalse(g._show_value_labels)
        self.assertFalse(g._show_timestamps)

    def test_diary_preview_loads_all_graphs(self):
        """Verify load_metrics_preview populates metrics, raw EEG, and freq graphs."""
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
        self.assertEqual(screen._raw_eeg_graph.total_points, 10)
        self.assertEqual(screen._freq_graph.total_points, 10)

    def test_diary_tab_switching(self):
        """Verify diary graph tab switching changes active graph."""
        from app.ui.diary_screen import DiaryScreen
        screen = DiaryScreen()
        self.assertEqual(screen._active_graph_tab, "metrics")
        screen._switch_graph_tab("raw")
        self.assertEqual(screen._active_graph_tab, "raw")
        screen._switch_graph_tab("freq")
        self.assertEqual(screen._active_graph_tab, "freq")
        screen._switch_graph_tab("metrics")
        self.assertEqual(screen._active_graph_tab, "metrics")


class TestMockEEGStream(unittest.TestCase):
    """Test realistic mock EEG signal generation."""

    def setUp(self):
        from app.eeg.mock_stream import MockEEGStream
        self.stream = MockEEGStream()
        self.stream.start()

    def tearDown(self):
        self.stream.stop()

    def test_sample_has_all_bands(self):
        sample = self.stream.read_sample()
        expected = {"delta", "theta", "alpha1", "alpha2",
                    "beta1", "beta2", "gamma1", "gamma2",
                    "attention", "meditation", "timestamp"}
        self.assertTrue(expected.issubset(sample.keys()))

    def test_all_values_non_negative(self):
        for _ in range(50):
            sample = self.stream.read_sample()
            for key in ("delta", "theta", "alpha1", "alpha2",
                        "beta1", "beta2", "gamma1", "gamma2"):
                self.assertGreaterEqual(sample[key], 0.0, f"{key} was negative")

    def test_attention_meditation_in_range(self):
        for _ in range(50):
            sample = self.stream.read_sample()
            self.assertGreaterEqual(sample["attention"], 0)
            self.assertLessEqual(sample["attention"], 100)
            self.assertGreaterEqual(sample["meditation"], 0)
            self.assertLessEqual(sample["meditation"], 100)

    def test_state_transitions_produce_variation(self):
        """Collect many samples and verify alpha varies (state changes)."""
        from app.eeg.mock_stream import MockEEGStream
        stream = MockEEGStream()
        stream.start()
        alphas = []
        for _ in range(100):
            s = stream.read_sample()
            alphas.append(s["alpha1"])
        stream.stop()
        # Should have meaningful variation (not constant)
        self.assertGreater(max(alphas) - min(alphas), 50.0)

    def test_smooth_step(self):
        from app.eeg.mock_stream import MockEEGStream
        self.assertAlmostEqual(MockEEGStream._smooth_step(0.0), 0.0)
        self.assertAlmostEqual(MockEEGStream._smooth_step(1.0), 1.0)
        self.assertAlmostEqual(MockEEGStream._smooth_step(0.5), 0.5)


class TestSessionManager(unittest.TestCase):
    """Test session lifecycle."""

    def test_start_stop(self):
        from app.session.manager import SessionManager, SessionState
        sm = SessionManager()
        self.assertEqual(sm.state, SessionState.IDLE)
        sm.start(threshold=50)
        self.assertEqual(sm.state, SessionState.RUNNING)
        stats = sm.stop()
        self.assertEqual(sm.state, SessionState.FINISHED)
        self.assertIn("duration", stats)

    def test_pause_resume(self):
        from app.session.manager import SessionManager, SessionState
        sm = SessionManager()
        sm.start()
        sm.pause()
        self.assertEqual(sm.state, SessionState.PAUSED)
        sm.resume()
        self.assertEqual(sm.state, SessionState.RUNNING)

    def test_add_metric_accumulates(self):
        from app.session.manager import SessionManager
        sm = SessionManager()
        sm.start(threshold=50)
        sm.add_metric({"meditation_score": 60, "state": "Stable Focus"})
        sm.add_metric({"meditation_score": 30, "state": "Gross Distraction"})
        self.assertEqual(sm.metrics_count, 2)

    def test_elapsed_formatted(self):
        from app.session.manager import SessionManager
        sm = SessionManager()
        self.assertEqual(sm.elapsed_formatted, "00:00")


class TestAudioFeedback(unittest.TestCase):
    """Test realtime white noise volume computation and lifecycle."""

    def setUp(self):
        from app.audio_feedback.noise import WhiteNoiseGenerator
        self.gen = WhiteNoiseGenerator()

    def tearDown(self):
        self.gen.cleanup()

    def test_volume_at_threshold(self):
        self.gen.set_threshold(50)
        vol = self.gen.compute_volume(50)
        self.assertAlmostEqual(vol, 0.0)

    def test_volume_above_threshold(self):
        self.gen.set_threshold(50)
        vol = self.gen.compute_volume(100)
        self.assertAlmostEqual(vol, 0.0)

    def test_volume_at_zero(self):
        self.gen.set_threshold(50)
        vol = self.gen.compute_volume(0)
        self.assertAlmostEqual(vol, 1.0)

    def test_volume_proportional(self):
        self.gen.set_threshold(100)
        vol = self.gen.compute_volume(50)
        self.assertAlmostEqual(vol, 0.5)

    def test_volume_curve_monotonically_decreasing(self):
        self.gen.set_threshold(100)
        prev_vol = self.gen.compute_volume(0)
        for score in range(10, 110, 10):
            vol = self.gen.compute_volume(score)
            self.assertLessEqual(vol, prev_vol)
            prev_vol = vol

    def test_volume_never_negative(self):
        self.gen.set_threshold(50)
        for score in range(-10, 200, 5):
            vol = self.gen.compute_volume(score)
            self.assertGreaterEqual(vol, 0.0)

    def test_volume_never_exceeds_max(self):
        from app.config import APP
        self.gen.set_threshold(50)
        for score in range(-10, 200, 5):
            vol = self.gen.compute_volume(score)
            self.assertLessEqual(vol, APP.MAX_VOLUME)

    def test_set_threshold_minimum_clamp(self):
        self.gen.set_threshold(0)
        self.assertEqual(self.gen._threshold, 1)

    def test_set_threshold_updates_value(self):
        self.gen.set_threshold(75)
        self.assertEqual(self.gen._threshold, 75)

    def test_update_sets_internal_volume(self):
        self.gen.set_threshold(100)
        self.gen.update(50)
        self.assertAlmostEqual(self.gen.volume, 0.5)

    def test_update_at_threshold_zeroes_volume(self):
        self.gen.set_threshold(50)
        self.gen.update(50)
        self.assertAlmostEqual(self.gen.volume, 0.0)

    def test_initial_state_not_playing(self):
        self.assertFalse(self.gen.is_playing)

    def test_stop_resets_volume(self):
        self.gen.set_threshold(100)
        self.gen.update(25)
        self.assertGreater(self.gen.volume, 0.0)
        self.gen.stop()
        self.assertAlmostEqual(self.gen.volume, 0.0)

    def test_stop_sets_not_playing(self):
        self.gen.stop()
        self.assertFalse(self.gen.is_playing)

    def test_cleanup_idempotent(self):
        self.gen.cleanup()
        self.gen.cleanup()  # should not raise

    def test_volume_with_different_thresholds(self):
        for threshold in [30, 50, 80, 100]:
            self.gen.set_threshold(threshold)
            vol_zero = self.gen.compute_volume(0)
            vol_threshold = self.gen.compute_volume(threshold)
            self.assertAlmostEqual(vol_zero, 1.0)
            self.assertAlmostEqual(vol_threshold, 0.0)

    def test_no_file_attributes(self):
        """Audiostream-based generator has no noise file."""
        self.assertFalse(hasattr(self.gen, "_noise_file"))

    def test_cleanup_releases_stream(self):
        self.gen._stream = "fake_stream"
        self.gen.cleanup()
        self.assertIsNone(self.gen._stream)
        self.assertIsNone(self.gen._source)

    def test_update_only_sets_internal_volume(self):
        """update() sets _volume without needing a sound object."""
        self.gen.set_threshold(100)
        self.gen.update(50)
        self.assertAlmostEqual(self.gen._volume, 0.5)

    def test_default_threshold_is_100(self):
        from app.audio_feedback.noise import WhiteNoiseGenerator
        gen = WhiteNoiseGenerator()
        self.assertEqual(gen._threshold, 100)
        gen.cleanup()

    def test_thread_safe_volume_update(self):
        import threading
        results = []

        def update_volume():
            for i in range(100):
                self.gen.update(i % 100)
                results.append(self.gen.volume)

        threads = [threading.Thread(target=update_volume) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for v in results:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
