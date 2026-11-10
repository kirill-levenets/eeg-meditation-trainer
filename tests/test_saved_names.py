"""A saved formula or program keeps a name no other has: saving under one that exists asks, then overwrites it in
place; a new name is added without asking."""

import pytest

from app.storage.database import DatabaseManager
from tests._formula_settings import make_formula_settings
from tests._program_settings import make_programs


@pytest.fixture
def db(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    yield db
    db.close()


def _formulas(db, uid, confirm):
    settings = make_formula_settings(db, uid, confirm=confirm)
    return (lambda name, body: settings.on_save(0, name, body)), (lambda: db.get_saved_formulas(uid)), "formula"


def _programs(db, uid, confirm):
    programs = make_programs(db, uid, confirm=confirm)

    def save(name, body):
        programs.segments = [{"minutes": 1, "target": 50, "formula": body}]
        programs.on_save(name)
    return save, (lambda: db.get_saved_programs(uid)), "segments"


@pytest.mark.parametrize("library, kind, bodies", [
    (_formulas, "formula", ("alpha1", "theta", "alpha2")),
    (_programs, "program", ("shamatha_score", "meditation_score", "native_attention")),
], ids=["formula", "program"])
def test_saving_under_a_name_that_exists_asks_then_overwrites_it_in_place(db, library, kind, bodies):
    uid = db.create_user("A")
    asked = []
    save, saved, field = library(db, uid, lambda title, message, ok_text, on_ok, **kw: asked.append((title, on_ok)))
    first, second, new = bodies
    save("Calm", first)
    save("Deep", second)
    assert asked == []  # new names are added without asking
    save("Calm", new)
    assert [title for title, _ in asked] == [f"Overwrite {kind}"]
    assert [entry["name"] for entry in saved()] == ["Calm", "Deep"]  # nothing written before the answer
    asked[0][1]()  # Overwrite
    assert [entry["name"] for entry in saved()] == ["Calm", "Deep"]  # in place, still one "Calm"
    assert new in str(saved()[0][field])


def test_an_overwrite_of_an_entry_gone_meanwhile_writes_nothing_and_claims_nothing(db):
    uid = db.create_user("A")
    asked = []
    settings = make_formula_settings(db, uid, confirm=lambda title, message, ok_text, on_ok, **kw: asked.append(on_ok))
    settings.on_save(0, "Calm", "alpha1")
    settings.on_save(0, "Calm", "alpha2")
    db.remove_saved_formula(uid, 0)
    settings._section.reset_mock()
    asked[0]()  # Overwrite, its index now past the list's end
    assert db.get_saved_formulas(uid) == []
    settings._section.set_formula_slot_status.assert_not_called()  # no "Formula saved" for a write that didn't happen
