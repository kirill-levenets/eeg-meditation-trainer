"""A widget's hooks: unset ones do nothing, wire() plugs handlers in by name and refuses a name that isn't a hook."""
import importlib
import pkgutil

import pytest
from kivy.event import EventDispatcher
from kivy.uix.boxlayout import BoxLayout

import app.ui as ui
from app.ui.hooks import Hook, is_wired, wire


class _Panel(BoxLayout):
    on_save = Hook()
    item_count = Hook(default=0)


def test_an_unset_hook_does_nothing_and_returns_its_default():
    panel = _Panel()
    assert panel.on_save("notes") is None
    assert panel.item_count() == 0
    assert not is_wired(panel, "on_save")


def test_wire_plugs_a_handler_in_and_the_widget_calls_it():
    panel, saved = _Panel(), []
    wire(panel, on_save=lambda text: saved.append(text) or True, item_count=lambda: 3)
    assert panel.on_save("notes") is True
    assert saved == ["notes"]
    assert panel.item_count() == 3
    assert is_wired(panel, "on_save")


def test_hooks_belong_to_one_widget():
    wired, bare = _Panel(), _Panel()
    wire(wired, item_count=lambda: 3)
    assert bare.item_count() == 0


def test_wiring_none_unsets_a_hook():
    panel = _Panel()
    wire(panel, item_count=lambda: 3)
    wire(panel, item_count=None)
    assert panel.item_count() == 0
    assert not is_wired(panel, "item_count")


def test_a_name_that_is_no_hook_fails_at_wiring_instead_of_never_firing():
    panel = _Panel()
    with pytest.raises(AttributeError, match=r"_Panel has no hook 'on_sav'"):
        wire(panel, on_sav=print)
    with pytest.raises(AttributeError, match=r"_Panel has no hook 'orientation'"):
        wire(panel, orientation=print)  # a Kivy property is no hook
    with pytest.raises(AttributeError):
        is_wired(panel, "on_sav")


def _clashes(cls: type) -> set[str]:
    """Hooks Kivy would call itself: `on_<property>` on a property change, or a registered event's name."""
    members = {name: v for k in reversed(cls.__mro__) for name, v in vars(k).items()}
    props = {name for name, v in members.items() if type(v).__name__.endswith("Property")}
    events = {e for k in cls.__mro__ for e in vars(k).get("__events__", ())}
    hooks = {name for name, v in members.items() if isinstance(v, Hook)}
    return {h for h in hooks if h in events or (h.startswith("on_") and h[3:] in props)}


def test_a_hook_kivy_would_call_itself_is_caught():
    class _Bad(BoxLayout):
        on_orientation = Hook()  # a property's change handler
        on_touch_down = Hook()  # a registered event

    class _Child(_Bad):
        pass

    assert _clashes(_Bad) == _clashes(_Child) == {"on_orientation", "on_touch_down"}


def test_a_falsy_handler_is_still_the_handler():
    class _Falsy:
        def __call__(self, text):
            return f"saved {text}"

        def __bool__(self):
            return False

    panel = _Panel()
    wire(panel, on_save=_Falsy())
    assert is_wired(panel, "on_save") and panel.on_save("notes") == "saved notes"


def test_no_widget_hook_shadows_a_kivy_property_handler():
    for mod in pkgutil.walk_packages(ui.__path__, "app.ui."):
        module = importlib.import_module(mod.name)
        for cls in vars(module).values():
            if isinstance(cls, type) and issubclass(cls, EventDispatcher) and cls.__module__ == module.__name__:
                assert not _clashes(cls), f"{cls.__name__}: {sorted(_clashes(cls))}"
