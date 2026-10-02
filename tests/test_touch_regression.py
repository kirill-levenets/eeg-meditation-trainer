"""Touch-regression harness: catch 'dead zones' where a disabled, non-zero-size
widget covers an enabled interactive control. Kivy's Widget.on_touch_down does
`if self.disabled and self.collide_point(*touch.pos): return True` — it CONSUMES
the tap on a colliding disabled widget (unlike on_touch_up/on_touch_move, which
just ignore it). So any disabled widget overlapping a control's tap target makes
that control unclickable. Hidden interactive content must be DETACHED, never
collapse-in-place (height=0/opacity=0/disabled), or it eats neighbours' taps.
"""
from kivy.base import EventLoop
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.checkbox import CheckBox
from kivy.uix.textinput import TextInput

INTERACTIVE = (ButtonBehavior, CheckBox, TextInput)


def _pump(n=8):
    for _ in range(n):
        EventLoop.idle()


def _mount(widget):
    from kivy.core.window import Window
    EventLoop.ensure_window()
    Window.add_widget(widget)
    _pump()


def _unmount(widget):
    from kivy.core.window import Window
    Window.remove_widget(widget)


def _visible(w):
    return (w.get_root_window() is not None and w.opacity > 0
            and w.width > 0 and w.height > 0)


def find_dead_zones(root):
    """[(control, blocker), ...] — enabled visible interactive controls whose center
    is covered by a disabled, non-zero-size widget that isn't the control itself or
    a descendant of it."""
    controls = [w for w in root.walk()
                if isinstance(w, INTERACTIVE) and not w.disabled and _visible(w)]
    dead = []
    for c in controls:
        cx, cy = c.to_window(c.center_x, c.center_y)
        own = {id(x) for x in c.walk()}
        for other in root.walk():
            if id(other) in own or not getattr(other, "disabled", False):
                continue
            if other.width <= 0 or other.height <= 0:
                continue
            ox, oy = other.to_window(other.x, other.y)
            if ox <= cx <= ox + other.width and oy <= cy <= oy + other.height:
                dead.append((c, other))
                break
    return dead


def find_collapsed_disabled_with_children(root):
    """[widget, ...] — the touch-eating anti-pattern, geometry-independent: a `disabled`
    container hidden by collapse-in-place (height~0 or opacity 0) that STILL has
    interactive descendants attached. Because Kivy's on_touch_down consumes a colliding
    disabled widget, such a container eats taps on whatever it overlaps the moment its
    children fail to shrink to zero (device DPI, min line-height, etc.). The fix is to
    DETACH the children when hidden, not collapse-and-disable them."""
    from kivy.metrics import dp
    bad = []
    for w in root.walk():
        if not getattr(w, "disabled", False):
            continue
        collapsed = w.height < dp(5) or w.opacity < 0.01
        if not collapsed:
            continue
        if any(d is not w and isinstance(d, INTERACTIVE) for d in w.walk()):
            bad.append(w)
    return bad


def find_invisible_interactive(root):
    """[widget, ...] — enabled interactive widgets that are attached, have a real size, but are invisible (own or an
    ancestor's opacity ~0): Kivy still dispatches touches to them, so they take taps meant for what is drawn there."""
    bad = []
    for w in root.walk():
        if not isinstance(w, INTERACTIVE) or w.disabled or w.width <= 0 or w.height <= 0:
            continue
        node, invisible = w, False
        while node is not None and node is not root.parent:
            if node.opacity < 0.01:
                invisible = True
                break
            node = node.parent
        if invisible:
            bad.append(w)
    return bad


def _describe(dead):
    return "; ".join(
        f"{type(c).__name__}('{getattr(c, 'text', '')}') blocked by "
        f"disabled {type(b).__name__}" for c, b in dead)


def _settings_audio_open():
    from app.ui.settings_screen import SettingsScreen
    s = SettingsScreen()
    _mount(s)
    audio = next(x for x in s.walk() if type(x).__name__ == "_AccordionSection"
                 and x._header.text == "Audio")
    audio.open()
    _pump()
    return s


def test_audio_source_pickers_no_dead_zones():
    # Feedback/reward source selection is a picker button (opens a popup), not a
    # conditional custom RevealBox row, so there is no collapse-in-place anti-pattern.
    s = _settings_audio_open()
    try:
        for src, path in (("noise", ""), ("custom", "/tmp/x.wav"), ("heartbeat", "")):
            s.set_reward_source(src, path)
            _pump()
            assert not find_dead_zones(s), _describe(find_dead_zones(s))
        bad = find_collapsed_disabled_with_children(s)
        assert not bad, ("hidden-by-collapse disabled widgets still holding interactive "
                         "children (detach them instead): "
                         + ", ".join(type(w).__name__ for w in bad))
    finally:
        _unmount(s)


def test_hidden_session_end_card_leaves_no_invisible_buttons_and_start_stop_take_taps():
    # The hidden card used to stay attached at opacity 0 with fixed-size buttons on screen: Delete sat over Start and
    # OK over Stop, so Start/Stop responded to about one tap in ten.
    from kivy.tests.common import UnitTestTouch

    from app.ui.live_session import LiveSessionScreen
    screen = LiveSessionScreen()
    _mount(screen)
    try:
        assert find_invisible_interactive(screen) == []
        screen.show_summary(1, {"duration": 60})
        _pump()
        screen.hide_summary()
        _pump()
        assert find_invisible_interactive(screen) == []
        for btn in (screen._btn_start, screen._btn_stop):
            btn.disabled = False
            hits = []
            btn.bind(on_release=lambda *_a, b=btn: hits.append(b))
            x, y = btn.to_window(btn.center_x, btn.center_y)
            touch = UnitTestTouch(x, y)
            touch.touch_down()
            touch.touch_up()
            _pump(2)
            assert hits == [btn], f"a tap on {btn.text!r} did not reach it"
    finally:
        _unmount(screen)
