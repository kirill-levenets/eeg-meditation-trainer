import time
import unittest

from app.session.manager import SessionManager, SessionState


class TestSessionManager(unittest.TestCase):
    """Test session lifecycle."""

    def test_compute_statistics_duration_nonzero_while_running(self):
        # Regression: a 60s partial DB flush calls compute_statistics() on a
        # RUNNING session. It must report live elapsed, not the unfinalized
        # _elapsed field (which is 0 until stop()) — otherwise a session killed
        # mid-run leaves a 0-duration row in History.
        sm = SessionManager()
        sm.start(threshold=50)
        sm._start_time = time.time() - 5.0  # simulate 5s elapsed
        sm.add_metric({"meditation_score": 60, "shamatha_score": 40, "state": "x"})
        stats = sm.compute_statistics()
        self.assertGreaterEqual(stats["duration"], 4)
        self.assertEqual(sm.state, SessionState.RUNNING)  # not mutated by stats

    def test_compute_statistics_duration_nonzero_with_no_metrics(self):
        sm = SessionManager()
        sm.start(threshold=50)
        sm._start_time = time.time() - 7.0
        stats = sm.compute_statistics()  # empty-accumulator branch
        self.assertGreaterEqual(stats["duration"], 6)

    def test_stop_duration_unchanged_by_elapsed_seconds_switch(self):
        sm = SessionManager()
        sm.start(threshold=50)
        sm._start_time = time.time() - 3.0
        stats = sm.stop()
        self.assertGreaterEqual(stats["duration"], 2)

    def test_start_stop(self):
        sm = SessionManager()
        self.assertEqual(sm.state, SessionState.IDLE)
        sm.start(threshold=50)
        self.assertEqual(sm.state, SessionState.RUNNING)
        stats = sm.stop()
        self.assertEqual(sm.state, SessionState.FINISHED)
        self.assertIn("duration", stats)

    def test_pause_resume(self):
        sm = SessionManager()
        sm.start()
        sm.pause()
        self.assertEqual(sm.state, SessionState.PAUSED)
        sm.resume()
        self.assertEqual(sm.state, SessionState.RUNNING)

    def test_add_metric_accumulates(self):
        sm = SessionManager()
        sm.start(threshold=50)
        sm.add_metric({"meditation_score": 60, "state": "Stable Focus"})
        sm.add_metric({"meditation_score": 30, "state": "Gross Distraction"})
        self.assertEqual(sm.metrics_count, 2)

    def test_elapsed_formatted(self):
        sm = SessionManager()
        self.assertEqual(sm.elapsed_formatted, "00:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
