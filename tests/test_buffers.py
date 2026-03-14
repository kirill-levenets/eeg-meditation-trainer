import unittest

from app.eeg.buffer import RollingBuffer, VarianceBuffer


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
