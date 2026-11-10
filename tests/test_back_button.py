"""Android hardware-back (key 27) handling: overlay close / navigate / double-exit."""
import time

import pytest
from kivy.core.window import Window
from kivy.uix.modalview import ModalView

import app.ui.app_manager as am
from tests._app import open_detail, saved_session


@pytest.fixture
def app(fresh_app, monkeypatch):
    """The app on its Session screen; `app.toasts` and `app.stops` record what a back press said and whether it
    exited."""
    app = fresh_app
    app.toasts, app.stops = [], []
    monkeypatch.setattr(am, "show_toast", app.toasts.append)
    monkeypatch.setattr(app, "stop", lambda: app.stops.append(True))
    return app


def _back(app, key: int = 27) -> bool:
    return app._on_keyboard(Window, key, 0, None, [])


def test_non_back_key_ignored(app):
    assert _back(app, key=97) is False  # 'a'
    assert app.toasts == []


def test_open_modal_not_intercepted(app):
    app._switch_screen("history")
    modal = ModalView()
    modal.open(animation=False)
    try:
        assert _back(app) is False  # let the popup dismiss itself
        assert app._sm.current == "history"
    finally:
        modal.dismiss(animation=False)


def test_fullscreen_overlay_closes(app):
    app._fullscreen.present(app._live_screen.graph)
    assert app._fullscreen.is_open
    assert _back(app) is True
    assert not app._fullscreen.is_open and app._sm.current == "live_session" and app.toasts == []


def test_diary_back(app):
    open_detail(app, saved_session(app))
    assert app._sm.current == "diary"
    assert _back(app) is True
    assert app._sm.current == "history"


@pytest.mark.parametrize("screen", ["history", "settings"])
def test_a_tab_navigates_to_session(app, screen):
    app._switch_screen(screen)
    assert _back(app) is True
    assert app._sm.current == "live_session" and app.toasts == [] and app.stops == []


def test_root_first_press_toasts_no_exit(app):
    assert _back(app) is True
    assert app.toasts == ["Press back again to exit"] and app.stops == []
    assert app._last_back_time > 0.0


def test_root_double_press_exits(app):
    assert _back(app) is True and _back(app) is True
    assert app.stops == [True] and app.toasts == ["Press back again to exit"]


def test_root_slow_second_press_does_not_exit(app):
    app._last_back_time = time.time() - 5.0  # the first press, more than 2 s ago
    assert _back(app) is True
    assert app.stops == [] and app.toasts == ["Press back again to exit"]
