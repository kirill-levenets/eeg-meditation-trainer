"""A runtime theme switch repaints everything: no widget or canvas keeps a colour from the old palette (#38)."""

import ast
import gc
import pathlib
import weakref

import pytest
from kivy.base import EventLoop
from kivy.graphics import Canvas, Color, InstructionGroup
from kivy.uix.widget import Widget

from app.ui.theme import (
    THEMES,
    BottomNav,
    C,
    Card,
    CenteredTextInput,
    Divider,
    IconLabel,
    PresetRow,
    SectionLabel,
    StyledButton,
    ThemedColor,
    ThemedLabel,
    ThemedTextInput,
)

PAIRS = [("Light Cream", "Dark Blue"), ("Dark Blue", "Light Cream"), ("Dark Green", "Light Green")]


@pytest.fixture(autouse=True)
def _restore_theme():
    saved = C.theme_name
    yield
    C.set_theme(saved)


def _pump(n: int = 6) -> None:
    for _ in range(n):
        EventLoop.idle()


def _rgb(value) -> tuple | None:
    try:
        if len(value) in (3, 4) and all(isinstance(x, (int, float)) for x in value):
            return tuple(round(float(x), 3) for x in value[:3])
    except TypeError:
        pass
    return None


def _stale_rgbs(old: str, new: str) -> dict:
    """rgb -> roles, for old-palette colours the switch changes (a value the new palette also uses can't be told apart)."""
    new_rgbs = {_rgb(v) for v in THEMES[new].values()}
    stale: dict = {}
    for role, value in THEMES[old].items():
        rgb = _rgb(value)
        if rgb != _rgb(THEMES[new][role]) and rgb not in new_rgbs:
            stale.setdefault(rgb, []).append(role)
    return stale


def _own_instructions(group):
    """The widget's own canvas instructions (before/after included), not its children's canvases."""
    for instr in getattr(group, "children", []):
        if isinstance(instr, Canvas):
            continue
        yield instr
        if isinstance(instr, InstructionGroup):
            yield from _own_instructions(instr)


def _describe(w: Widget) -> str:
    text = getattr(w, "text", "")
    return f"{type(w).__name__}({text[:24]!r})" if isinstance(text, str) and text else type(w).__name__


def stale_colours(root: Widget, old: str, new: str) -> list[str]:
    """Every colour property or canvas Color under root still holding a colour the switch from old to new changed."""
    stale = _stale_rgbs(old, new)
    found = []
    for w in root.walk():
        for name in w.properties():
            if "color" in name or name == "bg_pressed":
                rgb = _rgb(getattr(w, name))
                if rgb in stale:
                    found.append(f"{_describe(w)}.{name} = old {'/'.join(stale[rgb])}")
        for instr in _own_instructions(w.canvas):
            if isinstance(instr, Color) and _rgb(instr.rgba) in stale:
                found.append(f"{_describe(w)} canvas Color = old {'/'.join(stale[_rgb(instr.rgba)])}")
    return found


def _assert_repainted(root: Widget, old: str, new: str, state: str) -> None:
    _pump()
    found = stale_colours(root, old, new)
    assert not found, f"{old} -> {new}, {state}: {len(found)} stale: " + "; ".join(sorted(set(found))[:25])


def _mount(widget: Widget) -> None:
    from kivy.core.window import Window
    EventLoop.ensure_window()
    Window.add_widget(widget)
    _pump()


def _unmount(widget: Widget) -> None:
    from kivy.core.window import Window
    Window.remove_widget(widget)


# ---- the mechanism ----


def test_a_palette_colour_carries_its_role_and_list_makes_a_fixed_copy():
    C.set_theme("Dark Blue")
    assert C.BG_CARD == THEMES["Dark Blue"]["BG_CARD"]
    assert C.BG_CARD.role == "BG_CARD"
    assert not hasattr(list(C.BG_CARD), "role")


@pytest.mark.parametrize("make, prop, role", [
    (lambda: Card(bg_color=C.BG_CARD), "bg_color", "BG_CARD"),
    (lambda: Card(), "bg_color", "BG_CARD"),
    (lambda: Divider(), "color", "BORDER"),
    (lambda: SectionLabel(text="s"), "color", "TEXT_SECONDARY"),
    (lambda: IconLabel(icon="i"), "color", "TEXT_SECONDARY"),
    (lambda: ThemedLabel(text="l", color=C.TEXT_SECONDARY), "color", "TEXT_SECONDARY"),
    (lambda: ThemedTextInput(background_color=C.BG_INPUT), "background_color", "BG_INPUT"),
    (lambda: CenteredTextInput(foreground_color=C.TEXT), "foreground_color", "TEXT"),
    (lambda: StyledButton(text="b", bg_color=C.BG_CARD), "bg_color", "BG_CARD"),
    (lambda: StyledButton(text="b"), "bg_color", "PRIMARY"),
    (lambda: StyledButton(text="b", bg_color=C.BG_CARD, text_color=C.TEXT_MUTED), "text_color", "TEXT_MUTED"),
])
def test_a_widget_given_a_palette_colour_follows_the_switch(make, prop, role):
    C.set_theme("Light Cream")
    w = make()
    assert _rgb(getattr(w, prop)) == _rgb(THEMES["Light Cream"][role])
    C.set_theme("Dark Blue")
    assert _rgb(getattr(w, prop)) == _rgb(THEMES["Dark Blue"][role])


def test_a_literal_colour_stays_and_replacing_a_role_with_a_literal_drops_the_role():
    C.set_theme("Light Cream")
    fixed = ThemedLabel(text="x", color=(0.9, 0.1, 0.1, 1))
    later = ThemedLabel(text="y", color=C.TEXT)
    later.color = (0.2, 0.7, 0.2, 1)
    C.set_theme("Dark Blue")
    assert list(fixed.color) == [0.9, 0.1, 0.1, 1]
    assert list(later.color) == [0.2, 0.7, 0.2, 1]


def test_a_palette_colour_kept_from_before_a_switch_paints_the_current_palette():
    C.set_theme("Light Cream")
    kept = C.ACCENT  # e.g. a widget's stored "selected" colour, assigned on a later tap
    C.set_theme("Dark Blue")
    w = Card(bg_color=kept)
    assert _rgb(w.bg_color) == _rgb(THEMES["Dark Blue"]["ACCENT"])


def test_preset_row_buttons_follow_the_switch_selected_or_not():
    C.set_theme("Light Cream")
    row = PresetRow(values=[1, 2])
    row.set_selected(1)
    C.set_theme("Dark Blue")
    row.set_selected(2)
    assert _rgb(row._buttons[1].bg_color) == _rgb(THEMES["Dark Blue"]["BG_CARD"])
    assert _rgb(row._buttons[2].bg_color) == _rgb(THEMES["Dark Blue"]["ACCENT"])
    assert _rgb(row._buttons[1].text_color) == _rgb(THEMES["Dark Blue"]["TEXT_MUTED"])


def test_a_button_still_follows_the_switch_after_its_saved_flash():
    C.set_theme("Light Cream")
    btn = StyledButton(text="Save", bg_color=C.ACCENT)
    btn.flash_confirm("Saved", confirm_color=C.SHAMATHA)
    btn._end_confirm()
    C.set_theme("Dark Blue")
    assert _rgb(btn.bg_color) == _rgb(THEMES["Dark Blue"]["ACCENT"])


def test_an_auto_button_given_a_palette_text_colour_keeps_it_across_a_switch():
    C.set_theme("Dark Blue")
    btn = StyledButton(text="Metrics", bg_color=C.BG_CARD)  # AUTO glyph colour
    btn.text_color = C.TEXT_SECONDARY  # e.g. the inactive view toggle
    C.set_theme("Light Cream")
    assert _rgb(btn.text_color) == _rgb(THEMES["Light Cream"]["TEXT_SECONDARY"])
    assert _rgb(btn._label.color) == _rgb(THEMES["Light Cream"]["TEXT_SECONDARY"])


def test_a_button_with_a_fixed_fill_still_repaints_its_disabled_fill():
    C.set_theme("Light Cream")
    btn = StyledButton(text="x", bg_color=(0.5, 0.5, 0.5, 1), disabled=True)  # disabled fill is C.BG_CARD
    C.set_theme("Dark Blue")
    assert not stale_colours(btn, "Light Cream", "Dark Blue")


def test_a_graph_draws_a_series_colour_read_before_the_switch_in_the_current_palette():
    # Series colour dicts are module constants, read once at import in the default palette.
    from app.ui.raw_eeg_screen import ScrollableGraphWidget
    C.set_theme("Dark Blue")
    colors = {"warm": C.WARM}
    C.set_theme("Light Cream")
    g = ScrollableGraphWidget(colors=colors, scales={"warm": 100}, size=(400, 300), size_hint=(None, None))
    for i in range(5):
        g.add_point({"warm": 10.0 * i})
    g._redraw()
    want = _rgb(THEMES["Light Cream"]["WARM"])
    assert _rgb(g.series_color("warm")) == want
    assert want in {_rgb(i.rgba) for i in _own_instructions(g.canvas) if isinstance(i, Color)}
    assert _rgb(THEMES["Dark Blue"]["WARM"]) not in {_rgb(i.rgba) for i in _own_instructions(g.canvas)
                                                     if isinstance(i, Color)}


def test_a_canvas_colour_follows_the_switch_and_keeps_its_alpha():
    C.set_theme("Light Cream")
    w = Widget()
    with w.canvas.before:
        bg = ThemedColor(C.BG)
        overlay = ThemedColor(C.BG, alpha=0.4)
    C.set_theme("Dark Blue")
    assert _rgb(bg.rgba) == _rgb(THEMES["Dark Blue"]["BG"])
    assert _rgb(overlay.rgba) == _rgb(THEMES["Dark Blue"]["BG"])
    assert overlay.a == pytest.approx(0.4)


def test_applying_the_active_theme_again_repaints_nothing():
    # Every profile activation applies the profile's stored theme, usually the one already showing.
    calls = []

    class Spy:
        def fire(self):
            calls.append(C.theme_name)

    C.set_theme("Light Cream")
    spy = Spy()
    C.add_listener(spy.fire)
    C.set_theme("Light Cream")
    assert calls == []
    C.set_theme("Dark Blue")
    assert calls == ["Dark Blue"]


def test_theme_listeners_do_not_keep_widgets_alive():
    btn = StyledButton(text="gone")
    ref = weakref.ref(btn)
    del btn
    gc.collect()
    assert ref() is None


def test_a_plain_function_listener_is_registered_once_and_any_callable_is_accepted():
    calls = []

    def on_switch():
        calls.append(C.theme_name)

    C.set_theme("Dark Blue")
    C.add_listener(on_switch)
    C.add_listener(on_switch)
    C.add_listener("abc".upper)  # a builtin bound method can't be weakly referenced
    try:
        C.set_theme("Light Cream")
    finally:
        C._listeners.pop(on_switch, None)
        C._listeners.pop("abc".upper, None)
    assert calls == ["Light Cream"]


def test_dropped_widgets_leave_no_listeners_behind():
    gc.collect()
    before = len(C._listeners)
    for _ in range(50):
        StyledButton(text="row")
    gc.collect()
    assert len(C._listeners) <= before + 1


def test_a_widget_whose_repaint_raises_is_logged_and_the_rest_still_repaint(caplog):
    def boom(*_a):
        raise RuntimeError("binding broke")

    C.set_theme("Light Cream")
    broken = ThemedLabel(text="broken", color=C.TEXT)
    broken.bind(color=boom)
    fine = Card()
    try:
        C.set_theme("Dark Blue")
    finally:
        broken.unbind(color=boom)  # a failed assertion must not leave a widget that breaks every later switch
    assert "binding broke" in caplog.text
    assert _rgb(fine.bg_color) == _rgb(THEMES["Dark Blue"]["BG_CARD"])


def test_a_failing_listener_is_logged_and_the_rest_still_run(caplog):
    calls = []

    class Boom:
        def fire(self):
            raise RuntimeError("listener broke")

    class Ok:
        def fire(self):
            calls.append(C.theme_name)

    boom, ok = Boom(), Ok()
    C.add_listener(boom.fire)
    C.add_listener(ok.fire)
    try:
        C.set_theme("Light Green")
    finally:
        # The log record keeps the failing method (and so Boom) alive; drop it so later switches don't call it.
        for key in [k for k, get in C._listeners.items() if get() == boom.fire]:
            C._listeners.pop(key)
    assert calls == ["Light Green"]
    assert "listener broke" in caplog.text


def test_app_ui_takes_label_and_textinput_from_theme():
    # A plain Kivy Label/TextInput given C.X keeps that palette's RGBA after a switch.
    ui = pathlib.Path(__file__).resolve().parent.parent / "app" / "ui"
    plain = []
    for path in sorted(ui.rglob("*.py")):
        if path.name == "theme.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module in ("kivy.uix.label", "kivy.uix.textinput"):
                plain.append(f"{path.relative_to(ui)}:{node.lineno} imports from {node.module}")
    assert not plain, "use ThemedLabel / ThemedTextInput from app.ui.theme: " + "; ".join(plain)


# ---- the screens ----


def _history_sessions(n: int) -> list[dict]:
    return [
        {"id": i, "date_time": f"2026-09-{28 - i // 2:02d}T{10 + i % 2}:00:00", "duration": 1800,
         "avg_shamatha": 40 + i, "session_name": f"Session {i}"}
        for i in range(n)
    ]


def _drain_history(h) -> None:
    _pump()  # the list lays out its rows over the next frames


@pytest.mark.parametrize("old, new", PAIRS)
def test_live_session_screen_repaints(old, new):
    from app.ui.live_session import LiveSessionScreen
    C.set_theme(old)
    screen = LiveSessionScreen()
    _mount(screen)
    try:
        C.set_theme(new)
        _assert_repainted(screen, old, new, "idle")
        screen._toggle_stats_mode()
        _assert_repainted(screen, old, new, "stats card in the other mode")
        screen.show_overlay("Connecting...")
        _assert_repainted(screen, old, new, "connection overlay")
        screen.hide_overlay()
        screen.show_summary(1, {"duration": 60, "avg_shamatha": 50, "avg_meditation": 40})
        _assert_repainted(screen, old, new, "session-end card")
        screen.hide_summary()
        screen._set_view("raw")
        _assert_repainted(screen, old, new, "raw view")
    finally:
        _unmount(screen)


@pytest.mark.parametrize("old, new", PAIRS)
def test_history_screen_repaints_in_both_views_and_select_mode(old, new):
    from app.ui.history_screen import HistoryScreen
    C.set_theme(old)
    h = HistoryScreen()
    _mount(h)
    try:
        h.load_sessions(_history_sessions(8))
        _drain_history(h)
        C.set_theme(new)
        _assert_repainted(h, old, new, "calendar")
        h.set_view_mode("bars")
        _assert_repainted(h, old, new, "14-day bars")
        h.set_select_mode(True)
        _drain_history(h)
        _assert_repainted(h, old, new, "select mode")
    finally:
        _unmount(h)


@pytest.mark.parametrize("old, new", PAIRS)
def test_session_detail_repaints(old, new):
    from app.ui.diary_screen import DiaryScreen
    C.set_theme(old)
    screen = DiaryScreen()
    _mount(screen)
    try:
        screen.show_session_detail({"id": 1, "date_time": "2026-09-20T10:00:00", "duration": 600,
                                    "avg_shamatha": 55, "avg_meditation": 45, "session_name": "Morning",
                                    "notes": "calm"})
        screen.load_metrics_preview([
            {"meditation_score": 50, "shamatha_score": 30 + i, "distraction": 20, "sinking": 10,
             "delta_raw": 300, "theta_raw": 200, "alpha1_raw": 400, "alpha2_raw": 350,
             "beta1_raw": 100, "beta2_raw": 80, "gamma1_raw": 30, "gamma2_raw": 20}
            for i in range(10)
        ])
        screen.set_band_totals({"delta": 3.0, "theta": 2.0, "alpha1": 4.0, "alpha2": 3.5,
                                "beta1": 1.0, "beta2": 0.8, "gamma1": 0.3, "gamma2": 0.2})
        _pump()
        C.set_theme(new)
        _assert_repainted(screen, old, new, "metrics tab")
        for tab in ("raw", "freq"):
            screen._switch_graph_tab(tab)
            _assert_repainted(screen, old, new, f"{tab} tab")
    finally:
        _unmount(screen)


@pytest.mark.parametrize("old, new", PAIRS)
def test_settings_screen_repaints_every_section(old, new):
    from app.ui.settings_screen import SettingsScreen
    C.set_theme(old)
    s = SettingsScreen()
    _mount(s)
    segments = [{"minutes": 10, "target": 50, "formula": "shamatha_score"},
                {"minutes": 5, "target": 60, "formula": "meditation_score"}]
    s.load_program(segments, "program")
    s.set_saved_programs([{"name": "Ramp", "segments": segments}])
    s.set_program_mode("simple")  # the program editor is built, then detached
    try:
        C.set_theme(new)
        _assert_repainted(s, old, new, "all sections collapsed")
        sections = [x for x in s.walk() if type(x).__name__ == "_AccordionSection"]
        assert sections
        for sec in sections:
            sec.open()
            _assert_repainted(s, old, new, f"{sec._header.text} open")
        timer = next(sec for sec in sections if sec._header.text.startswith("Timer"))
        timer.open()
        s.set_program_mode("program")
        _assert_repainted(s, old, new, "Timer in Program mode, built before the switch")
    finally:
        _unmount(s)


@pytest.mark.parametrize("old, new", PAIRS)
def test_wizard_and_bottom_nav_repaint(old, new):
    from app.ui.wizard_screen import WizardScreen
    C.set_theme(old)
    wizard = WizardScreen()
    nav = BottomNav(tabs=[("Session", "session"), ("History", "history"), ("Settings", "settings")])
    _mount(wizard)
    _mount(nav)
    try:
        C.set_theme(new)
        _assert_repainted(wizard, old, new, "wizard")
        _assert_repainted(nav, old, new, "bottom nav")
        nav.active_tab = "history"
        _assert_repainted(nav, old, new, "bottom nav, another tab")
    finally:
        _unmount(nav)
        _unmount(wizard)


def test_the_theme_selector_shows_the_active_theme_however_it_was_applied():
    # A profile switch applies the profile's theme through the settings registry, not through the selector.
    from app.ui.settings_screen import SettingsScreen
    C.set_theme("Dark Blue")
    s = SettingsScreen()
    C.set_theme("Light Cream")
    selected = {name for name, btn in s._theme_buttons.items() if btn.bold}
    assert selected == {"Light Cream"}
    assert _rgb(s._theme_buttons["Light Cream"].bg_color) == _rgb(THEMES["Light Cream"]["PRIMARY"])
    assert _rgb(s._theme_buttons["Dark Blue"].bg_color) == _rgb(THEMES["Light Cream"]["BG_CARD"])
