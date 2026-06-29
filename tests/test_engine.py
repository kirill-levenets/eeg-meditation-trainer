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

    def test_meditation_score_non_negative(self):
        bands_sqrt = MetricsEngine.compute_sqrt_relative_bands(self.sample)
        score = self.engine.compute_meditation_score(bands_sqrt)
        self.assertGreaterEqual(score, 0.0)

    def test_shamatha_equals_meditation(self):
        result = self.engine.process_sample(self.sample)
        self.assertAlmostEqual(
            result["shamatha_score"], result["meditation_score"]
        )

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
            meditation_score=85, stability=10, sinking=20, distraction=20
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
            meditation_score=85, stability=500, sinking=20, distraction=20
        )
        self.assertEqual(state, "Subtle Distraction")

    def test_meditation_threshold_setter(self):
        self.engine.meditation_threshold = 60
        self.assertEqual(self.engine.meditation_threshold, 60)
        self.engine.meditation_threshold = 300
        self.assertEqual(self.engine.meditation_threshold, 100)
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
        self.assertGreater(result["meditation_score"], 75.0)

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


class TestReferenceDistraction(unittest.TestCase):
    """Distraction from the original Vernihor app.

    distraction = 100*(b1_raw+b2_raw)/a1_raw * (140-S')/100,
    gated to 0 when S'>=140 or a1p>65, clamped [0,100].
    """

    def test_main_branch_modulated(self):
        # 100*(3000+3000)/20000 = 30; 30*(140-60)/100 = 24
        result = MetricsEngine.reference_distraction(3000.0, 3000.0, 20000.0, 47, 60.0)
        self.assertAlmostEqual(result, 24.0, places=4)

    def test_alpha_gate_strictly_greater_than_65(self):
        self.assertEqual(MetricsEngine.reference_distraction(3000.0, 3000.0, 20000.0, 66, 60.0), 0.0)

    def test_alpha_pct_exactly_65_is_not_gated(self):
        # gate is a1p > 65, so 65 passes through
        self.assertAlmostEqual(MetricsEngine.reference_distraction(3000.0, 3000.0, 20000.0, 65, 60.0), 24.0, places=4)

    def test_shamatha_gate_at_140(self):
        self.assertEqual(MetricsEngine.reference_distraction(3000.0, 3000.0, 20000.0, 47, 140.0), 0.0)

    def test_clamped_to_100(self):
        # 100*60000/20000 = 300; 300*(140-0)/100 = 420 -> clamp 100
        self.assertEqual(MetricsEngine.reference_distraction(50000.0, 10000.0, 20000.0, 47, 0.0), 100.0)

    def test_zero_alpha_guard_clamps_to_100(self):
        # reference divides by raw alpha1 with no guard (inf -> clamp 100); port guards explicitly
        self.assertEqual(MetricsEngine.reference_distraction(3000.0, 3000.0, 0.0, 47, 60.0), 100.0)


class TestReferenceSinking(unittest.TestCase):
    """Sinking from the original Vernihor app.

    sinking = (45-a2p)/0.26 * (140-S')/100, gated to 0 when S'>=140 or
    a1p>=65 or a2p>=45, then gamma-damped: s /= (min(gp-9,10)/25 + 1) for
    each of gamma1/gamma2 when gp>=10 and raw<70000. Clamped [0,100].
    """

    def test_main_branch_no_gamma_damp(self):
        # (45-32)/0.26 = 50; 50*(140-40)/100 = 50; gp=5<10 -> no damp
        result = MetricsEngine.reference_sinking(40, 32, 5, 5, 5000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 50.0, places=4)

    def test_gamma1_damp(self):
        # 50 / (min(14-9,10)/25 + 1) = 50 / 1.2 = 41.6667
        result = MetricsEngine.reference_sinking(40, 32, 14, 5, 5000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 41.66667, places=4)

    def test_both_gamma_damp(self):
        # 50 / 1.2 / 1.2 = 34.7222
        result = MetricsEngine.reference_sinking(40, 32, 14, 14, 5000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 34.72222, places=4)

    def test_gamma_damp_capped_at_10(self):
        # g1p=25 -> min(16,10)=10 -> /25+1 = 1.4; 50/1.4 = 35.7143
        result = MetricsEngine.reference_sinking(40, 32, 25, 5, 5000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 35.71429, places=4)

    def test_gamma_damp_skipped_when_raw_at_70000(self):
        # gate requires gamma_raw < 70000; at 70000 no damp -> 50
        result = MetricsEngine.reference_sinking(40, 32, 14, 5, 70000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 50.0, places=4)

    def test_gamma_damp_skipped_when_pct_below_10(self):
        # g1p=9 < 10 -> no damp
        result = MetricsEngine.reference_sinking(40, 32, 9, 5, 5000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 50.0, places=4)

    def test_alpha1_gate_at_65(self):
        self.assertEqual(MetricsEngine.reference_sinking(65, 32, 5, 5, 5000.0, 5000.0, 40.0), 0.0)

    def test_alpha2_gate_at_45(self):
        self.assertEqual(MetricsEngine.reference_sinking(40, 45, 5, 5, 5000.0, 5000.0, 40.0), 0.0)

    def test_alpha2_just_below_gate_not_zeroed(self):
        # a2p=44 < 45: (45-44)/0.26 = 3.8462; *(140-40)/100 = 3.8462
        result = MetricsEngine.reference_sinking(40, 44, 5, 5, 5000.0, 5000.0, 40.0)
        self.assertAlmostEqual(result, 3.84615, places=4)

    def test_shamatha_gate_at_140(self):
        self.assertEqual(MetricsEngine.reference_sinking(40, 32, 5, 5, 5000.0, 5000.0, 140.0), 0.0)

    def test_clamped_to_100(self):
        # a2p=0 -> 45/0.26 = 173.08 -> clamp 100
        self.assertEqual(MetricsEngine.reference_sinking(40, 0, 5, 5, 5000.0, 5000.0, 40.0), 100.0)


class TestSqrtPct8Band(unittest.TestCase):
    """8-band sqrt-relative percent: round(sqrt(raw/P8)*100), from the original Vernihor app."""

    def test_known_sample(self):
        sample = {
            "delta": 4600.0, "theta": 0.0,
            "alpha1": 2500.0, "alpha2": 1600.0,  # P8 = 10000
            "beta1": 0.0, "beta2": 0.0,
            "gamma1": 900.0, "gamma2": 400.0,
        }
        pct = MetricsEngine.sqrt_pct_8band(sample)
        self.assertEqual(pct["alpha1"], 50)  # sqrt(0.25)*100
        self.assertEqual(pct["alpha2"], 40)  # sqrt(0.16)*100
        self.assertEqual(pct["gamma1"], 30)  # sqrt(0.09)*100
        self.assertEqual(pct["gamma2"], 20)  # sqrt(0.04)*100

    def test_zero_total_returns_zeros(self):
        sample = dict.fromkeys(
            ["delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2"], 0.0
        )
        self.assertEqual(
            MetricsEngine.sqrt_pct_8band(sample),
            {"alpha1": 0, "alpha2": 0, "gamma1": 0, "gamma2": 0},
        )


class TestSPrimeExposure(unittest.TestCase):
    """S' = pre-(-20) shamatha, exposed for the distraction/sinking modulation."""

    def test_s_prime_is_score_plus_20_in_unclamped_region(self):
        engine = MetricsEngine()
        high_alpha = {
            "timestamp": 1.0, "delta": 5000.0, "theta": 3000.0,
            "alpha1": 80000.0, "alpha2": 40000.0,
            "beta1": 4000.0, "beta2": 3000.0,
            "gamma1": 1000.0, "gamma2": 1000.0,
        }
        result = engine.process_sample(high_alpha)
        self.assertGreater(result["meditation_score"], 0.0)  # unclamped region
        self.assertAlmostEqual(engine.last_s_prime, result["meditation_score"] + 20.0, places=4)

    def test_meditation_score_unchanged_by_refactor(self):
        # the displayed score must stay max(0, 75*avg_ratio - 30)
        engine = MetricsEngine()
        bands_sqrt = {"alpha1": 0.5, "alpha2": 0.35355, "beta1": 0.43301,
                      "beta2": 0.43301, "theta": 0.35355, "delta": 0.35355}
        score = engine.compute_meditation_score(bands_sqrt)
        # ratio = (0.5+0.8*0.35355)/(0.43301+0.43301+0.4*0.35355+0.08*0.35355) = 0.755843
        self.assertAlmostEqual(score, max(0.0, 75.0 * 0.755843 - 30.0), places=2)


class TestReferenceIntegration(unittest.TestCase):
    """process_sample routes distraction/sinking through the ported reference formulas."""

    def test_process_sample_distraction_sinking_match_reference(self):
        engine = MetricsEngine()
        # first push -> RollingBuffer returns the value itself, so smoothed == raw
        sample = {
            "timestamp": 1.0,
            "delta": 15000.0, "theta": 10000.0,
            "alpha1": 30000.0, "alpha2": 18000.0,     # a1p~57 (<65), a2p~44 (<45): both active
            "beta1": 8000.0, "beta2": 7000.0,         # raw ratio ~0.5 -> mid-range distraction
            "gamma1": 2000.0, "gamma2": 1000.0,
        }
        result = engine.process_sample(sample)

        pct = MetricsEngine.sqrt_pct_8band(sample)
        s_prime = engine.last_s_prime
        expected_d = MetricsEngine.reference_distraction(
            sample["beta1"], sample["beta2"], sample["alpha1"], pct["alpha1"], s_prime
        )
        expected_s = MetricsEngine.reference_sinking(
            pct["alpha1"], pct["alpha2"], pct["gamma1"], pct["gamma2"],
            sample["gamma1"], sample["gamma2"], s_prime,
        )
        self.assertAlmostEqual(result["distraction"], expected_d, places=4)
        self.assertAlmostEqual(result["sinking"], expected_s, places=4)
        self.assertGreater(expected_d, 0.0)  # sample chosen to exercise the active branch


if __name__ == "__main__":
    unittest.main(verbosity=2)
