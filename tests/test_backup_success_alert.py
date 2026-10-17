"""A finished backup must be announced in a dialog; the status line alone went unseen."""

from unittest.mock import MagicMock

import app.ui.backup_flow as bf
from app.ui.backup_flow import BACKUP_SOUND_NOTE
from tests._backup_flow import make_flow


def test_desktop_success_names_the_file_and_the_sound_note():
    flow = make_flow()
    flow._report_backup_saved("/home/u/eeg_backup_carl_2026-09-29_17-49.db")
    flow._settings_screen.show_backup_status.assert_called_once_with("Backup saved")
    title, body = flow._info.call_args.args
    assert title == "Backup saved"
    assert "/home/u/eeg_backup_carl_2026-09-29_17-49.db" in body
    assert BACKUP_SOUND_NOTE in body


def test_saf_success_pops_up_without_the_content_uri(monkeypatch):
    flow = make_flow()
    uri = "content://com.android.externalstorage.documents/document/primary%3ADownload%2Fx.db"
    monkeypatch.setattr(bf._backup, "online_backup_to_tempfile", lambda db: "/nonexistent/tmp.db")
    monkeypatch.setattr(bf._saf, "write_file_to_uri", lambda u, p: True)
    monkeypatch.setattr(bf.Clock, "schedule_once", lambda fn, *a: fn(0))
    flow._backup_to_uri_worker(uri)
    title, body = flow._info.call_args.args
    assert title == "Backup saved"
    assert uri not in body
    assert BACKUP_SOUND_NOTE in body


def test_saf_write_failure_is_reported_not_announced(monkeypatch):
    flow = make_flow()
    reported = []
    monkeypatch.setattr(bf._backup, "online_backup_to_tempfile", lambda db: "/nonexistent/tmp.db")
    monkeypatch.setattr(bf._saf, "write_file_to_uri", lambda u, p: False)
    monkeypatch.setattr(bf.Clock, "schedule_once", lambda fn, *a: fn(0))
    monkeypatch.setattr(bf, "report_soft_error", lambda label, detail, **k: reported.append(label))
    flow._backup_to_uri_worker("content://x")
    assert reported == ["backup_failed"]
    flow._info.assert_not_called()


def test_the_backup_is_named_for_the_active_profile_after_its_settings_are_saved(monkeypatch):
    order = []
    flow = make_flow(user_name=lambda: order.append("name") or "carl",
                     save_settings=MagicMock(side_effect=lambda: order.append("save")))
    monkeypatch.setattr(bf, "_on_android", lambda: False)
    flow._open_backup_save_picker = MagicMock()
    flow.on_backup_pressed()
    assert order == ["save", "name"]
    assert "carl" in flow._open_backup_save_picker.call_args.args[0]
