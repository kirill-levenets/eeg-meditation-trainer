"""Missing custom sound files are reported once, together; two reports raced and the second was dropped."""

from unittest.mock import MagicMock

import app.ui.app_manager as am
from app.ui.app_manager import EEGMeditationApp


def _make_app(monkeypatch):
    reports: list[tuple] = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail="", **_: reports.append((label, detail)))
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    return app, reports


def test_missing_feedback_file_and_gong_become_one_report(monkeypatch, tmp_path):
    app, reports = _make_app(monkeypatch)
    app._warn_missing_sound_files(
        {"custom": ("custom", str(tmp_path / "gone_rain.wav"))}, str(tmp_path / "gone_gong.wav"),
    )
    assert len(reports) == 1
    label, detail = reports[0]
    assert label == "sound_files_missing"
    assert "gone_rain.wav" in detail and "gone_gong.wav" in detail


def test_present_files_report_nothing(monkeypatch, tmp_path):
    app, reports = _make_app(monkeypatch)
    rain, gong = tmp_path / "rain.wav", tmp_path / "gong.wav"
    rain.write_bytes(b"x")
    gong.write_bytes(b"x")
    app._warn_missing_sound_files({"custom": ("custom", str(rain)), "noise": ("noise", "")}, str(gong))
    assert reports == []


def test_testing_a_missing_gong_warns_instead_of_silently_playing_the_default(monkeypatch, tmp_path):
    app, reports = _make_app(monkeypatch)
    app._timer_state = MagicMock(custom_sound_path=str(tmp_path / "typo_gong.wav"))
    app._audio = MagicMock()
    app._audio._bell_sound = None

    app._on_test_timer_sound()

    assert len(reports) == 1 and "typo_gong.wav" in reports[0][1]
