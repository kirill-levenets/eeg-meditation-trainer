"""A saved formula or program keeps a name no other has: saving under one that exists asks, then overwrites it in
place; a new name is added without asking."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.metrics.formula_slots import FormulaSlots
from app.storage.database import DatabaseManager
from tests._formula_settings import make_formula_settings
from tests._program_settings import make_programs


@pytest.fixture
def db(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    yield db
    db.close()


def _formulas(db, uid, confirm):
    app = SimpleNamespace(_db=db, _formulas=FormulaSlots(), _current_user_id=uid, _require_user=lambda _a: uid,
                          _audio_metric_key="shamatha_score", _confirm_action=confirm, _info_popup=MagicMock())
    settings = make_formula_settings(app)
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
