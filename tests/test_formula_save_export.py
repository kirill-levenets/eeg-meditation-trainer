"""Settings › Custom Formula's Save and Export (#102): a formula that doesn't compile isn't saved, Export reaches the
Documents folder and says so in a popup, and both ask for a profile as Load and Delete do."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.metrics.formula_slots import FormulaSlots
from app.storage.database import DatabaseManager
from app.ui import formula_settings
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
                              _require_user=MagicMock(return_value=uid), _audio_metric_key="shamatha_score",
                              _confirm_action=MagicMock(), _info_popup=MagicMock())
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


@pytest.mark.parametrize("action, call", [("save a formula", lambda fs: fs.on_save(0, "A", "alpha1")),
                                          ("export formulas", lambda fs: fs.on_export())])
def test_save_and_export_without_a_profile_ask_for_one_as_load_and_delete_do(make, action, call):
    fs, app, _db, _uid = make(profile=False)
    call(fs)
    app._require_user.assert_called_once_with(action)
    fs._section.set_formula_slot_status.assert_not_called()  # the popup says it, not a slot's status line


def test_export_delivers_to_documents_and_leaves_no_private_copy(make, tmp_path, monkeypatch):
    fs, app, db, uid = make()
    db.add_saved_formula(uid, "Alpha", "alpha1 * 2")
    delivered = {}

    def deliver(path, display_name=""):
        delivered[display_name] = open(path, encoding="utf-8").read()
        return f"Documents/EEGMeditation/{display_name}"
    monkeypatch.setattr(formula_settings, "copy_to_documents", deliver)
    fs.on_export()
    name = f"formulas_user_{uid}.txt"
    assert delivered == {name: "alpha1 * 2\n"}
    assert not os.path.exists(tmp_path / name)  # the private copy is gone once it's delivered
    # A popup, not slot 1's status line: it is far from the button, and clipped at the larger text sizes.
    app._info_popup.assert_called_once_with("Export complete",
                                            f"Exported 1 formula to:\nDocuments/EEGMeditation/{name}")


def test_an_export_with_nothing_saved_says_so_in_a_popup(make):
    fs, app, _db, _uid = make()
    fs.on_export()
    assert app._info_popup.call_args.args[0] == "Nothing to export"


@pytest.mark.parametrize("failure, why", [("write", "No space left on device"), ("deliver", "see the log")])
def test_an_export_that_fails_says_so_and_why(make, tmp_path, monkeypatch, failure, why):
    fs, app, db, uid = make()
    db.add_saved_formula(uid, "Alpha", "alpha1")
    reports = []
    monkeypatch.setattr(formula_settings, "report_soft_error",
                        lambda label, detail, **kw: reports.append((label, detail)))
    if failure == "write":
        def no_space(*_a, **_kw):
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(formula_settings, "open", no_space, raising=False)
    monkeypatch.setattr(formula_settings, "copy_to_documents", lambda *a, **kw: None)
    fs.on_export()  # must not raise out of the button's handler
    assert [label for label, _ in reports] == ["formula_export_failed"]
    assert why in reports[0][1]
    app._info_popup.assert_not_called()
    assert not os.path.exists(tmp_path / f"formulas_user_{uid}.txt")  # nothing left in app storage either
