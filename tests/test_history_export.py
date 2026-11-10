"""History's exports through the flow on a real database: one session's CSV, and a selection as one ZIP off the main
thread behind the overlay, said where it went; an export with no data says so."""
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


def test_a_selection_is_exported_as_one_zip_and_said_where(exporting):
    flow, db, uid, reported = exporting
    ids = [_session(db, uid, 4, name, 100.0) for name in ("Morning sit", "Evening sit")]
    flow.on_export_sessions_csv(ids)
    flow._loading.show.assert_called_once()
    flow._loading.hide.assert_called_once()
    flow._history_screen.set_select_mode.assert_called_once_with(False)
    title, message = flow._ctx.info.call_args.args
    dest = message.split("to:\n")[1]
    assert title == "Export complete" and "2 sessions" in message and not reported
    with zipfile.ZipFile(dest) as z:
        assert len(z.namelist()) == 2


def test_a_selection_with_no_data_says_so(exporting, monkeypatch):
    flow, db, _uid, reported = exporting
    monkeypatch.setattr(db, "export_session_csv", lambda sid, custom_formula=None: "")
    flow.on_export_sessions_csv([7])
    assert reported == ["export_empty"]
    flow._loading.hide.assert_called_once()
    flow._ctx.info.assert_not_called()
    flow.on_export_sessions_csv([])  # nothing selected: nothing happens
    flow._loading.show.assert_called_once()
