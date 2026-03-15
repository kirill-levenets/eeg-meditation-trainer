import unittest

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


class TestMetricsEngine(unittest.TestCase):
    """Test full metrics pipeline."""

    def setUp(self):
        self.engine = MetricsEngine()
        self.sample = {
            "timestamp": 1.0,
            "delta": 32000.0,
            "theta": 17000.0,
            "alpha1": 30000.0,
            "alpha2": 24000.0,
            "beta1": 12000.0,
            "beta2": 6000.0,
            "gamma1": 6400.0,
            "gamma2": 3400.0,
            "attention": 50,
            "meditation": 60,
        }

    def test_derive_bands(self):
        bands = MetricsEngine.derive_bands(self.sample)
        self.assertAlmostEqual(bands["alpha"], 54000.0)
        self.assertAlmostEqual(bands["beta"], 18000.0)
        self.assertAlmostEqual(bands["gamma"], 9800.0)
        self.assertAlmostEqual(bands["theta"], 17000.0)
        self.assertAlmostEqual(bands["delta"], 32000.0)

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
        norms = MetricsEngine.normalize_bands(bands)
        calmness = self.engine.compute_calmness(norms)
        self.assertGreater(calmness, 0.0)

    def test_meditation_score_in_range(self):
        bands_sqrt = MetricsEngine.compute_sqrt_relative_bands(self.sample)
        score = self.engine.compute_meditation_score(bands_sqrt)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 200.0)

    def test_sinking_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        norms = MetricsEngine.normalize_bands(bands)
        sinking = self.engine.compute_sinking(norms)
        self.assertGreater(sinking, 0.0)
        self.assertLess(sinking, 100.0)

    def test_distraction_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        norms = MetricsEngine.normalize_bands(bands)
        distraction = self.engine.compute_distraction(norms)
        self.assertGreater(distraction, 0.0)
        self.assertLess(distraction, 100.0)

    def test_shamatha_in_range(self):
        bands = MetricsEngine.derive_bands(self.sample)
        norms = MetricsEngine.normalize_bands(bands)
        calmness = self.engine.compute_calmness(norms)
        shamatha = self.engine.compute_shamatha(calmness, norms, 10.0)
        self.assertGreater(shamatha, 0.0)
        self.assertLess(shamatha, 100.0)

    def test_process_sample_returns_all_keys(self):
        result = self.engine.process_sample(self.sample)
        expected_keys = [
            "timestamp", "alpha_norm", "beta_norm", "gamma_norm",
            "theta_norm", "delta_norm", "meditation_score", "distraction",
            "subtle_distraction", "sinking", "shamatha_score", "stability",
            "state", "calmness", "native_attention", "native_meditation",
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
            meditation_score=100, stability=500, sinking=20, distraction=20
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
            meditation_score=50
        )
        self.assertAlmostEqual(result, 0.0)

    def test_high_alpha_gives_high_calmness(self):
        high_alpha_sample = {
            "timestamp": 1.0,
            "delta": 5000.0,
            "theta": 5000.0,
            "alpha1": 200000.0,
            "alpha2": 200000.0,
            "beta1": 2000.0,
            "beta2": 2000.0,
            "gamma1": 500.0,
            "gamma2": 500.0,
            "attention": 50,
            "meditation": 80,
        }
        bands = MetricsEngine.derive_bands(high_alpha_sample)
        norms = MetricsEngine.normalize_bands(bands)
        calmness = self.engine.compute_calmness(norms)
        self.assertGreater(calmness, 3.0)

    def test_sqrt_relative_bands_sum(self):
        bands_sqrt = MetricsEngine.compute_sqrt_relative_bands(self.sample)
        for key in ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2"):
            self.assertIn(key, bands_sqrt)
            self.assertGreaterEqual(bands_sqrt[key], 0.0)
            self.assertLessEqual(bands_sqrt[key], 1.0)

    def test_high_alpha_gives_high_meditation(self):
        high_alpha = {
            "timestamp": 1.0,
            "delta": 5000.0, "theta": 5000.0,
            "alpha1": 200000.0, "alpha2": 200000.0,
            "beta1": 2000.0, "beta2": 2000.0,
            "gamma1": 500.0, "gamma2": 500.0,
        }
        result = self.engine.process_sample(high_alpha)
        self.assertGreater(result["meditation_score"], 150.0)

    def test_high_beta_gives_low_meditation(self):
        high_beta = {
            "timestamp": 1.0,
            "delta": 10000.0, "theta": 10000.0,
            "alpha1": 3000.0, "alpha2": 2000.0,
            "beta1": 50000.0, "beta2": 40000.0,
            "gamma1": 10000.0, "gamma2": 5000.0,
        }
        result = self.engine.process_sample(high_beta)
        self.assertLess(result["meditation_score"], 50.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
