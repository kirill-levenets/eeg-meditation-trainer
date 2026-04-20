from unittest.mock import MagicMock


def test_format_report_contains_required_sections():
    from app.crash_handler import _format_report

    app = MagicMock()
    app.session_manager = MagicMock()
    app.session_manager.state = "running"
    app.session_manager.stream_name = "Mock EEG"

    try:
        raise RuntimeError("synthetic-boom")
    except RuntimeError:
        import sys
        exc_type, exc_value, tb = sys.exc_info()

    report = _format_report(exc_type, exc_value, tb, source="main", app=app)

    assert "EEG Meditation Trainer crash report" in report
    assert "App:" in report
    assert "1.0.0" in report
    assert "Platform:" in report
    assert "Python:" in report
    assert "Kivy:" in report
    assert "Device:" in report
    assert "Mock EEG" in report
    assert "Session:" in report
    assert "running" in report
    assert "Source:" in report
    assert "main" in report
    assert "synthetic-boom" in report
    assert "Traceback" in report


def test_format_report_handles_missing_session_manager():
    from app.crash_handler import _format_report

    app = MagicMock()
    del app.session_manager  # simulate crash before manager is attached

    try:
        raise ValueError("early-boom")
    except ValueError:
        import sys
        exc_type, exc_value, tb = sys.exc_info()

    report = _format_report(exc_type, exc_value, tb, source="main", app=app)

    assert "unknown" in report.lower()
    assert "early-boom" in report
