"""The tick thread and the UI thread share one connection: their write transactions must not interleave."""

import threading

from app.storage.database import DatabaseManager


def _metric_rows(n: int) -> list[dict]:
    return [{"timestamp": i, "shamatha_score": 50.0} for i in range(n)]


def test_a_second_write_waits_for_the_open_transaction(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    inside = threading.Event()
    release = threading.Event()
    b_done = threading.Event()

    def hold_transaction():
        with db._write() as c:
            c.execute("INSERT INTO app_settings (key, value) VALUES ('a', '1')")
            inside.set()
            release.wait(2.0)

    def second_writer():
        db.set_setting("b", "2")
        b_done.set()

    a = threading.Thread(target=hold_transaction)
    a.start()
    assert inside.wait(2.0)
    b = threading.Thread(target=second_writer)
    b.start()
    assert not b_done.wait(0.2), "second write ran inside the other thread's open transaction"
    release.set()
    a.join(2.0)
    b.join(2.0)
    assert db.get_setting("a") == "1" and db.get_setting("b") == "2"


def test_metrics_batches_and_setting_writes_race_without_errors_or_lost_rows(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    errors: list[BaseException] = []
    batches, rows_per_batch, settings_writes = 60, 120, 600

    def tick_thread():
        try:
            for _ in range(batches):
                db.save_metrics_batch(1, _metric_rows(rows_per_batch))
        except BaseException as e:
            errors.append(e)

    def ui_thread():
        try:
            for i in range(settings_writes):
                db.set_user_setting(1, "threshold", str(i))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=tick_thread), threading.Thread(target=ui_thread)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60.0)
    assert errors == []
    count = db._conn.execute("SELECT COUNT(*) FROM metrics WHERE session_id = 1").fetchone()[0]
    assert count == batches * rows_per_batch
    assert db.get_user_setting(1, "threshold") == str(settings_writes - 1)


def test_a_failed_write_rolls_back_and_releases_the_lock(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    try:
        with db._write() as c:
            c.execute("INSERT INTO app_settings (key, value) VALUES ('x', '1')")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.get_setting("x") is None
    db.set_setting("y", "2")  # the lock was released
    assert db.get_setting("y") == "2"
