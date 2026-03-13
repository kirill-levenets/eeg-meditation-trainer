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
    """Test white noise volume computation."""

    def test_volume_at_threshold(self):
        from app.audio_feedback.noise import WhiteNoiseGenerator
        gen = WhiteNoiseGenerator()
        gen.set_threshold(50)
        vol = gen.compute_volume(50)
        self.assertAlmostEqual(vol, 0.0)

    def test_volume_above_threshold(self):
        from app.audio_feedback.noise import WhiteNoiseGenerator
        gen = WhiteNoiseGenerator()
        gen.set_threshold(50)
        vol = gen.compute_volume(100)
        self.assertAlmostEqual(vol, 0.0)

    def test_volume_at_zero(self):
        from app.audio_feedback.noise import WhiteNoiseGenerator
        gen = WhiteNoiseGenerator()
        gen.set_threshold(50)
        vol = gen.compute_volume(0)
        self.assertAlmostEqual(vol, 1.0)

    def test_volume_proportional(self):
        from app.audio_feedback.noise import WhiteNoiseGenerator
        gen = WhiteNoiseGenerator()
        gen.set_threshold(100)
        vol = gen.compute_volume(50)
        self.assertAlmostEqual(vol, 0.5)
        gen.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
