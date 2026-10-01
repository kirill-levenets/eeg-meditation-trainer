"""delete_user must purge the user's sessions, metrics, and settings — not orphan them.

Regression: delete_user ran only DELETE FROM users, leaving orphan sessions (visible in
the All-Users view), orphan metrics, and orphan user_{id}_* settings rows forever."""
import os
import tempfile

from app.storage.database import DatabaseManager


def _db():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    return DatabaseManager(db_path=path)


def test_delete_user_purges_sessions_metrics_settings_and_spares_others():
    db = _db()
    try:
        a = db.create_user("A")
        b = db.create_user("B")
        sid = db.save_session({"duration": 1}, user_id=a)
        db.save_metrics_batch(sid, [{"timestamp": 0.0, "meditation_score": 5}])
        db.set_user_setting(a, "threshold", "120")
        db.set_user_setting(a, "saved_programs", "[]")
        db.set_user_setting(b, "threshold", "60")
        assert db.get_user_setting(a, "threshold") == "120"
        assert db.get_session(sid) is not None
        assert db.get_session_metrics(sid)

        db.delete_user(a)

        # A's data is gone
        assert db.get_user_setting(a, "threshold") is None
        assert db.get_user_setting(a, "saved_programs") is None
        assert db.get_session(sid) is None
        assert db.get_session_metrics(sid) == []
        assert db.get_all_sessions(a) == []
        # B is untouched
        assert db.get_user_setting(b, "threshold") == "60"
    finally:
        db.close()


def test_delete_user_settings_prefix_does_not_match_other_users():
    # user_1 delete must not touch user_11's settings (GLOB, not LIKE-with-_-wildcard).
    db = _db()
    try:
        u1 = db.create_user("one")
        # force a second user whose id string starts with u1's id
        while True:
            uid = db.create_user(f"u{db.get_all_users().__len__()}")
            if str(uid).startswith(str(u1)) and uid != u1:
                u_long = uid
                break
        db.set_user_setting(u1, "threshold", "10")
        db.set_user_setting(u_long, "threshold", "20")
        db.delete_user(u1)
        assert db.get_user_setting(u_long, "threshold") == "20"
    finally:
        db.close()
