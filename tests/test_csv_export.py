import os
import zipfile

from app.storage.csv_export import build_sessions_zip


def test_build_sessions_zip_one_entry_per_session(tmp_path):
    path = str(tmp_path / "out.zip")
    n = build_sessions_zip(path, {12: "a,b\n1,2\n", 14: "a,b\n3,4\n"})
    assert n == 2
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["session_12.csv", "session_14.csv"]
        assert z.read("session_12.csv").decode() == "a,b\n1,2\n"
        assert z.read("session_14.csv").decode() == "a,b\n3,4\n"


def test_build_sessions_zip_skips_empty_csv(tmp_path):
    path = str(tmp_path / "out.zip")
    n = build_sessions_zip(path, {12: "a,b\n1,2\n", 99: ""})
    assert n == 1
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == ["session_12.csv"]


def test_build_sessions_zip_nothing_to_write_creates_no_file(tmp_path):
    path = str(tmp_path / "out.zip")
    assert build_sessions_zip(path, {}) == 0
    assert build_sessions_zip(path, {5: ""}) == 0   # all empty
    assert not os.path.exists(path)


def test_zip_from_real_db_sessions(tmp_path):
    from app.storage.database import DatabaseManager
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    uid = db.create_user("a")
    s1 = db.save_session({"duration": 10}, user_id=uid)
    db.save_metrics_batch(s1, [{"shamatha_score": 55}, {"shamatha_score": 58}])
    s2 = db.save_session({"duration": 20}, user_id=uid)
    db.save_metrics_batch(s2, [{"shamatha_score": 40}])
    mapping = {sid: db.export_session_csv(sid) for sid in (s1, s2)}
    zpath = str(tmp_path / "out.zip")
    assert build_sessions_zip(zpath, mapping) == 2
    with zipfile.ZipFile(zpath) as z:
        assert sorted(z.namelist()) == [f"session_{s1}.csv", f"session_{s2}.csv"]
        c1 = z.read(f"session_{s1}.csv").decode()
        assert "shamatha_score" in c1.splitlines()[0]   # header
        assert len(c1.strip().splitlines()) == 3         # header + 2 rows
