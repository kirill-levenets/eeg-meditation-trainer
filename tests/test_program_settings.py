"""Settings › Timer's program and the Session screen's duration and program picks: what each tap changes and stores
for the profile, and what it asks first."""
from unittest.mock import MagicMock

import pytest

from app.storage.database import DatabaseManager
from tests._program_settings import make_programs

SEGMENTS = [{"minutes": 5, "target": 60, "formula": "shamatha_score"}]


@pytest.fixture
def db(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    yield db
    db.close()


@pytest.fixture
def uid(db):
    return db.create_user("me")


def _programs(db, uid):
    return make_programs(db, uid, timer_section=MagicMock(timer_enabled=False, timer_minutes=10))


def test_a_duration_tap_is_a_simple_timer_and_leaves_program_mode(db, uid):
    p = _programs(db, uid)
    p.on_mode_change("program")
    p.on_duration_preset(20)
    timer = p._timer_section
    assert (timer.timer_enabled, timer.timer_minutes, p.mode) == (True, 20, "simple")
    timer.set_program_mode.assert_called_with("simple")
    assert db.get_user_setting(uid, "timer_mode") == "simple"
    p._ctx.save_settings.assert_called_once()  # the timer's fields
    p.on_duration_preset(None)  # no limit
    assert timer.timer_enabled is False


def test_the_mode_and_the_edited_segments_come_back_with_the_profile(db, uid):
    p = _programs(db, uid)
    p.on_mode_change("program")
    p.on_changed(SEGMENTS)
    again = _programs(db, uid)
    again.load(uid)
    assert (again.mode, again.segments) == ("program", SEGMENTS)
    again._timer_section.load_program.assert_called_once_with(SEGMENTS, "program")


def test_a_program_needs_a_name_to_be_saved(db, uid):
    p = _programs(db, uid)
    p.segments = SEGMENTS
    p.on_save("   ")
    assert p._ctx.info.call_args.args[0] == "Name required" and db.get_saved_programs(uid) == []


def test_a_full_library_says_so_and_saves_nothing(db, uid):
    for i in range(db._MAX_SAVED_PROGRAMS):
        db.add_saved_program(uid, f"P{i}", SEGMENTS)
    p = _programs(db, uid)
    p.segments = SEGMENTS
    p.on_save("One more")
    assert p._ctx.info.call_args.args[0] == "Program library full"
    assert len(db.get_saved_programs(uid)) == db._MAX_SAVED_PROGRAMS and p.name == ""


def test_loading_a_program_asks_only_when_edits_would_be_lost(db, uid):
    db.add_saved_program(uid, "Morning", SEGMENTS)
    p = _programs(db, uid)
    p.on_load(0)  # nothing to lose: it loads at once
    assert (p.name, p.segments, p.mode) == ("Morning", SEGMENTS, "program")
    p._ctx.confirm.assert_not_called()
    p.on_changed([{"minutes": 9, "target": 70, "formula": "shamatha_score"}])  # an edit not saved
    p.on_load(0)
    assert p._ctx.confirm.call_args.args[0] == "Load program" and p.segments[0]["minutes"] == 9
    p._ctx.confirm.call_args.args[3]()  # Load
    assert p.segments == SEGMENTS
    p.on_load(5)  # a row gone meanwhile
    assert p._ctx.confirm.call_count == 1


def test_deleting_a_program_asks_with_its_name_then_deletes_it(db, uid):
    db.add_saved_program(uid, "Morning", SEGMENTS)
    db.add_saved_program(uid, "Evening", SEGMENTS)
    p = _programs(db, uid)
    p.on_delete(1)
    _title, message, ok_text, on_ok = p._ctx.confirm.call_args.args[:4]
    assert "'Evening'" in message and ok_text == "Delete"
    on_ok()
    assert [x["name"] for x in db.get_saved_programs(uid)] == ["Morning"]
    p.on_delete(3)  # an index the list no longer has asks nothing
    assert p._ctx.confirm.call_count == 1
