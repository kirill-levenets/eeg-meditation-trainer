"""A finished backup must be announced in a dialog; the status line alone went unseen."""

from unittest.mock import MagicMock

import app.ui.app_manager as am
from app.ui.app_manager import _BACKUP_SOUND_NOTE, EEGMeditationApp


def _make_app():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._settings_screen = MagicMock()
    app._info_popup = MagicMock()
    return app


def test_desktop_success_names_the_file_and_the_sound_note():
    app = _make_app()
    app._report_backup_saved("/home/u/eeg_backup_carl_2026-09-29_17-49.db")
    app._settings_screen.show_backup_status.assert_called_once_with("Backup saved")
    title, body = app._info_popup.call_args.args
    assert title == "Backup saved"
    assert "/home/u/eeg_backup_carl_2026-09-29_17-49.db" in body
    assert _BACKUP_SOUND_NOTE in body


def test_saf_success_pops_up_without_the_content_uri(monkeypatch):
    app = _make_app()
    app._db = MagicMock()
    uri = "content://com.android.externalstorage.documents/document/primary%3ADownload%2Fx.db"
    monkeypatch.setattr(am._backup, "online_backup_to_tempfile", lambda db: "/nonexistent/tmp.db")
    monkeypatch.setattr(am._saf, "write_file_to_uri", lambda u, p: True)
    monkeypatch.setattr(am.Clock, "schedule_once", lambda fn, *a: fn(0))
    app._backup_to_uri_worker(uri)
    title, body = app._info_popup.call_args.args
    assert title == "Backup saved"
    assert uri not in body
    assert _BACKUP_SOUND_NOTE in body


def test_saf_write_failure_is_reported_not_announced(monkeypatch):
    app = _make_app()
    app._db = MagicMock()
    reported = []
    monkeypatch.setattr(am._backup, "online_backup_to_tempfile", lambda db: "/nonexistent/tmp.db")
    monkeypatch.setattr(am._saf, "write_file_to_uri", lambda u, p: False)
    monkeypatch.setattr(am.Clock, "schedule_once", lambda fn, *a: fn(0))
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    app._backup_to_uri_worker("content://x")
    assert reported == ["backup_failed"]
    app._info_popup.assert_not_called()
