from app.ui.live_session import _format_stats_slots


def test_live_mode_shows_instant_values():
    metrics = {
        "shamatha_score": 72,
        "distraction": 18,
        "sinking": 5,
        "native_attention": 60,
        "native_meditation": 55,
    }
    stats = {}  # unused in live mode
    titles, values = _format_stats_slots("live", metrics=metrics, stats=stats)
    assert titles == ["Shamatha", "Distraction", "Sinking", "NS Attn", "NS Med"]
    assert values == ["72", "18", "5", "60", "55"]


def test_aggregate_mode_shows_session_totals():
    metrics = {}
    stats = {
        "avg_shamatha": 63.4,
        "avg_meditation": 58.1,
        "time_above_threshold": 420,  # seconds
        "time_shamatha_90": 90,
        "longest_streak": 60,
    }
    titles, values = _format_stats_slots("aggregate", metrics=metrics, stats=stats)
    assert titles == ["Avg Sham", "Avg Med", ">Thresh", "\u226590", "Streak"]
    assert values[0] == "63.4"
    assert values[1] == "58.1"
    # format_duration: 420s = "7m 00s", 90s = "1m 30s", 60s = "1m 00s"
    assert values[2] == "7m 00s"
    assert values[3] == "1m 30s"
    assert values[4] == "1m 00s"


def test_idle_aggregate_shows_zeros():
    titles, values = _format_stats_slots("aggregate", metrics={}, stats={
        "avg_shamatha": 0.0,
        "avg_meditation": 0.0,
        "time_above_threshold": 0,
        "time_shamatha_90": 0,
        "longest_streak": 0,
    })
    assert values == ["0.0", "0.0", "0s", "0s", "0s"]


def test_stats_view_mode_roundtrips_user_settings(tmp_path):
    """Saving and loading stats_view_mode via the Database API preserves the value."""
    from app.storage.database import DatabaseManager

    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path=db_path)
    uid = db.create_user("alice")
    db.set_user_setting(uid, "stats_view_mode", "aggregate")
    value = db.get_user_setting(uid, "stats_view_mode")
    assert value == "aggregate"
