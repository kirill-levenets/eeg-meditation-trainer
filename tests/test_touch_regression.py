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
