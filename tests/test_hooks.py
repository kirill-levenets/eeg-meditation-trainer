"""A widget's hooks: unset ones do nothing, wire() plugs handlers in by name and refuses a name that isn't a hook."""
import pytest
from kivy.uix.boxlayout import BoxLayout

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
