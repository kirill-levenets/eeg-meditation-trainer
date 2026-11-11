"""History's exports through the flow on a real database: one session's CSV, and a selection as one ZIP off the main
thread behind the overlay, said where it went; an export with no data says so."""
import csv
import io
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.ui.history_flow as history_flow
from app.metrics.formula_slots import FormulaSlots
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
    monkeypatch.setattr(history_flow, "copy_to_documents", lambda path, display_name: None)  # stays beside the DB
    reported = []
    monkeypatch.setattr(history_flow, "report_soft_error", lambda label, detail="", **_k: reported.append(label))
    flow = HistoryFlow(stub_context(db=db, user_id=lambda: uid, info=MagicMock()), MagicMock(), FormulaSlots(),
                       MagicMock(), on_sessions_deleted=MagicMock())
    try:
        yield flow, db, uid, reported
    finally:
        db.close()


def test_a_sessions_csv_is_written_beside_the_database(exporting):
    flow, db, uid, _reported = exporting
    sid = _session(db, uid, 4, "Morning sit", 100.0)
    path = flow.on_export_csv(sid)
    assert path == os.path.join(os.path.dirname(db._db_path), f"session_{sid}.csv")
    with open(path) as f:
        assert len(f.read().splitlines()) > 4  # a header and the ticks


def test_an_export_leaves_the_running_formulas_averages(exporting):
    # Slot 1's avg() is the running session's: an export computed its column through it, and the session went on
    # averaging the exported rows (a selection's export does it from its worker thread).
    flow, db, uid, _reported = exporting
    ev = flow._formulas.evaluators[0]
    ev.set_formula("avg(alpha1, 4)")
    for _ in range(4):
        ev.push_variables({"alpha1": 100.0})  # the running session's ticks
    flow.on_export_csv(_session(db, uid, 4, "Quiet sit", 0.0))
    ev.push_variables({"alpha1": 0.0})
    assert ev.evaluate({"alpha1": 0.0}) == pytest.approx(75.0)


def test_each_exported_session_averages_only_its_own_rows(exporting):
    flow, db, uid, _reported = exporting
    flow._formulas.evaluators[0].set_formula("avg(alpha1, 4)")
    flow.on_export_csv(_session(db, uid, 4, "Loud sit", 100.0))
    with open(flow.on_export_csv(_session(db, uid, 4, "Quiet sit", 0.0))) as f:
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
