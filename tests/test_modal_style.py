"""Every modal window shares one themed style: popups, the session-end card, the connection and loading overlays,
the diagnostic dialog and toasts are drawn on the same panel, in the active theme, with readable text."""

import ast
import pathlib
import sys
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

from app.ui.theme import (
    _FG_DARK,
    _FG_LIGHT,
    THEMES,
    C,
    Card,
    ModalPanel,
    StyledButton,
    ThemedColor,
    ThemedLabel,
    ThemedPopup,
    _contrast,
    make_message_popup,
    make_scroll_popup,
)
from tests.test_theme_switch import _own_instructions, stale_colours


@pytest.fixture(autouse=True)
def _restore_theme():
    saved = C.theme_name
    yield
    C.set_theme(saved)


def _pump(n: int = 8) -> None:
    for _ in range(n):
        EventLoop.idle()


def _panel_roles(widget) -> list[str]:
    return [i.role for i in _own_instructions(widget.canvas.before) if isinstance(i, ThemedColor)]


def _frame(popup: Popup):
    return popup._container.parent


def _surface(w, panels) -> tuple:
    """The colour a label is drawn on: its button, card or input, else the modal panel it sits in."""
    node = w
    while node is not None:
        if isinstance(node, StyledButton):
            return tuple(node._get_bg())
        if isinstance(node, Card):
            return tuple(node.bg_color)
        if node in panels:
            return tuple(C.BG)
        node = node.parent
    raise AssertionError(f"{type(w).__name__}({getattr(w, 'text', '')!r}) is not inside a modal panel")


def unreadable_text(root, panels) -> list[str]:
    """Visible labels (and inputs) whose text has under 3:1 contrast with what is behind them."""
    bad = []
    for w in root.walk(restrict=True):
        if isinstance(w, TextInput):
            if _contrast(w.foreground_color, w.background_color) < 3:
                bad.append(f"input {w.text[:20]!r}")
            continue
        if not isinstance(w, Label) or not w.text.strip() or w.opacity == 0:
            continue
        color = w.disabled_color if w.disabled else w.color
        cr = _contrast(color, _surface(w, panels))
        if cr < 3:
            bad.append(f"{w.text[:24]!r} {cr:.1f}:1")
    return bad


def _popups():
    """One of each popup kind the app builds: a message, a list, and plain content."""
    msg = make_message_popup("Delete session", "Delete this session permanently? This can't be undone.",
                             [StyledButton(text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY),
                              StyledButton(text="Delete", bg_color=C.DANGER)])
    rows = [StyledButton(text=f"Series {i}", bg_color=C.BG_CARD, text_color=C.TEXT) for i in range(3)]
    lst = make_scroll_popup("Graph series", rows, footer=StyledButton(text="Done", bg_color=C.ACCENT))
    body = ModalPanel()  # any content: a themed label straight on the popup
    body.add_widget(ThemedLabel(text="Welcome! Create a profile or pick an existing one:", color=C.TEXT,
                                size_hint_y=None, height=dp(40)))
    plain = ThemedPopup(title="Select Profile", content=body, size_hint=(0.9, 0.6))
    return [msg, lst, plain]


@pytest.mark.parametrize("theme", list(THEMES))
def test_every_popup_is_the_themed_panel_with_readable_text(theme):
    C.set_theme(theme)
    for popup in _popups():
        popup.open()
        _pump()
        try:
            assert isinstance(popup, ThemedPopup)
            assert _panel_roles(_frame(popup)) == ["BG", "BORDER"]
            assert tuple(popup.overlay_color) == tuple(C.BG_OVERLAY)
            assert tuple(popup.title_color) == tuple(C.TEXT)
            assert not unreadable_text(popup, {_frame(popup)}), (popup.title, unreadable_text(popup, {_frame(popup)}))
        finally:
            popup.dismiss()
            _pump()


def test_an_open_popup_follows_a_theme_switch():
    C.set_theme("Light Cream")
    popup = _popups()[0]
    popup.open()
    _pump()
    try:
        C.set_theme("Dark Blue")
        _pump()
        assert not stale_colours(popup, "Light Cream", "Dark Blue")
    finally:
        popup.dismiss()
        _pump()


@pytest.mark.parametrize("theme", list(THEMES))
def test_the_in_screen_modals_are_the_same_panel_with_readable_text(theme):
    from app.ui.live_session import LiveSessionScreen
    from app.ui.widgets.loading_overlay import LoadingOverlay
    C.set_theme(theme)
    screen = LiveSessionScreen()
    loading = LoadingOverlay()
    Window.add_widget(screen)
    Window.add_widget(loading)
    try:
        screen.show_summary(1, {"duration": 600, "avg_shamatha": 55, "avg_meditation": 45})
        screen.show_overlay("Connecting to MindWave…")
        loading.show("Loading history…")
        _pump()
        for overlay in (screen._summary, screen._overlay, loading):
            panels = [w for w in overlay.walk(restrict=True) if isinstance(w, ModalPanel)]
            assert len(panels) == 1, type(overlay).__name__
            assert _panel_roles(panels[0]) == ["BG", "BORDER"]
            assert not unreadable_text(panels[0], set(panels)), unreadable_text(panels[0], set(panels))
        assert screen._summary_title.text == "Session saved"
        assert screen._summary_title.font_size == _frame(_popups()[0]).children[-1].font_size  # the popup title's
    finally:
        loading.hide()
        screen.hide_overlay()
        screen.hide_summary()
        Window.remove_widget(loading)
        Window.remove_widget(screen)


def test_the_session_end_card_fits_a_landscape_phone():
    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    Window.add_widget(screen)
    try:
        screen.show_summary(1, {"duration": 600})
        _pump()
        panel = next(w for w in screen._summary.walk(restrict=True) if isinstance(w, ModalPanel))
        pad = screen._summary.padding
        assert panel.height + pad[1] + pad[3] <= dp(390), panel.height
    finally:
        screen.hide_summary()
        Window.remove_widget(screen)


@pytest.mark.parametrize("theme", ["Light Cream", "Dark Blue"])
def test_the_diagnostic_dialog_is_the_themed_panel_with_readable_text(theme):
    from app.crash_handler import CrashDialog
    C.set_theme(theme)
    CrashDialog.show("report body\nline 2", app=None, fatal=False, title="Diagnostic report")
    popup = CrashDialog._popup
    _pump()
    try:
        assert isinstance(popup, ThemedPopup)
        assert not unreadable_text(popup, {_frame(popup)}), unreadable_text(popup, {_frame(popup)})
    finally:
        popup.dismiss()
        _pump()


def _toast_app():
    from app.ui.app_manager import EEGMeditationApp
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._android_toast = MagicMock()
    return app


@pytest.mark.parametrize("theme", ["Light Cream", "Dark Blue"])
def test_a_toast_is_the_themed_panel_above_any_popup(theme, monkeypatch):
    monkeypatch.setattr(sys, "getandroidapilevel", lambda: 30, raising=False)  # also on Android, while in the app
    C.set_theme(theme)
    popup = _popups()[0]
    popup.open()
    _pump()
    app = _toast_app()
    try:
        app._toast("Notes saved")
        toast = Window.children[0]  # the topmost window child: drawn over the open popup
        assert isinstance(toast, ThemedLabel) and toast.text == "Notes saved"
        assert _panel_roles(toast) == ["BG", "BORDER"]
        assert _contrast(toast.color, C.BG) >= 4.5
        app._android_toast.assert_not_called()
    finally:
        Window.remove_widget(Window.children[0])
        popup.dismiss()
        _pump()


def test_a_toast_raised_while_the_app_is_leaving_is_the_native_one(monkeypatch):
    monkeypatch.setattr(sys, "getandroidapilevel", lambda: 30, raising=False)
    app = _toast_app()
    before = list(Window.children)
    app._leaving = True
    app._toast("Notes saved")
    app._android_toast.assert_called_once_with("Notes saved")
    assert list(Window.children) == before


def _best_glyph_contrast(fill) -> float:
    return max(_contrast(_FG_DARK, fill), _contrast(_FG_LIGHT, fill))


@pytest.mark.parametrize("theme", list(THEMES))
def test_a_selected_button_glyph_is_auto_and_readable_on_its_fill(theme):
    # "Selected" is an accent fill with AUTO glyph colour (text_color=None); C.TEXT on a bright fill was 1.5-2:1.
    # AUTO is the better of the two glyphs; the palette's mid-tone fills cap that at ~3.9:1 (bold labels need 3:1).
    C.set_theme(theme)
    btn = StyledButton(text="Metrics", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY)
    for fill in (C.PRIMARY, C.ACCENT, C.PRIMARY_DIM, C.SHAMATHA):
        btn.bg_color = fill
        btn.text_color = None
        cr = _contrast(btn.text_color, fill)
        assert cr == pytest.approx(_best_glyph_contrast(fill)) and cr >= 3, fill.role
    btn.bg_color = C.BG_CARD
    assert _contrast(btn.text_color, C.BG_CARD) == pytest.approx(_best_glyph_contrast(C.BG_CARD))  # still AUTO
    btn.text_color = C.TEXT_SECONDARY
    btn.bg_color = C.PRIMARY
    assert tuple(btn.text_color) == tuple(C.TEXT_SECONDARY)  # an explicit colour stays


@pytest.mark.parametrize("theme", list(THEMES))
def test_the_app_selected_states_are_readable(theme):
    from app.ui.history_screen import HistoryScreen
    from app.ui.live_session import LiveSessionScreen
    from app.ui.settings_screen import SettingsScreen
    C.set_theme(theme)
    live, hist, sett = LiveSessionScreen(), HistoryScreen(), SettingsScreen()
    live._set_view("raw")
    live._set_view("metrics")
    hist.set_view_mode("bars")
    for btn in (live._btn_view_metrics, hist._btn_bars, sett._theme_buttons[theme]):
        assert _contrast(btn.text_color, btn.bg_color) == pytest.approx(_best_glyph_contrast(btn.bg_color)), btn.text


def test_a_popup_without_a_height_is_as_tall_as_its_content_capped():
    from kivy.uix.boxlayout import BoxLayout
    content = BoxLayout(orientation="vertical", size_hint_y=None)
    content.bind(minimum_height=content.setter("height"))
    content.add_widget(ThemedLabel(text="Welcome", size_hint_y=None, height=dp(48)))
    popup = ThemedPopup(title="Select Profile", content=content, size_hint=(0.9, None))
    popup.open()
    _pump()
    try:
        short = popup.height
        assert dp(48) < short < Window.height * 0.5  # no empty half-screen panel
        for _ in range(40):
            content.add_widget(ThemedLabel(text="row", size_hint_y=None, height=dp(48)))
        _pump()
        assert popup.height == pytest.approx(Window.height * 0.85)  # grows with it, capped
    finally:
        popup.dismiss()
        _pump()


_NEUTRAL = ("BG", "BG_CARD", "BG_INPUT", "BG_DARK")


def _accent_buttons_with_unreadable_text(root) -> list[str]:
    """Enabled filled buttons on a non-neutral fill whose glyph is not the more readable of the two (AUTO)."""
    neutral = {tuple(round(x, 3) for x in getattr(C, r)[:3]) for r in _NEUTRAL}
    bad = []
    for w in root.walk(restrict=True):
        if not isinstance(w, StyledButton) or w.disabled or w.outline or w.bg_color[3] == 0:
            continue
        fill = w._get_bg()
        if tuple(round(x, 3) for x in fill[:3]) in neutral:
            continue
        if _contrast(w.text_color, fill) < _best_glyph_contrast(fill) - 0.01:
            bad.append(f"{w.text or w.icon!r} {_contrast(w.text_color, fill):.1f}:1")
    return bad


@pytest.mark.parametrize("theme", list(THEMES))
def test_no_screen_draws_a_fixed_glyph_colour_on_an_accent_fill(theme):
    from app.ui.diary_screen import DiaryScreen
    from app.ui.history_screen import HistoryScreen
    from app.ui.live_session import LiveSessionScreen
    from app.ui.settings_screen import SettingsScreen
    from app.ui.wizard_screen import WizardScreen
    C.set_theme(theme)
    live, hist, diary, sett, wiz = LiveSessionScreen(), HistoryScreen(), DiaryScreen(), SettingsScreen(), WizardScreen()
    live._set_view("raw")
    live._set_view("metrics")
    hist.set_view_mode("bars")
    diary.populate_sessions([{"id": 1, "date_time": "2026-09-20T10:00:00", "duration": 600, "avg_shamatha": 55}])
    diary._switch_graph_tab("raw")
    sett.load_program([{"minutes": 10, "target": 50, "formula": "shamatha_score"}], "program")
    sections = [x for x in sett.walk(restrict=True) if type(x).__name__ == "_AccordionSection"]
    bad = []
    for sec in sections:
        sec.open()
        bad += _accent_buttons_with_unreadable_text(sett)
    sett.set_program_mode("simple")
    for root in (live, hist, diary, sett, wiz):
        bad += _accent_buttons_with_unreadable_text(root)
    assert not sorted(set(bad)), sorted(set(bad))


def test_a_selected_file_stays_readable(tmp_path):
    for name in ("a.db", "b.db"):
        (tmp_path / name).write_bytes(b"x")
    from kivy.tests.common import UnitTestTouch

    from app.ui.theme import ThemedFileChooser
    for theme in THEMES:
        C.set_theme(theme)
        chooser = ThemedFileChooser(path=str(tmp_path), filters=["*.db"], size_hint=(None, None), size=(600, 400))
        Window.add_widget(chooser)
        try:
            _pump()
            node = next(n for n in chooser.walk(restrict=True) if getattr(n, "path", "").endswith("a.db"))
            x, y = node.to_window(*node.center)
            touch = UnitTestTouch(x, y)
            touch.touch_down()
            touch.touch_up()
            _pump()
            assert node.is_selected
            tint = node.color_selected
            behind = [tint[i] * tint[3] + C.BG[i] * (1 - tint[3]) for i in range(3)] + [1]
            label = next(w for w in node.walk(restrict=True) if isinstance(w, Label) and w.text == "a.db")
            assert _contrast(label.color, behind) >= 4.5, theme
        finally:
            Window.remove_widget(chooser)


def test_the_diagnostic_dialog_falls_back_to_plain_widgets_if_the_themed_one_fails(monkeypatch):
    import app.ui.theme as theme_mod
    from app.crash_handler import _STATE, CrashDialog

    def broken(*_a, **_k):
        raise RuntimeError("theme broke")

    monkeypatch.setattr(theme_mod, "ThemedPopup", broken)
    CrashDialog.show("report body", app=None, fatal=False, title="Diagnostic report")
    popup = CrashDialog._popup
    _pump()
    try:
        assert isinstance(popup, Popup) and popup.title == "Diagnostic report"
        assert popup.get_root_window() is not None  # it is open
    finally:
        popup.dismiss()
        _pump()
        _STATE["in_dialog"] = False


def test_the_session_end_card_scrolls_rather_than_clipping_on_a_short_screen():
    from kivy.uix.scrollview import ScrollView

    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    Window.add_widget(screen)
    try:
        screen.show_summary(1, {"duration": 600})
        screen._summary.size_hint_y = None
        screen._summary.height = dp(280)  # a landscape phone minus the bottom nav, and less
        _pump()
        scroll = next(w for w in screen._summary.walk(restrict=True) if isinstance(w, ScrollView))
        pad = screen._summary.padding
        assert scroll.height <= dp(280) - pad[1] - pad[3] + 0.5
        panel = next(w for w in scroll.walk(restrict=True) if isinstance(w, ModalPanel))
        assert screen.summary_ok_btn in list(panel.walk(restrict=True))  # reachable by scrolling, not cut off
        screen._summary.height = Window.height
        _pump()
        assert scroll.height == pytest.approx(panel.height)  # room enough: no scrolling, the whole card
    finally:
        screen.hide_summary()
        Window.remove_widget(screen)


def test_the_connection_card_has_no_blank_slot_for_a_hidden_retry():
    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    Window.add_widget(screen)
    try:
        screen.show_overlay("Connecting…")
        _pump()
        assert screen._overlay_retry_btn.parent is None  # detached, not an invisible 44 dp slot
        screen.show_overlay_retry("Connection failed")
        _pump()
        assert screen._overlay_retry_btn.get_root_window() is not None
        screen.show_overlay("Connecting…")
        _pump()
        assert screen._overlay_retry_btn.parent is None
    finally:
        screen.hide_overlay()
        Window.remove_widget(screen)


def test_the_in_screen_modals_block_taps_on_the_screen_behind():
    from kivy.tests.common import UnitTestTouch

    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    Window.add_widget(screen)
    hits = []
    screen._btn_start.bind(on_release=lambda *_a: hits.append("start"))
    try:
        for show, hide in ((lambda: screen.show_summary(1, {"duration": 60}), screen.hide_summary),
                           (lambda: screen.show_overlay("Connecting…"), screen.hide_overlay)):
            show()
            _pump()
            x, y = screen._btn_start.to_window(*screen._btn_start.center)
            t = UnitTestTouch(x, y)
            t.touch_down()
            t.touch_up()
            _pump()
            assert hits == [], "a tap on the dim area reached Start"
            hide()
            _pump()
    finally:
        Window.remove_widget(screen)


def test_a_popup_given_no_size_keeps_kivys_full_size():
    content = ModalPanel()
    popup = ThemedPopup(title="x", content=content)
    assert tuple(popup.size_hint) == (1, 1) and not popup._fits_content


@pytest.mark.parametrize("theme", list(THEMES))
def test_the_export_result_message_is_readable(theme):
    from app.ui.diary_screen import DiaryScreen
    C.set_theme(theme)
    screen = DiaryScreen()
    for success in (True, False):
        screen._show_export_result("Saved to /tmp/session_1.csv" if success else "Export error:\nno space",
                                   success=success)
        popup = screen._export_result_popup
        _pump()
        try:
            assert not unreadable_text(popup, {_frame(popup)}), unreadable_text(popup, {_frame(popup)})
        finally:
            popup.dismiss()
            _pump()


@pytest.mark.parametrize("theme", list(THEMES))
def test_the_marker_hotkey_capture_state_is_readable(theme):
    from app.ui.settings_screen import SettingsScreen
    C.set_theme(theme)
    s = SettingsScreen()
    btn = s._marker_hotkey_btn
    s._on_marker_hotkey_pressed()
    try:
        assert _contrast(btn.text_color, btn.bg_color) == pytest.approx(_best_glyph_contrast(btn.bg_color))
    finally:
        s._on_hotkey_capture(Window, 109, 0, "m", [])
    assert tuple(btn.text_color) == tuple(C.PRIMARY)  # back to its resting colour


def test_the_session_end_card_opens_at_its_top():
    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    Window.add_widget(screen)
    try:
        screen.show_summary(1, {"duration": 600})
        screen._summary.size_hint_y = None
        screen._summary.height = dp(280)
        _pump()
        screen._summary_scroll.scroll_y = 0  # the user scrolled down to OK
        screen.hide_summary()
        screen.show_summary(2, {"duration": 60})
        _pump()
        assert screen._summary_scroll.scroll_y == 1
    finally:
        screen.hide_summary()
        Window.remove_widget(screen)


def test_a_hidden_scrim_takes_no_taps():
    from kivy.tests.common import UnitTestTouch

    from app.ui.theme import ModalScrim
    scrim = ModalScrim(size_hint=(None, None), size=(0, 0), pos=(0, 0))
    assert not scrim.on_touch_down(UnitTestTouch(0, 0))


def test_app_code_builds_popups_and_file_choosers_only_through_theme():
    # A plain Kivy Popup is the always-dark chrome; a plain FileChooserListView draws white names.
    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    plain = []
    for path in sorted(app_dir.rglob("*.py")):
        if path.name == "theme.py":
            continue
        source = path.read_text()
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module in ("kivy.uix.popup", "kivy.uix.filechooser"):
                if "# plain-ok:" in lines[node.lineno - 1]:  # a deliberate, reasoned exception
                    continue
                plain.append(f"{path.relative_to(app_dir)}:{node.lineno} imports from {node.module}")
    assert not plain, "use ThemedPopup / ThemedFileChooser from app.ui.theme: " + "; ".join(plain)
