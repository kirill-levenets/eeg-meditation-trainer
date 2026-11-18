"""Missing custom sound files are reported once, together; two reports raced and the second was dropped."""
import pytest

import app.ui.sound_sources as sound_sources
from tests._sound_sources import sounds_alone


@pytest.fixture
def reports(monkeypatch) -> list[tuple]:
    said: list[tuple] = []
    monkeypatch.setattr(sound_sources, "report_soft_error", lambda label, detail="", **_: said.append((label, detail)))
    return said


def test_missing_feedback_file_and_gong_become_one_report(reports, tmp_path):
    sounds_alone().warn_missing({"custom": ("custom", str(tmp_path / "gone_rain.wav"))}, str(tmp_path / "gone_gong.wav"))
    assert len(reports) == 1
    label, detail = reports[0]
    assert label == "sound_files_missing"
    assert "gone_rain.wav" in detail and "gone_gong.wav" in detail


def test_present_files_report_nothing(reports, tmp_path):
    rain, gong = tmp_path / "rain.wav", tmp_path / "gong.wav"
    rain.write_bytes(b"x")
    gong.write_bytes(b"x")
    sounds_alone().warn_missing({"custom": ("custom", str(rain)), "noise": ("noise", "")}, str(gong))
    assert reports == []


def _gong_tester(path: str):
    return sounds_alone({"timer_sound": path})


def test_testing_a_missing_gong_warns_instead_of_silently_playing_the_default(reports, tmp_path):
    _gong_tester(str(tmp_path / "typo_gong.wav")).on_test_timer_sound()
    assert len(reports) == 1 and "typo_gong.wav" in reports[0][1]


def test_a_test_button_report_is_not_swallowed_by_an_earlier_session_start_report(monkeypatch, tmp_path):
    """Real report_soft_error: one label's 60 s cooldown must not hide what the user just asked to test."""
    import app.crash_handler as ch

    shown: list[str] = []

    def schedule(report, fatal):
        shown.append(report)
        ch._STATE["in_dialog"] = False  # the user closes it

    monkeypatch.setattr(ch, "_schedule_dialog", schedule)
    monkeypatch.setattr(ch, "_format_soft_report", lambda label, detail, app: detail)
    monkeypatch.setattr(ch, "_SOFT_ERROR_LAST", {})
    monkeypatch.setitem(ch._STATE, "in_dialog", False)

    sounds_alone().warn_missing({"custom": ("custom", str(tmp_path / "gone_rain.wav"))})  # session start
    _gong_tester(str(tmp_path / "typo_gong.wav")).on_test_timer_sound()  # seconds later: the user tests the gong

    assert len(shown) == 2 and "typo_gong.wav" in shown[1]
