"""The session detail's Band Power table folds away under its title's chevron, like Try another threshold; each profile
remembers it."""

from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch

from app.settings.registry import BOOL, Setting, SettingsStore
from app.ui.diary_screen import DiaryScreen
from app.ui.theme import Icons
from tests.test_session_detail_open import app, db  # noqa: F401  (fixtures)

TOTALS = {"delta": 4.0, "theta": 2.0, "alpha1": 1.0, "alpha2": 1.0, "beta1": 0.5, "beta2": 0.5, "gamma1": 0.2,
          "gamma2": 0.1}


def _frames(n: int = 3) -> None:
    for _ in range(n):
        EventLoop.idle()


def _shown(d: DiaryScreen) -> list:
    return list(reversed(d._detail_layout.children))


def test_folding_detaches_the_table_and_unfolding_puts_it_back_under_its_title():
    d = DiaryScreen()
    d.set_band_totals(TOTALS)
    d.set_band_collapsed(True)
    assert d.band_collapsed and d._band_holder.parent is None  # detached: nothing hidden in place takes taps
    assert d._btn_band_fold._icon_label.text == Icons.CHEVRON_RIGHT
    d.set_band_collapsed(False)
    shown = _shown(d)
    assert shown[shown.index(d._band_header) + 1] is d._band_holder
    assert d._btn_band_fold._icon_label.text == Icons.CHEVRON_DOWN


def test_totals_arriving_while_folded_show_on_unfolding():
    d = DiaryScreen()
    d.set_band_collapsed(True)
    d.set_band_totals(TOTALS)
    assert d._band_holder.parent is None
    d.set_band_collapsed(False)
    assert d._band_holder.children == [d._band_totals]


def test_a_tap_on_the_chevron_folds_it():
    d = DiaryScreen()
    d.set_band_totals(TOTALS)
    Window.add_widget(d)
    try:
        _frames(6)
        x, y = d._btn_band_fold.to_window(*d._btn_band_fold.center)
        touch = UnitTestTouch(x, y)
        touch.touch_down()
        _frames(1)
        touch.touch_up()
        _frames(3)
        assert d.band_collapsed
    finally:
        Window.remove_widget(d)


def test_the_folded_table_is_saved_per_profile(app):  # noqa: F811
    a, _workers = app
    store, me = a._db, a._current_user_id
    other = store.create_user("other")
    d = a._diary_screen
    a._loading_settings = False
    # As _build_settings_store declares it, and as build() wires the chevron.
    a._settings_store = SettingsStore(store, [Setting("band_power_collapsed", False, BOOL[0], BOOL[1],
                                                      lambda: d.band_collapsed, d.set_band_collapsed)])
    d.set_band_collapse_callback(lambda _c: a._persist_user_setting("band_power_collapsed"))
    d.toggle_band_collapsed()  # "me" folds it
    assert store.get_user_setting(me, "band_power_collapsed") == "True"
    a._settings_store.load(other)
    assert not d.band_collapsed  # the other profile's own state
    a._settings_store.load(me)
    assert d.band_collapsed

