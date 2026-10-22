"""What may close a locked session: battery optimisation and the maker's power manager. The app explains and opens the
screens once at the first start and in Settings › Device; the user decides."""
import sys
import types
from unittest.mock import MagicMock

import pytest

import app.android_jni as android_jni
import app.ui.power_exemption as pe
from app.ui.power_exemption import PowerExemption, advice, maker_screen
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import StyledButton


class _Db:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    def get_setting(self, key):
        return self.settings.get(key)

    def set_setting(self, key, value):
        self.settings[key] = value


@pytest.fixture
def android(monkeypatch):
    """An Android phone whose battery state and maker the test sets."""
    phone = types.SimpleNamespace(exempt=False, maker="huawei")
    monkeypatch.setattr(sys, "getandroidapilevel", lambda: 29, raising=False)
    monkeypatch.setattr(pe, "ignores_battery_optimisation", lambda: phone.exempt)
    monkeypatch.setattr(pe, "manufacturer", lambda: phone.maker)
    return phone


@pytest.fixture
def popups(monkeypatch):
    shown = []

    def _popup(title, message, buttons, **_kwargs):
        popup = MagicMock()
        shown.append(types.SimpleNamespace(title=title, message=message, buttons=buttons, popup=popup))
        return popup

    monkeypatch.setattr(pe, "make_message_popup", _popup)
    return shown


def _power(db=None, section=None):
    return PowerExemption(db or _Db(), section or MagicMock(), toast=MagicMock(), main=lambda fn: fn())


@pytest.mark.parametrize(("exempt", "maker", "want"), [
    (False, "huawei", ["Battery", "App launch"]),
    (True, "honor", ["App launch"]),
    (True, "samsung", ["App info"]),
    (False, "google", ["Battery"]),
    (True, "google", []),
])
def test_the_advice_follows_what_the_phone_needs(exempt, maker, want):
    assert [line.split(":")[0] for line in advice(exempt, maker)] == want
    assert maker_screen(maker) == next((w for w in want if w != "Battery"), None)


def test_off_android_nothing_is_offered(monkeypatch, popups):
    monkeypatch.delattr(sys, "getandroidapilevel", raising=False)  # on_android() reads it
    db = _Db()
    _power(db).offer_once()
    assert popups == [] and db.settings == {}


def test_the_alert_shows_once_with_what_the_phone_needs(android, popups):
    db = _Db()
    power = _power(db)
    power.offer_once()
    assert len(popups) == 1
    shown = popups[0]
    assert [b.text for b in shown.buttons] == ["Battery", "App launch", "Close"]
    assert "Manage manually" in shown.message and "Settings › Device" in shown.message
    shown.popup.open.assert_called_once()
    power.offer_once()
    assert len(popups) == 1  # once: Settings keeps the same buttons
    assert db.settings[pe.SHOWN_KEY]


def test_a_phone_with_nothing_to_allow_gets_no_alert_and_keeps_it_for_later(android, popups):
    android.exempt, android.maker = True, "google"
    db = _Db()
    _power(db).offer_once()
    assert popups == [] and pe.SHOWN_KEY not in db.settings  # should the exemption go, the alert is still to come


def test_the_alerts_buttons_open_the_screens(android, popups, monkeypatch):
    power = _power()
    opened = []
    monkeypatch.setattr(power, "on_battery_settings", lambda: opened.append("battery"))
    monkeypatch.setattr(power, "on_maker_settings", lambda: opened.append("maker"))
    power.offer_once()
    battery, maker, close = popups[0].buttons
    battery.dispatch("on_release")
    maker.dispatch("on_release")
    assert opened == ["battery", "maker"]
    close.dispatch("on_release")
    popups[0].popup.dismiss.assert_called_once()


def test_battery_asks_androids_dialog_then_falls_back_to_the_list(android, monkeypatch):
    tried = []
    monkeypatch.setattr(pe, "settings_intent", lambda action, package=True: (action, package))
    monkeypatch.setattr(pe, "open_first", lambda intents, done: (tried.extend(intents), done(False)))
    power = _power()
    power.on_battery_settings()
    assert tried == [("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS", True),
                     ("android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS", False)]
    power._toast.assert_called_once()  # none opened: said so, not silence


@pytest.mark.parametrize(("maker", "screens"), [
    ("huawei", [*pe._APP_LAUNCH_SCREENS, "android.intent.action.POWER_USAGE_SUMMARY"]),  # EMUI 12 refuses the first two
    ("xiaomi", []),
])
def test_the_makers_screen_is_app_launch_on_huawei_and_app_info_after_it_or_elsewhere(android, monkeypatch, maker,
                                                                                    screens):
    android.maker = maker
    monkeypatch.setattr(pe, "component_intent", lambda package, cls: (package, cls))
    monkeypatch.setattr(pe, "settings_intent", lambda action, package=True: action)
    tried = []
    monkeypatch.setattr(pe, "open_first", lambda intents, done: tried.extend(intents))
    _power().on_maker_settings()
    assert tried == [*screens, "android.settings.APPLICATION_DETAILS_SETTINGS"]


def test_settings_device_shows_the_row_only_on_android_with_the_buttons_it_needs(android):
    screen = SettingsScreen()
    device = screen.device
    assert device._power_box.parent is None  # off Android refresh() never attaches it
    power = _power(section=device)
    power.refresh()
    content = device._diagnostics_btn.parent
    assert device._power_box.parent is content
    assert content.children.index(device._power_box) == content.children.index(device._diagnostics_btn) + 1  # above it
    assert "battery optimisation is on" in device._power_label.text
    assert [b.text for b in reversed(device._power_buttons.children)] == ["Battery", "App launch"]
    android.exempt, android.maker = True, "google"
    power.refresh()
    assert "off for this app" in device._power_label.text
    assert device._power_buttons.parent is None  # nothing to open: no empty row


def test_settings_device_buttons_reach_the_app(android):
    device = SettingsScreen().device
    calls = []
    device.on_battery_settings = lambda: calls.append("battery")
    device.on_maker_settings = lambda: calls.append("maker")
    _power(section=device).refresh()
    for button in device._power_buttons.children:
        assert isinstance(button, StyledButton)
        button.dispatch("on_release")
    assert sorted(calls) == ["battery", "maker"]


def test_the_app_offers_it_at_start_or_once_the_first_run_picks_a_profile(monkeypatch):
    import app.ui.app_manager as am
    app = am.EEGMeditationApp.__new__(am.EEGMeditationApp)
    app._power = MagicMock()
    monkeypatch.setattr(am, "flush_pre_app_errors", lambda: None)
    monkeypatch.setattr(am.render_stats, "start", lambda: None)
    scheduled = []
    monkeypatch.setattr(am.Clock, "schedule_once", lambda fn, _timeout=0: scheduled.append(fn))
    gated = [True]
    monkeypatch.setattr(app, "_gate_active", lambda: gated[0])
    app.on_start()
    assert scheduled == []  # the profile popup is up: not over it
    for attr in ("_bottom_nav", "_refresh_profile", "_sm", "_headset"):
        setattr(app, attr, MagicMock())
    app._finish_first_run("test")
    app._power.offer_once.assert_called_once()
    gated[0] = False
    app.on_start()
    scheduled[-1](0)
    assert app._power.offer_once.call_count == 2
    assert app._power.refresh.call_count == 2  # the Device row at every start


def test_the_rows_buttons_fit_their_row_at_the_largest_text_size(android):
    from app.ui.theme import TEXT_SIZES, F
    F.set_scale(max(scale for scale, _name in TEXT_SIZES))
    try:
        device = SettingsScreen().device
        _power(section=device).refresh()
        for button in device._power_buttons.children:
            assert button.height <= device._power_buttons.height  # a taller one runs into the text above it
    finally:
        F.set_scale(1.0)


def _fake_ui_thread(monkeypatch, activity):
    monkeypatch.setitem(sys.modules, "android", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "android.runnable", types.SimpleNamespace(run_on_ui_thread=lambda fn: fn))
    monkeypatch.setattr(android_jni, "activity", lambda: activity)


def test_a_screen_is_tried_by_opening_it_and_a_missing_one_falls_through(monkeypatch):
    # From Android 11 resolveActivity can't see other apps' screens, so only opening one tells.
    opened = []

    def start(intent):
        if intent.name != "app info":
            raise RuntimeError("ActivityNotFoundException")
        opened.append(intent.name)

    _fake_ui_thread(monkeypatch, types.SimpleNamespace(startActivity=start, getPackageManager=lambda: "pm"))

    def intent(name):  # resolveActivity returns null, as it does for another app's screen from Android 11
        return types.SimpleNamespace(name=name, getComponent=lambda: name, getAction=lambda: None,
                                     resolveActivity=lambda _pm: None)

    results = []
    android_jni.open_first([intent("app launch"), intent("app info")], results.append)
    assert opened == ["app info"] and results == [True]
    android_jni.open_first([intent("app launch")], results.append)
    assert results == [True, False]


def test_a_jni_failure_behind_a_button_says_so_instead_of_crashing(android, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("JavaException: no such class")

    monkeypatch.setattr(pe, "settings_intent", broken)
    monkeypatch.setattr(pe, "component_intent", broken)
    power = _power()
    power.on_battery_settings()
    power.on_maker_settings()
    assert power._toast.call_count == 2


def test_an_alert_that_fails_to_open_doesnt_take_the_app_down_and_comes_again(android, monkeypatch):
    tries = []

    def broken(*_args, **_kwargs):
        tries.append(1)
        raise RuntimeError("a widget error")

    monkeypatch.setattr(pe, "make_message_popup", broken)
    db = _Db()
    power = _power(db)
    power.offer_once()  # at start-up, from a Clock callback: raising here would crash every start
    assert pe.SHOWN_KEY not in db.settings
    power.offer_once()
    assert len(tries) == 2  # the next start tries again



def test_every_return_to_the_app_refreshes_the_row(monkeypatch):
    import app.ui.app_manager as am
    app = am.EEGMeditationApp.__new__(am.EEGMeditationApp)
    app._power = MagicMock()
    app._bottom_nav = MagicMock()
    app._current_user_id = 1
    scheduled = []
    monkeypatch.setattr(am.Clock, "schedule_once", lambda fn, _timeout=0: scheduled.append(fn))
    app.on_resume()
    app._power.refresh.assert_called_once()  # the user may have changed it in the phone's settings meanwhile
    assert scheduled  # and after the session's own UI refresh was queued


def test_without_the_activity_a_screen_says_it_couldnt_open(monkeypatch):
    def gone():
        raise RuntimeError("JavaException: no activity")

    monkeypatch.setitem(sys.modules, "android", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "android.runnable", types.SimpleNamespace(run_on_ui_thread=lambda fn: fn))
    monkeypatch.setattr(android_jni, "activity", gone)
    results = []
    android_jni.open_first(["any screen"], results.append)
    assert results == [False]  # so the button's toast still comes
