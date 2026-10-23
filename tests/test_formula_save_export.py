"""Settings › Custom Formula's Save (#102): a formula that doesn't compile isn't saved, since a program segment can pick
any saved formula."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.metrics.formula_slots import FormulaSlots
from app.storage.database import DatabaseManager
from tests._formula_settings import make_formula_settings


@pytest.fixture
def make(tmp_path):
    """A FormulaSettings on a fresh database, with a profile or without one; the database closes after the test."""
    dbs = []

    def build(*, profile=True):
        db = DatabaseManager(db_path=str(tmp_path / "t.db"))
        dbs.append(db)
        uid = db.create_user("A") if profile else None
        app = SimpleNamespace(_db=db, _formulas=FormulaSlots(), _current_user_id=uid,
                              _require_user=MagicMock(return_value=uid), _audio_metric_key="shamatha_score")
        return make_formula_settings(app), app, db, uid
    yield build
    for db in dbs:
        db.close()


def test_a_formula_that_doesnt_compile_isnt_saved(make):
    fs, _app, db, uid = make()
    fs.on_save(0, "Broken", "alpha1 +")
    assert db.get_saved_formulas(uid) == []  # a program segment could pick it: constant maximum noise
    status = fs._section.set_formula_slot_status.call_args
    assert status.args[1].startswith("Error:") and status.kwargs == {"is_error": True}


def test_a_formula_that_compiles_is_saved(make):
    fs, _app, db, uid = make()
    fs.on_save(0, "Alpha", "alpha1 * 2")
    assert db.get_saved_formulas(uid) == [{"name": "Alpha", "formula": "alpha1 * 2"}]
