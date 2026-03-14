import unittest

from app.session.manager import SessionManager, SessionState


class TestSessionManager(unittest.TestCase):
    """Test session lifecycle."""

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
