"""ChoiceToggle: every position shown, the chosen one filled; a tap on another chooses it, `show` only marks it."""

from app.ui.theme import C
from app.ui.widgets.choice_toggle import ChoiceToggle


def _toggle(chosen: list):
    return ChoiceToggle([("live", "LIVE"), ("aggregate", "AVG")], "live", chosen.append, button={})


def _filled(toggle) -> list[str]:
    return [k for k, btn in toggle.buttons.items() if list(btn.bg_color) == list(C.PRIMARY) and btn.bold]


def test_both_positions_are_shown_with_the_chosen_one_filled():
    toggle = _toggle([])
    assert [b.text for b in reversed(toggle.children)] == ["LIVE", "AVG"]
    assert _filled(toggle) == ["live"]
    assert list(toggle.buttons["aggregate"].text_color) == list(C.TEXT_SECONDARY)


def test_a_tap_on_the_other_position_chooses_it():
    chosen = []
    toggle = _toggle(chosen)
    toggle.buttons["aggregate"].dispatch("on_release")
    assert (chosen, toggle.chosen, _filled(toggle)) == (["aggregate"], "aggregate", ["aggregate"])


def test_a_tap_on_the_chosen_position_does_nothing():
    chosen = []
    _toggle(chosen).buttons["live"].dispatch("on_release")
    assert chosen == []


def test_show_marks_a_choice_made_elsewhere_without_calling_back():
    chosen = []
    toggle = _toggle(chosen)
    toggle.show("aggregate")
    assert (chosen, _filled(toggle)) == ([], ["aggregate"])
