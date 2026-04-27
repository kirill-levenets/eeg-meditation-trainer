from unittest.mock import MagicMock


class _FakeRealStream:
    def __init__(self, name: str) -> None:
        self._device_name = name


class _FakeSessionManager:
    def __init__(self, state_name: str = "RUNNING") -> None:
        # Mimic enum with .name
        state = MagicMock()
        state.name = state_name
        self.state = state


class _FakeApp:
    """Minimal app stub matching EEGMeditationApp's attribute surface."""
    def __init__(self, session_state: str = "RUNNING", device_name: str = "MindWave Mobile 2") -> None:
        self._session_manager = _FakeSessionManager(session_state)
        self._real_stream = _FakeRealStream(device_name)


def test_format_report_contains_required_sections():
    from app.config import APP, APP_VERSION
    from app.crash_handler import _format_report

    APP.USE_MOCK_DEVICE = False  # force real path
    app = _FakeApp(session_state="RUNNING", device_name="MindWave Mobile 2")

    try:
        raise RuntimeError("synthetic-boom")
    except RuntimeError:
        import sys
        exc_type, exc_value, tb = sys.exc_info()

    report = _format_report(exc_type, exc_value, tb, source="main", app=app)

    assert "EEG Meditation Trainer crash report" in report
    assert "App:" in report
    assert APP_VERSION in report
    assert "Platform:" in report
    assert "Python:" in report
    assert "Kivy:" in report
    assert "Device:" in report
    assert "MindWave Mobile 2" in report  # now proven, not MagicMock trickery
    assert "Session:" in report
    assert "RUNNING" in report  # enum .name handling
    assert "Source:" in report
    assert "main" in report
    assert "synthetic-boom" in report
    assert "Traceback" in report


def test_format_report_mock_mode_shows_mock_eeg():
    from app.config import APP
    from app.crash_handler import _format_report

    original = APP.USE_MOCK_DEVICE
    APP.USE_MOCK_DEVICE = True
    try:
        app = _FakeApp(session_state="IDLE")

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys
            exc_type, exc_value, tb = sys.exc_info()

        report = _format_report(exc_type, exc_value, tb, source="main", app=app)
        assert "Mock EEG" in report
        assert "IDLE" in report
    finally:
        APP.USE_MOCK_DEVICE = original


def test_format_report_handles_missing_session_manager():
    """Crash before any app state is attached."""
    from app.crash_handler import _format_report

    app = MagicMock(spec=[])  # empty spec — no attributes defined

    try:
        raise ValueError("early-boom")
    except ValueError:
        import sys
        exc_type, exc_value, tb = sys.exc_info()

    report = _format_report(exc_type, exc_value, tb, source="main", app=app)

    assert "unknown" in report.lower()
    assert "early-boom" in report


def test_reentrance_guard_prevents_second_dialog(monkeypatch):
    import app.crash_handler as ch

    scheduled = []
    monkeypatch.setattr(ch, "_schedule_dialog", lambda report: scheduled.append(report))

    ch._STATE["in_dialog"] = False
    try:
        raise RuntimeError("first")
    except RuntimeError:
        t, v, tb = __import__("sys").exc_info()
    ch._handle_exception(t, v, tb, source="main", app=MagicMock())
    assert len(scheduled) == 1

    try:
        raise RuntimeError("second")
    except RuntimeError:
        t2, v2, tb2 = __import__("sys").exc_info()
    ch._handle_exception(t2, v2, tb2, source="main", app=MagicMock())
    assert len(scheduled) == 1  # second call blocked


def test_report_soft_error_schedules_dialog_with_label(monkeypatch):
    """First call with a fresh label must schedule a non-fatal dialog."""
    import app.crash_handler as ch

    scheduled = []
    monkeypatch.setattr(
        ch, "_schedule_dialog",
        lambda report, fatal=True, title="": scheduled.append((report, fatal)),
    )
    ch._STATE["in_dialog"] = False
    ch._SOFT_ERROR_LAST.clear()

    app = _FakeApp(session_state="RUNNING", device_name="MindWave Mobile 2")
    ok = ch.report_soft_error("bt_connect_failed", "errno 16", app=app)
    try:
        assert ok is True
        assert len(scheduled) == 1
        report, fatal = scheduled[0]
        assert fatal is False
        assert "diagnostic report" in report.lower()
        assert "soft:bt_connect_failed" in report
        assert "errno 16" in report
        assert "MindWave Mobile 2" in report
    finally:
        ch._STATE["in_dialog"] = False


def test_report_soft_error_cooldown_suppresses_repeats(monkeypatch):
    """Same label inside the cooldown window must NOT pop a second dialog."""
    import app.crash_handler as ch

    scheduled = []
    monkeypatch.setattr(
        ch, "_schedule_dialog",
        lambda report, fatal=True, title="": scheduled.append(report),
    )
    ch._STATE["in_dialog"] = False
    ch._SOFT_ERROR_LAST.clear()

    app = _FakeApp()
    assert ch.report_soft_error("bt_connect_failed", "first", app=app) is True
    ch._STATE["in_dialog"] = False  # simulate dialog dismissed
    assert ch.report_soft_error("bt_connect_failed", "second", app=app) is False
    assert len(scheduled) == 1


def test_report_soft_error_force_bypasses_cooldown(monkeypatch):
    """User-initiated 'Copy Diagnostics' must always pop, even on re-tap."""
    import app.crash_handler as ch

    scheduled = []
    monkeypatch.setattr(
        ch, "_schedule_dialog",
        lambda report, fatal=True, title="": scheduled.append(report),
    )
    ch._STATE["in_dialog"] = False
    ch._SOFT_ERROR_LAST.clear()

    app = _FakeApp()
    ch.report_soft_error("user_diagnostics", "first", app=app)
    ch._STATE["in_dialog"] = False
    ch.report_soft_error("user_diagnostics", "second", app=app, force=True)
    assert len(scheduled) == 2


def test_report_soft_error_blocked_during_active_dialog(monkeypatch):
    """If a (fatal) crash dialog is up, soft errors must not interrupt it."""
    import app.crash_handler as ch

    scheduled = []
    monkeypatch.setattr(
        ch, "_schedule_dialog",
        lambda report, fatal=True, title="": scheduled.append(report),
    )
    ch._STATE["in_dialog"] = True  # a crash dialog is currently up
    ch._SOFT_ERROR_LAST.clear()

    app = _FakeApp()
    try:
        assert ch.report_soft_error("anything", "noise", app=app) is False
        assert scheduled == []
    finally:
        ch._STATE["in_dialog"] = False


def test_install_sets_all_three_hooks(monkeypatch):
    import sys
    import threading

    import app.crash_handler as ch

    original_sys = sys.excepthook
    original_thr = threading.excepthook

    app = MagicMock()
    ch.install_crash_handler(app)

    assert sys.excepthook is not original_sys
    assert threading.excepthook is not original_thr

    # Kivy ExceptionManager handler — our wrapper must be registered
    from kivy.base import ExceptionManager
    assert any(
        isinstance(h, ch._KivyExceptionHandler) for h in ExceptionManager.handlers
    )

    # Cleanup so later tests aren't polluted
    sys.excepthook = original_sys
    threading.excepthook = original_thr
    ExceptionManager.handlers[:] = [
        h for h in ExceptionManager.handlers if not isinstance(h, ch._KivyExceptionHandler)
    ]
