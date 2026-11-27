"""History's exports through the flow on a real database: one session's CSV, to a folder or on to Documents, and a
selection as one ZIP off the main thread behind the overlay, said where it went; a copy delivered to Documents leaves no
private one behind, one that failed stays and is named; an export with no data says so."""
import csv
import io
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.history_flow as history_flow
from app.metrics.formula_slots import FormulaSlots
from app.storage import android_share
from app.storage.database import DatabaseManager
from app.ui.history_flow import HistoryFlow
from tests._context import stub_context
from tests.test_session_detail_open import _session


@pytest.fixture
def exporting(tmp_path, monkeypatch):
    """(flow, db, uid, reported): a HistoryFlow on a real database, its worker run in the call; the History screen, the
    overlay and the popup are stand-ins (`flow._history_screen`, `flow._loading`, `flow._ctx.info`)."""
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    uid = db.create_user("me")
    monkeypatch.setattr(history_flow, "threading", SimpleNamespace(Thread=lambda target, **k: SimpleNamespace(
        start=target)))  # the worker runs in the call
    monkeypatch.setattr(android_share, "copy_to_documents", lambda path, display_name: None)  # stays beside the DB
    reported = []
    monkeypatch.setattr(history_flow, "report_soft_error", lambda label, detail="", **_k: reported.append(label))
    flow = HistoryFlow(stub_context(db=db, user_id=lambda: uid, info=MagicMock()), MagicMock(), FormulaSlots(),
                       MagicMock(), on_sessions_deleted=MagicMock())
    try:
        yield flow, db, uid, reported
    finally:
        db.close()


def _export(flow, sid: int, folder) -> str:
    """The CSV the session's export wrote into `folder`, under its default name."""
    message, ok = flow.on_export_csv(sid, str(folder), "")
    assert ok, message
    return os.path.join(folder, f"session_{sid}.csv")


def test_a_sessions_csv_goes_to_the_folder_picked_under_the_name_typed(exporting, tmp_path):
    flow, db, uid, _reported = exporting
    sid = _session(db, uid, 4, "Morning sit", 100.0)
    folder = tmp_path / "picked" / "new"  # made if it isn't there
    assert flow.on_export_csv(sid, str(folder), "  morning ") == (f"File saved:\n{folder / 'morning.csv'}", True)
    with open(folder / "morning.csv") as f:
        assert len(f.read().splitlines()) > 4  # a header and the ticks
    flow.on_export_csv(sid, str(folder), "")
    assert (folder / f"session_{sid}.csv").exists()  # nothing typed: the session's own name


@pytest.mark.parametrize("delivered", [True, False])
def test_with_no_folder_it_goes_on_to_documents_and_leaves_no_private_copy(exporting, monkeypatch, delivered):
    flow, db, uid, _reported = exporting
    sid = _session(db, uid, 4, "Morning sit", 100.0)
    copied = {}

    def copy(path, display_name):
        copied[display_name] = open(path).read()
        return f"Documents/EEGMeditation/{display_name}" if delivered else None
    monkeypatch.setattr(android_share, "copy_to_documents", copy)
    message, ok = flow.on_export_csv(sid, None, "morning.csv")
    private = os.path.join(os.path.dirname(db._db_path), "exports", "morning.csv")
    assert len(copied["morning.csv"].splitlines()) > 4
    if delivered:
        assert (message, ok) == ("Saved to:\nDocuments/EEGMeditation/morning.csv\n\nVisible in file browser", True)
        assert not os.path.exists(private)
    else:  # kept, and named: no Share button to point to
        assert (message, ok) == (f"Couldn't copy it to Documents. It is kept in the app's storage:\n{private}", False)
        assert os.path.exists(private)


def test_an_export_that_fails_says_why(exporting, tmp_path, monkeypatch):
    flow, db, uid, _reported = exporting
    sid = _session(db, uid, 4, "Morning sit", 100.0)
    assert flow.on_export_csv(sid + 1, str(tmp_path), "") == ("No data to export", False)

    def denied(*_a, **_k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(history_flow, "write_file_atomic", denied)
    assert flow.on_export_csv(sid, str(tmp_path), "") == (f"Permission denied for:\n{tmp_path}\n\nTry a different "
                                                          "folder.", False)


def test_an_export_leaves_the_running_formulas_averages(exporting, tmp_path):
    # Slot 1's avg() is the running session's: an export computed its column through it, and the session went on
    # averaging the exported rows (a selection's export does it from its worker thread).
    flow, db, uid, _reported = exporting
    ev = flow._formulas.evaluators[0]
    ev.set_formula("avg(alpha1, 4)")
    for _ in range(4):
        ev.push_variables({"alpha1": 100.0})  # the running session's ticks
    flow.on_export_csv(_session(db, uid, 4, "Quiet sit", 0.0), str(tmp_path), "")
    ev.push_variables({"alpha1": 0.0})
    assert ev.evaluate({"alpha1": 0.0}) == pytest.approx(75.0)


def test_each_exported_session_averages_only_its_own_rows(exporting, tmp_path):
    flow, db, uid, _reported = exporting
    flow._formulas.evaluators[0].set_formula("avg(alpha1, 4)")
    _export(flow, _session(db, uid, 4, "Loud sit", 100.0), tmp_path)
    with open(_export(flow, _session(db, uid, 4, "Quiet sit", 0.0), tmp_path)) as f:
        first = next(csv.DictReader(f))
    assert float(first["custom_formula"]) == 0.0


def test_a_selection_is_exported_as_one_zip_and_said_where(exporting):
    flow, db, uid, reported = exporting
    flow._formulas.evaluators[0].set_formula("avg(alpha1, 4)")
    ids = [_session(db, uid, 4, name, power) for name, power in (("Loud sit", 100.0), ("Quiet sit", 0.0))]
    flow.on_export_sessions_csv(ids)
    flow._loading.show.assert_called_once()
    flow._loading.hide.assert_called_once()
    flow._history_screen.set_select_mode.assert_called_once_with(False)
    title, message = flow._ctx.info.call_args.args
    dest = message.split("to:\n")[1]
    assert title == "Export complete" and "2 sessions" in message and not reported
    with zipfile.ZipFile(dest) as z:
        assert len(z.namelist()) == 2
        firsts = [next(csv.DictReader(io.StringIO(z.read(f"session_{sid}.csv").decode()))) for sid in ids]
    assert [float(row["custom_formula"]) for row in firsts] == [100.0, 0.0]  # each session averages its own rows


def test_a_selection_with_no_data_says_so(exporting, monkeypatch):
    flow, db, _uid, reported = exporting
    monkeypatch.setattr(db, "export_session_csv", lambda sid, formula="": "")
    flow.on_export_sessions_csv([7])
    assert reported == ["export_empty"]
    flow._loading.hide.assert_called_once()
    flow._ctx.info.assert_not_called()
    flow.on_export_sessions_csv([])  # nothing selected: nothing happens
    flow._loading.show.assert_called_once()


def test_a_selection_delivered_to_documents_leaves_no_zip_in_app_storage(exporting, monkeypatch):
    flow, db, uid, reported = exporting
    monkeypatch.setattr(android_share, "copy_to_documents",
                        lambda path, display_name: f"Documents/EEGMeditation/{display_name}")
    flow.on_export_sessions_csv([_session(db, uid, 4, "Morning sit", 100.0)])
    _title, message = flow._ctx.info.call_args.args
    assert message.split("to:\n")[1].startswith("Documents/EEGMeditation/sessions_") and not reported
    assert not [f for f in os.listdir(os.path.dirname(db._db_path)) if f.endswith(".zip")]
