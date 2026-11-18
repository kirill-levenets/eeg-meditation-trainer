"""A profile's headset is its own (#99): a profile load selects the one it saved, or none, closing a link to another
profile's, and a real-mode profile without one scans for it. One scan path serves a profile load, a new profile and
Start; a result that arrives after the profile, its headset or its mode changed, or after a session started, does
nothing. Only Start opens Settings → Device to pick among several."""

from unittest.mock import MagicMock

import pytest

import app.ui.headset as headset_module
from app.config import APP
from app.eeg.neurosky_stream import NeuroSkyStream
from app.session.session_run import Phase
from app.ui.headset import Headset
from tests._app import popups
from tests._context import stub_context
from tests._headset import fake_paired

BLUE = "00:11:22:33:44:01"
GREY = "00:11:22:33:44:02"
SPEAKER = {"name": "JBL Flip", "address": "00:11:22:33:44:09"}


def _mindwave(address: str) -> dict:
    return {"name": "MindWave Mobile", "address": address}


@pytest.fixture
def paired(monkeypatch):
    return fake_paired(monkeypatch)


@pytest.fixture
def app(fresh_app, paired, monkeypatch):
    """The app with the phone's paired devices faked (`paired`) and a reader that starts without Bluetooth, so a
    connect stays in its wait."""
    a = fresh_app

    def reader_started() -> bool:
        a._real_stream._running = True
        return True

    monkeypatch.setattr(a._real_stream, "start", reader_started)
    yield a
    a._db.set_json_setting("bt_device_aliases", {})  # the phone's, not a profile's: gone for the next test
    a._headset.load_aliases()


def _headset_alone(**ctx_fields) -> tuple[Headset, object]:
    """A Headset on a stub context, with its Settings device section a mock; (headset, device section)."""
    device = MagicMock()
    ctx = stub_context(user_id=lambda: 1, **ctx_fields)
    return Headset(ctx, MagicMock(_device_address=None), device, MagicMock(), serial_override=lambda: None), device


def test_the_mode_checkbox_changes_the_held_setting_and_writes_nothing_itself(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    changed, ctx_db = MagicMock(), MagicMock()
    hs, _device = _headset_alone(change_setting=changed, db=ctx_db, setting=lambda key: True)
    hs.on_mode_toggle(False)
    changed.assert_called_once_with("use_mock", False)
    ctx_db.set_user_setting.assert_not_called()


def test_a_mode_change_while_a_session_runs_is_refused_and_the_checkbox_put_back(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    changed = MagicMock()
    refused = MagicMock(side_effect=[True, False])  # a second ask would be let through: the put-back must not ask
    hs, device = _headset_alone(change_setting=changed, refused=refused, setting=lambda key: True)
    hs.on_mode_toggle(False)
    changed.assert_not_called()
    assert device._device_mode_cb.active is True
    hs.on_mode_toggle(True)  # the checkbox put back fires the hook with the mode in force: nothing happens
    changed.assert_not_called()
    device.update_device_status.assert_not_called()
    assert refused.call_count == 1


def test_the_hook_compares_with_the_held_mode_not_the_applied_flag(monkeypatch):
    # The store holds the value before its apply writes the flag and the checkbox: the hook must read the store.
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    changed = MagicMock()
    hs, _device = _headset_alone(change_setting=changed, setting=lambda key: True)
    hs.on_mode_toggle(True)
    changed.assert_not_called()


def test_picking_the_saved_headset_during_a_mock_session_is_refused_as_a_whole(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    refused = MagicMock(return_value=True)
    hs, device = _headset_alone(refused=refused)
    hs.stream._device_address = "00:11"
    hs.on_select("00:11", "MindWave Mobile")  # the same address: a pick that only changes the mode
    refused.assert_called_once_with("switching headsets")
    hs.stream.set_device.assert_not_called()
    device.clear_picker_banner.assert_not_called()


def _profile(app, name: str, saved: str | None = None) -> int:
    uid = app._db.create_user(name)
    if saved:
        app._db.set_user_setting(uid, "bt_device_address", saved)
        app._db.set_user_setting(uid, "bt_device_name", "MindWave Mobile")
    return uid


def _load(app, uid: int, *, mock: bool = False) -> None:
    """The profile picked, in the mode it stored: the settings load applies the mode, then Headset.load runs."""
    app._db.set_user_setting(uid, "use_mock", str(mock))
    app._activate_user(uid)


def _saved(app, uid: int) -> str | None:
    return app._db.get_user_setting(uid, "bt_device_address")


def _listed(app) -> set[str]:
    return set(app._settings_screen.device._bt_devices)


def _shown(app) -> str:
    """The headset as the Session screen names it."""
    return app._live_screen._device_label.text


def _connecting(app) -> bool:
    """Whether a Start went through to the headset's connect."""
    return app._session.run is not None and app._session.run.phase is Phase.CONNECTING


# ---- a profile load ----


def test_a_profile_without_a_headset_never_shows_another_profiles(app, paired):
    """The issue's example: A has headset X saved, B has none; after a switch to B nothing names X as B's."""
    a, b = _profile(app, "A", saved=BLUE), _profile(app, "B")
    _load(app, a)
    assert app._real_stream._device_address == BLUE
    _load(app, b)
    paired.arrive()  # nothing paired
    assert app._real_stream._device_address is None
    assert app._headset.state() == (None, None)
    assert app._headset.name() == "Real EEG" and _shown(app) == "[Real EEG]"
    assert app._settings_screen.device._device_meta_label.text == "Mode: Real Device"
    assert _saved(app, b) is None


def test_with_one_mindwave_paired_a_profile_gets_it_saved_and_a_restart_agrees(app, paired):
    paired.devices.append(_mindwave(BLUE))
    b = _profile(app, "B")
    _load(app, b)
    paired.arrive()
    assert app._real_stream._device_address == BLUE
    assert _saved(app, b) == BLUE
    assert _listed(app) == {BLUE}
    app._real_stream.set_device(None)  # the next launch
    _load(app, b)
    assert not paired.queued  # its saved headset: no scan
    assert app._real_stream._device_address == BLUE


def test_with_several_mindwaves_a_load_lists_them_and_leaves_the_pick_to_start(app, paired):
    paired.devices.extend([_mindwave(BLUE), _mindwave(GREY), SPEAKER])
    b = _profile(app, "B")
    _load(app, b)
    paired.arrive()
    assert app._real_stream._device_address is None
    assert _listed(app) == {BLUE, GREY}
    assert app._sm.current == "live_session"
    assert app._settings_screen.device._device_picker_banner.text == ""


def test_with_no_mindwave_a_load_lists_every_paired_device(app, paired):
    paired.devices.append(SPEAKER)
    _load(app, _profile(app, "B"))
    paired.arrive()
    assert app._real_stream._device_address is None
    assert _listed(app) == {SPEAKER["address"]}


def test_a_mock_profile_does_not_scan(app, paired):
    paired.devices.append(_mindwave(BLUE))
    b = _profile(app, "B")
    _load(app, b, mock=True)
    assert not paired.queued
    assert APP.USE_MOCK_DEVICE is True
    assert app._real_stream._device_address is None and _shown(app) == "[Mock EEG]"


def test_the_serial_override_keeps_its_device(app, paired, monkeypatch):
    monkeypatch.setattr(app, "serial_device_override", "/tmp/mindwave_b")
    app._real_stream.set_device("/tmp/mindwave_b", "Splitter (/tmp/mindwave_b)")  # as build() applies it
    _load(app, _profile(app, "B"))
    assert not paired.queued
    assert app._real_stream._device_address == "/tmp/mindwave_b"


def test_re_picking_the_running_sessions_profile_keeps_its_headset(app, paired):
    """Allowed mid-session, and it reloads the profile's settings: the session's link and its label stay."""
    b = _profile(app, "B")
    _load(app, b)
    paired.arrive()  # nothing paired
    app._real_stream.set_device(BLUE, "MindWave Mobile")  # its session's headset, its save to the profile lost
    app._on_start()
    assert _connecting(app)
    shown = _shown(app)
    _load(app, b)
    assert app._real_stream._device_address == BLUE
    assert not paired.queued and _shown(app) == shown


# ---- a scan result that comes too late ----


def test_a_scan_for_the_last_profile_does_nothing_for_the_next(app, paired):
    paired.devices.append(_mindwave(BLUE))
    b, c = _profile(app, "B"), _profile(app, "C", saved=GREY)
    _load(app, b)
    _load(app, c)  # B's scan still running
    paired.arrive()
    assert app._real_stream._device_address == GREY
    assert _saved(app, b) is None and _saved(app, c) == GREY


def test_a_new_profiles_scan_leaves_the_next_mock_profile_alone(app, paired):
    """The mode doesn't change between two profiles on the mock: only the load ends the first one's scan."""
    paired.devices.append(_mindwave(BLUE))
    b, c = _profile(app, "B"), _profile(app, "C")
    _load(app, b, mock=True)
    app._headset.scan_for_new_profile()
    _load(app, c, mock=True)  # B's scan still running
    paired.arrive()
    assert APP.USE_MOCK_DEVICE is True
    assert app._real_stream._device_address is None
    assert _saved(app, b) is None and _saved(app, c) is None


def test_a_scan_result_after_a_session_started_does_nothing(app, paired):
    """A Start right after launch: the result neither switches the headset nor refuses with "Session in progress"."""
    paired.devices.append(_mindwave(BLUE))
    _load(app, _profile(app, "New"), mock=True)
    app._headset.scan_for_new_profile()  # still running
    app._on_start()  # on the mock: the session runs at once
    assert app._session.live()
    paired.arrive()
    assert app._real_stream._device_address is None and APP.USE_MOCK_DEVICE is True
    assert popups() == [] and app._sm.current == "live_session"


def test_a_scan_result_after_a_pick_keeps_the_pick_and_the_list_it_came_from(app, paired):
    brainlink = {"name": "BrainLink Pro", "address": GREY}  # a TGAM headset the MindWave filter doesn't take
    paired.devices.extend([_mindwave(BLUE), brainlink])
    b = _profile(app, "B")
    app._headset.list_devices(list(paired.devices))  # an earlier Scan's list, still on screen
    _load(app, b)
    app._headset.on_select(GREY, "BrainLink Pro")  # picked from it while the load's scan ran
    paired.arrive()
    assert app._real_stream._device_address == GREY
    assert _saved(app, b) == GREY
    assert _listed(app) == {BLUE, GREY}


def test_a_scan_result_after_a_switch_to_the_mock_keeps_the_mock(app, paired):
    paired.devices.append(_mindwave(BLUE))
    b = _profile(app, "B")
    _load(app, b)
    app._settings_screen.device._device_mode_cb.active = True  # ticked while the scan ran
    paired.arrive()
    assert APP.USE_MOCK_DEVICE is True
    assert app._real_stream._device_address is None


# ---- a new profile ----


def _new_profile(app, paired) -> int:
    """As the first run makes one: saved on the mock, loaded, then scanned for."""
    uid = _profile(app, "New")
    app._db.set_user_setting(uid, "use_mock", "True")
    _load(app, uid, mock=True)
    app._headset.scan_for_new_profile()
    paired.arrive()
    return uid


def test_a_new_profile_takes_the_one_paired_mindwave(app, paired):
    paired.devices.append(_mindwave(BLUE))
    uid = _new_profile(app, paired)
    assert APP.USE_MOCK_DEVICE is False
    assert app._real_stream._device_address == BLUE
    assert _saved(app, uid) == BLUE and app._db.get_user_setting(uid, "use_mock") == "False"


def test_a_new_profile_with_several_mindwaves_leaves_the_mock_for_start_to_ask(app, paired):
    paired.devices.extend([_mindwave(BLUE), _mindwave(GREY)])
    uid = _new_profile(app, paired)
    assert APP.USE_MOCK_DEVICE is False and app._db.get_user_setting(uid, "use_mock") == "False"
    assert app._real_stream._device_address is None
    assert _listed(app) == {BLUE, GREY}
    assert app._sm.current == "live_session"


def test_a_new_profile_with_no_mindwave_stays_on_the_mock(app, paired):
    paired.devices.append(SPEAKER)
    uid = _new_profile(app, paired)
    assert APP.USE_MOCK_DEVICE is True and app._db.get_user_setting(uid, "use_mock") == "True"


# ---- Start ----


def test_start_with_several_mindwaves_asks_which_in_settings(app, paired):
    paired.devices.extend([_mindwave(BLUE), _mindwave(GREY)])
    _load(app, _profile(app, "B"))
    paired.arrive()
    app._on_start()
    paired.arrive()
    assert not _connecting(app) and app._sm.current == "settings"
    assert app._settings_screen.device._device_picker_banner.text.startswith("Found 2 MindWave devices.")
    assert not app._live_screen._btn_start.disabled  # the idle controls: Start can be pressed again


@pytest.mark.parametrize("answer", ["pick", "another profile", "Mock Data"])
def test_starts_pick_one_prompt_goes_once_answered(app, paired, answer):
    paired.devices.extend([_mindwave(BLUE), _mindwave(GREY)])
    _load(app, _profile(app, "B"))
    paired.arrive()
    app._on_start()
    paired.arrive()
    banner = app._settings_screen.device._device_picker_banner
    assert banner.text
    if answer == "pick":
        app._headset.on_select(GREY, "MindWave Mobile")
    elif answer == "Mock Data":
        app._settings_screen.device._device_mode_cb.active = True
    else:
        _load(app, _profile(app, "C", saved=BLUE))
    assert banner.text == ""


def test_start_with_one_mindwave_selects_it_for_the_profile_and_connects(app, paired):
    b = _profile(app, "B")
    _load(app, b)
    paired.arrive()  # nothing paired yet
    paired.devices.append(_mindwave(BLUE))  # paired before Start
    app._on_start()
    paired.arrive()
    assert _connecting(app)
    assert app._real_stream._device_address == BLUE and _saved(app, b) == BLUE


def test_a_headset_picked_while_start_scans_is_the_one_it_connects_to(app, paired):
    b = _profile(app, "B")
    _load(app, b)
    paired.arrive()
    paired.devices.append(_mindwave(BLUE))
    app._on_start()
    app._headset.on_select(GREY, "MindWave Mobile")  # picked in Settings while Start scanned
    paired.arrive()
    assert _connecting(app)
    assert app._real_stream._device_address == GREY and _saved(app, b) == GREY


def _raise():
    raise OSError("Bluetooth is off")


@pytest.mark.parametrize("devices, message", [
    ([SPEAKER], "No MindWave found among paired devices."),
    ([], "No paired Bluetooth devices found."),
    (_raise, "No paired Bluetooth devices found."),  # a listing that fails finds nothing, never a stuck overlay
])
def test_start_with_no_mindwave_paired_says_why(app, paired, monkeypatch, devices, message):
    _load(app, _profile(app, "B"))
    paired.arrive()
    if callable(devices):
        monkeypatch.setattr(NeuroSkyStream, "scan_paired_devices", staticmethod(devices))
    else:
        paired.devices.extend(devices)
    app._on_start()
    paired.arrive()
    assert not _connecting(app)
    assert app._live_screen._overlay_status.text.startswith(message)
    assert app._live_screen._overlay_retry_btn.parent is not None and not app._live_screen._btn_start.disabled


# ---- Settings → Device ----


def test_a_headset_picked_on_mock_data_takes_the_profile_off_it(app, paired):
    b = _profile(app, "B")
    _load(app, b, mock=True)
    app._headset.on_select(BLUE, "MindWave Mobile")
    assert APP.USE_MOCK_DEVICE is False and app._db.get_user_setting(b, "use_mock") == "False"
    assert _saved(app, b) == BLUE


def test_scan_while_a_profile_scan_runs_lists_every_device_and_keeps_its_pick(app, paired):
    paired.devices.extend([_mindwave(BLUE), SPEAKER])
    b = _profile(app, "B")
    _load(app, b)  # its scan still running
    app._headset.on_scan()
    paired.arrive()
    assert app._real_stream._device_address == BLUE and _saved(app, b) == BLUE
    assert _listed(app) == {BLUE, SPEAKER["address"]}


def test_a_name_being_typed_survives_a_list_that_arrives(app, paired):
    device = app._settings_screen.device
    app._headset.list_devices([_mindwave(BLUE), _mindwave(GREY)])
    device._toggle_device_rename(BLUE)
    device._bt_rename_input.text = "Blue"
    app._headset.list_devices([_mindwave(BLUE), _mindwave(GREY)])  # a scan's result lands
    assert device._bt_renaming == BLUE and device._bt_rename_input.text == "Blue"
    device._save_device_rename()
    assert app._headset.aliases == {BLUE: "Blue"}


def test_diagnostics_list_the_paired_devices_off_the_main_thread(app, paired, monkeypatch):
    report = MagicMock()
    monkeypatch.setattr(headset_module, "report_soft_error", report)
    paired.devices.append(_mindwave(BLUE))
    app._headset.on_copy_diagnostics()
    report.assert_not_called()  # the listing runs on its own thread
    paired.arrive()
    label, detail = report.call_args.args
    assert label == "user_diagnostics" and f"Paired BT devices (1):\n  - MindWave Mobile  ({BLUE})" in detail
