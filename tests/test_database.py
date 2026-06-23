import os
import tempfile
import unittest

from app.storage.database import DatabaseManager


class TestStorageIntegration(unittest.TestCase):
    """Test database operations."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "test_unit_meditation.db")
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


class TestDatabaseExtensions(unittest.TestCase):
    """Test new DB methods: settings, rename, delete, size, counts."""

    def setUp(self):
        self._tmp = os.path.join(tempfile.gettempdir(), "test_ext.db")
        self.db = DatabaseManager(db_path=self._tmp)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def test_set_and_get_setting(self):
        self.db.set_setting("foo", "bar")
        self.assertEqual(self.db.get_setting("foo"), "bar")

    def test_get_setting_missing(self):
        self.assertIsNone(self.db.get_setting("nonexistent"))

    def test_setting_upsert(self):
        self.db.set_setting("key", "v1")
        self.db.set_setting("key", "v2")
        self.assertEqual(self.db.get_setting("key"), "v2")

    def test_rename_session(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.rename_session(sid, "Morning sit")
        session = self.db.get_session(sid)
        self.assertEqual(session["session_name"], "Morning sit")

    def test_delete_session_removes(self):
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_metrics_batch(sid, [{"timestamp": 0.5}])
        self.db.delete_session(sid)
        self.assertIsNone(self.db.get_session(sid))
        self.assertEqual(len(self.db.get_session_metrics(sid)), 0)

    def test_db_size_bytes(self):
        size = self.db.get_db_size_bytes()
        self.assertGreater(size, 0)

    def test_record_counts(self):
        counts = self.db.get_record_counts()
        self.assertIn("sessions", counts)
        self.assertIn("metrics", counts)
        self.assertIn("users", counts)
        self.assertEqual(counts["sessions"], 0)

    def test_record_counts_after_insert(self):
        self.db.save_session({"duration": 60, "threshold_used": 50})
        counts = self.db.get_record_counts()
        self.assertEqual(counts["sessions"], 1)

    def test_user_setting_set_get(self):
        uid = self.db.create_user("Alice")
        self.db.set_user_setting(uid, "timer_enabled", "True")
        self.assertEqual(self.db.get_user_setting(uid, "timer_enabled"), "True")

    def test_user_setting_isolated_per_user(self):
        uid1 = self.db.create_user("Alice")
        uid2 = self.db.create_user("Bob")
        self.db.set_user_setting(uid1, "timer_minutes", "20")
        self.db.set_user_setting(uid2, "timer_minutes", "45")
        self.assertEqual(self.db.get_user_setting(uid1, "timer_minutes"), "20")
        self.assertEqual(self.db.get_user_setting(uid2, "timer_minutes"), "45")

    def test_user_setting_missing_returns_none(self):
        uid = self.db.create_user("Alice")
        self.assertIsNone(self.db.get_user_setting(uid, "nonexistent"))

    def test_user_json_setting_roundtrip_list(self):
        uid = self.db.create_user("Alice")
        self.db.set_user_json_setting(uid, "graph_series", ["a", "b", "c"])
        self.assertEqual(self.db.get_user_json_setting(uid, "graph_series"), ["a", "b", "c"])

    def test_user_json_setting_roundtrip_dict(self):
        uid = self.db.create_user("Alice")
        self.db.set_user_json_setting(uid, "cfg", {"x": 1, "y": [2, 3]})
        self.assertEqual(self.db.get_user_json_setting(uid, "cfg"), {"x": 1, "y": [2, 3]})

    def test_user_json_setting_missing_returns_default(self):
        uid = self.db.create_user("Alice")
        self.assertEqual(self.db.get_user_json_setting(uid, "absent", default=[]), [])
        self.assertIsNone(self.db.get_user_json_setting(uid, "absent"))

    def test_user_json_setting_corrupt_returns_default(self):
        uid = self.db.create_user("Alice")
        self.db.set_user_setting(uid, "broken", "{not json")
        self.assertEqual(self.db.get_user_json_setting(uid, "broken", default=["fallback"]), ["fallback"])

    def test_user_json_setting_isolated_per_user(self):
        uid1 = self.db.create_user("Alice")
        uid2 = self.db.create_user("Bob")
        self.db.set_user_json_setting(uid1, "k", [1])
        self.db.set_user_json_setting(uid2, "k", [2])
        self.assertEqual(self.db.get_user_json_setting(uid1, "k"), [1])
        self.assertEqual(self.db.get_user_json_setting(uid2, "k"), [2])

    def test_update_session_stats(self):
        sid = self.db.save_session({"duration": 0, "threshold_used": 50})
        session = self.db.get_session(sid)
        self.assertEqual(session["duration"], 0)
        self.db.update_session(sid, {
            "duration": 300, "threshold_used": 80,
            "avg_meditation": 120.0, "avg_shamatha": 55.0,
            "max_meditation": 190.0, "time_above_threshold": 200,
        })
        updated = self.db.get_session(sid)
        self.assertEqual(updated["duration"], 300)
        self.assertEqual(updated["threshold_used"], 80)
        self.assertAlmostEqual(updated["avg_meditation"], 120.0)

    def test_create_user_duplicate_raises(self):
        from app.storage.database import UserExistsError
        self.db.create_user("Alice")
        with self.assertRaises(UserExistsError) as ctx:
            self.db.create_user("Alice")
        err = ctx.exception
        self.assertEqual(err.name, "Alice")
        self.assertIsInstance(err.user_id, int)
        self.assertGreater(err.user_id, 0)

    def test_find_user_by_name_existing(self):
        uid = self.db.create_user("Bob")
        found = self.db.find_user_by_name("Bob")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], uid)
        self.assertEqual(found["name"], "Bob")

    def test_find_user_by_name_missing(self):
        self.assertIsNone(self.db.find_user_by_name("Nonexistent"))

    def test_find_user_by_name_case_sensitive(self):
        self.db.create_user("Charlie")
        self.assertIsNone(self.db.find_user_by_name("charlie"))

    def test_sessions_has_custom_formulas_column(self):
        cur = self.db._conn.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
        self.assertIn("custom_formulas", cols)

    def test_recompute_formula_series_matches_direct_eval(self):
        from app.metrics.custom_formula import CustomFormulaEvaluator
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_metrics_batch(sid, [{
            "timestamp": 0.5,
            "alpha1": 100, "alpha2": 50,
            "beta1": 10, "beta2": 5,
            "delta": 0, "theta": 0,
            "gamma1": 0, "gamma2": 0,
            "meditation_score": 0, "shamatha_score": 0,
            "native_attention": 0, "native_meditation": 0,
            "marker": 0,
        }])
        ev = CustomFormulaEvaluator()
        ev.set_formula("alpha + beta")
        series = self.db.recompute_formula_series(sid, {"custom_formula": ev})
        self.assertEqual(len(series["custom_formula"]), 1)
        self.assertAlmostEqual(series["custom_formula"][0], 165.0, places=3)

    def test_recompute_formula_series_skips_invalid(self):
        from app.metrics.custom_formula import CustomFormulaEvaluator
        sid = self.db.save_session({"duration": 60, "threshold_used": 50})
        self.db.save_metrics_batch(sid, [{"timestamp": 0.5, "alpha1": 10}])
        ev_valid = CustomFormulaEvaluator()
        ev_valid.set_formula("alpha1")
        ev_invalid = CustomFormulaEvaluator()
        # no set_formula call — is_valid is False
        series = self.db.recompute_formula_series(sid, {"good": ev_valid, "bad": ev_invalid})
        self.assertNotIn("bad", series)
        self.assertEqual(series["good"], [10.0])  # alpha1_raw=10 → formula "alpha1"


if __name__ == "__main__":
    unittest.main(verbosity=2)
