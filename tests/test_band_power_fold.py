"""The session detail's Band Power table folds away under its title's chevron, like Try another threshold; each profile
remembers it."""

from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch

from app.ui.diary_screen import DiaryScreen
from app.ui.theme import Icons
from tests.test_session_detail_open import app  # noqa: F401  (fixture)

TOTALS = {"delta": 4.0, "theta": 2.0, "alpha1": 1.0, "alpha2": 1.0, "beta1": 0.5, "beta2": 0.5, "gamma1": 0.2,
          "gamma2": 0.1}


def _frames(n: int = 3) -> None:
    for _ in range(n):
        EventLoop.idle()


def _shown(d: DiaryScreen) -> list:
    return list(reversed(d.bands._header.parent.children))


def test_folding_detaches_the_table_and_unfolding_puts_it_back_under_its_title():
    d = DiaryScreen()
    d.bands.show_totals(TOTALS)
    d.bands.set_collapsed(True)
    assert d.bands.collapsed and d.bands._holder.parent is None  # detached: nothing hidden in place takes taps
    assert d.bands.chevron._icon_label.text == Icons.CHEVRON_RIGHT
    d.bands.set_collapsed(False)
    shown = _shown(d)
    assert shown[shown.index(d.bands._header) + 1] is d.bands._holder
    assert d.bands.chevron._icon_label.text == Icons.CHEVRON_DOWN


def test_totals_arriving_while_folded_show_on_unfolding():
    d = DiaryScreen()
    d.bands.set_collapsed(True)
    d.bands.show_totals(TOTALS)
    assert d.bands._holder.parent is None
    d.bands.set_collapsed(False)
    assert d.bands._holder.children == [d.bands.totals]


def test_a_tap_on_the_chevron_folds_it():
    d = DiaryScreen()
    d.bands.show_totals(TOTALS)
    Window.add_widget(d)
    try:
        _frames(6)
        x, y = d.bands.chevron.to_window(*d.bands.chevron.center)
        touch = UnitTestTouch(x, y)
        touch.touch_down()
        _frames(1)
        touch.touch_up()
        _frames(3)
        assert d.bands.collapsed
    finally:
        Window.remove_widget(d)


def test_the_folded_table_is_saved_per_profile(app):  # noqa: F811
    a, _workers = app
    me, d = a._current_user_id, a._diary_screen
    other = a._db.create_user("other")
    a._db.set_user_setting(other, "use_mock", "True")
    assert not d.bands.collapsed
    d.bands.chevron.dispatch("on_release")  # "me" folds it
    assert d.bands.collapsed and a._db.get_user_setting(me, "band_power_collapsed") == "True"
    a._profiles.on_switch(other)
    assert not d.bands.collapsed  # the other profile's own state
    a._profiles.on_switch(me)
    assert d.bands.collapsed


def test_the_tables_view_is_saved_per_profile_and_shown_on_the_next_open(app):  # noqa: F811
    a, workers = app
    me, d = a._current_user_id, a._diary_screen
    a._detail.on_session_select(a.sessions["A"])
    header = next(w for w in d.bands.totals.walk() if type(w).__name__ == "_HeaderCell" and w.text.startswith("Power"))
    header.dispatch("on_release")  # sort by power, largest first
    assert a._db.get_user_json_setting(me, "band_breakdown_view") == {"mode": "detailed", "sort": "power", "desc": True}
    d.bands.set_view_state("grouped", "band", False)  # another view shown meanwhile
    a._detail.on_session_select(a.sessions["B"])
    assert (d.bands.totals._mode, d.bands.totals._sort_by, d.bands.totals._descending) == ("detailed", "power", True)
