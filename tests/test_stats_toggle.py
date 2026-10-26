"""The stats bar: three slots on the metric the session is scored on, LIVE now or AVG so far (#113)."""
from dataclasses import replace

from app.session.manager import NO_SCORE, LiveScore
from app.ui.live_session import _format_stats_slots

SCORE = LiveScore(value=72.4, target=60, streak=95, average=63.44, segmented=False, time_above=420, longest_streak=60)


def test_live_shows_the_scored_metric_its_threshold_and_the_streak_now():
    assert _format_stats_slots("live", "Shamatha", SCORE) == (["Shamatha", "Target", "Streak"], ["72", "60", "1m 35s"])


def test_avg_shows_the_end_cards_numbers_so_far():
    assert _format_stats_slots("aggregate", "Shamatha", SCORE) == (["Average", "On target", "Best streak"],
                                                                   ["63", "7m 00s", "1m 00s"])


def test_a_programs_average_is_its_running_segments():
    assert _format_stats_slots("aggregate", "Alpha calm", replace(SCORE, segmented=True))[0][0] == "Segment avg"


def test_before_the_first_scored_tick_the_bar_shows_no_numbers():
    assert _format_stats_slots("live", "Score", NO_SCORE)[1] == ["-", "-", "0s"]
    assert _format_stats_slots("aggregate", "Score", NO_SCORE)[1] == ["-", "0s", "0s"]


def test_stats_view_mode_roundtrips_user_settings(tmp_path):
    """Saving and loading stats_view_mode via the Database API preserves the value."""
    from app.storage.database import DatabaseManager

    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path=db_path)
    uid = db.create_user("alice")
    db.set_user_setting(uid, "stats_view_mode", "aggregate")
    value = db.get_user_setting(uid, "stats_view_mode")
    assert value == "aggregate"
