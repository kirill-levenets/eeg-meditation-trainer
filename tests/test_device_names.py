"""Telling headsets apart (#41): every MindWave advertises the same Bluetooth name, so the device list marks the selected
and the connected one, and each headset can be given its own name, used wherever the app names it."""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kivy.clock import Clock

from app.config import APP
from app.session.session_run import SessionRun
from app.storage.database import DatabaseManager
from app.ui.bt_wait import BtWait
from app.ui.device_labels import MAX_DEVICE_ALIAS, device_label, device_row_text
from app.ui.headset import Headset
from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen
from app.ui.settings_sections.device import DeviceSection
from app.ui.theme import C, Icons
from tests._app import HEADSET, popup_message, popups, start_connecting
from tests._context import stub_context
from tests._settings_section import settings_section

BLUE = "00:11:22:33:44:01"
GREY = "00:11:22:33:44:02"
PAIRED = [{"name": "MindWave Mobile", "address": BLUE}, {"name": "MindWave Mobile", "address": GREY}]


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch):
    """A real headset is in use unless a test says otherwise: the module's shared app leaves the mode its last
    profile loaded."""
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)


def _rig(db: DatabaseManager | None = None, uid: int = 1) -> SimpleNamespace:
    """A Headset built by its constructor, with BLUE selected and not connected: `headset`, and the stand-ins it works
    on (`stream`, `device` for Settings › Device, `live_screen`, `db` unless a real one is given)."""
    stream = MagicMock(_device_address=BLUE, _device_name="MindWave Mobile", is_connected=False)
    device, live_screen = MagicMock(), MagicMock()
    ctx = stub_context(db=db or MagicMock(), user_id=lambda: uid)
    headset = Headset(ctx, stream, device, live_screen, serial_override=lambda: None)
    if db is not None:
        headset.load_aliases()
    return SimpleNamespace(headset=headset, stream=stream, device=device, live_screen=live_screen, db=ctx.db)


# ---- one name for a headset, everywhere ----


def test_a_headset_is_called_by_its_alias_else_its_bluetooth_name_else_its_address():
    assert device_label(BLUE, "MindWave Mobile", {BLUE: "Blue"}) == "Blue"
    assert device_label(GREY, "MindWave Mobile", {BLUE: "Blue"}) == "MindWave Mobile"
    assert device_label(GREY, "", {}) == GREY
    assert device_row_text("Blue", BLUE) == f"Blue  ({BLUE})"


def test_an_alias_survives_a_restart_and_names_new_sessions(db_path, monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    db = DatabaseManager(db_path=db_path)
    try:
        _rig(db).headset.on_rename(BLUE, "MindWave Mobile", "  Blue  ")
    finally:
        db.close()
    db = DatabaseManager(db_path=db_path)  # the next launch
    try:
        rig = _rig(db)
        assert rig.headset.name() == "Blue"
        rig.stream._device_address = GREY
        assert rig.headset.name() == "MindWave Mobile"
    finally:
        db.close()


def test_a_session_on_a_headset_is_named_by_its_alias(fresh_app):
    app = fresh_app
    app._change_setting("use_mock", False)
    app._real_stream.set_device(BLUE, "MindWave Mobile")
    app._headset.on_rename(BLUE, "MindWave Mobile", "Blue")
    try:
        assert app._make_session_name().endswith(" - Blue")
        app._real_stream.set_device(GREY, "MindWave Mobile")
        assert app._make_session_name().endswith(" - MindWave Mobile")
    finally:
        app._headset.on_rename(BLUE, "MindWave Mobile", "")  # aliases are the phone's, not the profile's


def test_an_alias_names_the_headset_for_every_profile(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        _rig(db).headset.on_rename(BLUE, "MindWave Mobile", "Blue")
        assert _rig(db, uid=2).headset.name() == "Blue"
    finally:
        db.close()


@pytest.mark.parametrize("text", ["", "   ", "MindWave Mobile"])
def test_clearing_an_alias_or_giving_the_bluetooth_name_goes_back_to_the_bluetooth_name(db_path, text):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(BLUE, "MindWave Mobile", "Blue")
        rig.headset.on_rename(BLUE, "MindWave Mobile", text)
        assert rig.headset.name() == "MindWave Mobile"
        assert db.get_json_setting("bt_device_aliases", None) == {}
        rig.device.relabel_bt_device.assert_called_with(BLUE, "")
    finally:
        db.close()


def test_a_long_alias_is_cut_to_fit_a_row(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(BLUE, "MindWave Mobile", "x" * 100)
        assert rig.headset.name() == "x" * MAX_DEVICE_ALIAS == "x" * 24
    finally:
        db.close()


def test_renaming_the_selected_headset_renames_it_on_screen(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(BLUE, "MindWave Mobile", "Blue")
        rig.device.relabel_bt_device.assert_called_with(BLUE, "Blue")
        assert rig.live_screen.update_device_status.call_args.kwargs["device_name"] == "Blue"
        rig.device.update_device_status.assert_called_with(False, meta="Selected: Blue")
        rig.stream.is_connected = True
        rig.headset.on_rename(BLUE, "MindWave Mobile", "Blue 2")
        rig.live_screen.update_device_status.assert_called_with(True, device_name="Blue 2", connecting=False)
        rig.device.update_device_status.assert_called_with(True, name="Blue 2")
    finally:
        db.close()


def test_in_mock_mode_no_headset_is_in_use_and_a_rename_leaves_the_mock_labels(db_path, monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.stream.is_connected = True  # the link outlives a switch to mock data
        assert rig.headset.state() == (None, None)
        rig.headset.on_rename(BLUE, "MindWave Mobile", "Blue")
        rig.device.relabel_bt_device.assert_called_with(BLUE, "Blue")
        rig.live_screen.update_device_status.assert_not_called()
        rig.device.update_device_status.assert_not_called()
    finally:
        db.close()


def test_renaming_another_headset_leaves_the_selected_ones_labels(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(GREY, "MindWave Mobile", "Grey")
        rig.device.relabel_bt_device.assert_called_with(GREY, "Grey")
        rig.live_screen.update_device_status.assert_not_called()
    finally:
        db.close()


def test_the_connecting_overlay_names_the_headset_by_its_alias(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(BLUE, "MindWave Mobile", "Blue")
        rig.stream.start.return_value = True
        wait = BtWait(rig.stream, rig.live_screen, headset_name=rig.headset.name, on_main_for=lambda run, fn: fn())
        assert wait.begin(SessionRun(1)) is None  # the wait began
        rig.live_screen.show_overlay.assert_called_with("Connecting to Blue...")
    finally:
        db.close()


def test_scanned_devices_carry_their_aliases(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(GREY, "MindWave Mobile", "Grey")
        assert rig.headset.with_aliases(PAIRED) == [{**PAIRED[0], "alias": ""}, {**PAIRED[1], "alias": "Grey"}]
    finally:
        db.close()


def test_a_corrupt_alias_store_reads_as_none(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        db.set_setting("bt_device_aliases", "[1, 2")
        assert _rig(db).headset.name() == "MindWave Mobile"
        db.set_setting("bt_device_aliases", '["Blue"]')
        assert _rig(db).headset.name() == "MindWave Mobile"
    finally:
        db.close()


# ---- switching headsets ----


def _refusal() -> str:
    (popup,) = popups()
    return popup_message(popup)


def test_switching_headsets_while_a_session_runs_is_refused(fresh_app):
    app = fresh_app
    app._on_start()
    app._headset.on_select(GREY, "MindWave Mobile")
    assert "switching headsets" in _refusal() and app._real_stream._device_address != GREY


def test_switching_headsets_while_connecting_is_refused(fresh_app, monkeypatch):
    app = fresh_app
    start_connecting(app, monkeypatch)
    app._headset.on_select(GREY, "MindWave Mobile")
    assert "switching headsets" in _refusal() and app._real_stream._device_address == HEADSET[0]


def test_picking_the_selected_headset_during_a_session_is_not_refused(fresh_app, monkeypatch):
    app = fresh_app
    start_connecting(app, monkeypatch)  # in real mode it changes nothing; on the mock it would
    app._headset.on_select(*HEADSET)
    assert popups() == [] and app._real_stream._device_address == HEADSET[0]


def test_switching_headsets_between_sessions_selects_the_new_one(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    rig = _rig()
    rig.headset.on_select(GREY, "MindWave Mobile")
    rig.stream.set_device.assert_called_once_with(GREY, "MindWave Mobile")
    rig.db.set_user_setting.assert_any_call(1, "bt_device_address", GREY)


def _select_for_real(rig):
    """A MagicMock stream doesn't run set_device: do what the real one does (the link to another headset closes)."""
    def set_device(address, name):
        if address != rig.stream._device_address:
            rig.stream.is_connected = False
        rig.stream._device_address, rig.stream._device_name = address, name
    rig.stream.set_device.side_effect = set_device


def test_picking_another_headset_shows_it_unconnected_everywhere(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        rig = _rig(db)
        rig.headset.on_rename(GREY, "MindWave Mobile", "Grey")
        _select_for_real(rig)
        rig.stream.is_connected = True  # linked to BLUE between sessions
        rig.headset.on_select(GREY, "MindWave Mobile")
        rig.live_screen.update_device_status.assert_called_with(False, device_name="Grey", connecting=False)
        rig.device.update_device_status.assert_called_with(False, meta="Selected: Grey")
    finally:
        db.close()


def test_picking_the_connected_headset_again_keeps_it_shown_connected():
    rig = _rig()
    _select_for_real(rig)
    rig.stream.is_connected = True
    rig.headset.on_select(BLUE, "MindWave Mobile")
    rig.device.update_device_status.assert_called_with(True, name="MindWave Mobile")
    rig.live_screen.update_device_status.assert_called_with(True, device_name="MindWave Mobile", connecting=False)


def test_the_list_learns_which_headset_is_selected_and_which_connected():
    rig = _rig()
    assert rig.headset.state() == (BLUE, None)
    rig.stream.is_connected = True
    assert rig.headset.state() == (BLUE, BLUE)


# ---- the Settings list ----


def _listed(device, selected, connected) -> dict:
    """Two paired headsets in the Device list; the returned state is what device_state reports."""
    state = {"selected": selected, "connected": connected}
    wire(device, device_state=lambda: (state["selected"], state["connected"]))
    device.populate_bt_devices([{**PAIRED[0], "alias": "Blue"}, {**PAIRED[1], "alias": ""}])
    return state


def _settings(selected=BLUE, connected=None) -> SimpleNamespace:
    """The Device section alone, as Settings builds it."""
    device = settings_section(lambda section, scroll: DeviceSection(section, scroll=scroll))
    return SimpleNamespace(device=device, _state=_listed(device, selected, connected))


def test_the_list_names_each_row_by_its_alias_and_address():
    rows = _settings().device._bt_rows
    assert rows[BLUE].text == device_row_text("Blue", BLUE)
    assert rows[GREY].text == device_row_text("MindWave Mobile", GREY)


def test_the_selected_row_is_filled_and_the_connected_one_shows_the_link():
    screen = _settings(selected=BLUE, connected=BLUE)
    rows = screen.device._bt_rows
    assert tuple(rows[BLUE].bg_color) == tuple(C.ACCENT)
    assert tuple(rows[GREY].bg_color) == tuple(C.BG_CARD)
    assert rows[BLUE].icon == Icons.BLUETOOTH
    assert rows[GREY].icon == ""


def test_the_marks_follow_the_connection_whenever_the_status_changes():
    screen = SettingsScreen()  # the whole screen: its on_pre_enter is under test
    screen._state = _listed(screen.device, BLUE, None)
    assert screen.device._bt_rows[BLUE].icon == ""
    screen._state["connected"] = BLUE
    screen.device.update_device_status(True, name="Blue")
    assert screen.device._bt_rows[BLUE].icon == Icons.BLUETOOTH
    screen._state.update(selected=GREY, connected=None)
    screen.dispatch("on_pre_enter")  # coming back to Settings after the link dropped between sessions
    assert screen.device._bt_rows[BLUE].icon == ""
    assert tuple(screen.device._bt_rows[GREY].bg_color) == tuple(C.ACCENT)


def test_the_pencil_opens_the_name_editor_under_its_row():
    screen = _settings()
    for address in (BLUE, GREY):
        screen.device._bt_pencils[address].dispatch("on_release")
        shown = list(reversed(screen.device._bt_device_list.children))
        assert shown[shown.index(screen.device._bt_rows[address].parent) + 1] is screen.device._bt_rename_row
        assert shown.count(screen.device._bt_rename_row) == 1
    assert screen.device._bt_rename_input.text == ""  # GREY has no alias yet
    assert screen.device._bt_rename_input.hint_text == "MindWave Mobile"
    screen.device._bt_pencils[GREY].dispatch("on_release")  # the pencil again closes it
    assert screen.device._bt_rename_row.parent is None


def test_the_editor_starts_from_the_alias_and_saves_through_the_callback():
    screen = _settings()
    saved = []
    wire(screen.device, on_device_rename=lambda address, name, text: saved.append((address, name, text)))
    screen.device._bt_pencils[BLUE].dispatch("on_release")
    assert screen.device._bt_rename_input.text == "Blue"
    screen.device._bt_rename_input.text = "Blue headset"
    screen.device._bt_rename_input.dispatch("on_text_validate")
    assert saved == [(BLUE, "MindWave Mobile", "Blue headset")]
    assert screen.device._bt_rename_row.parent is None


def test_an_editor_closed_before_its_focus_lands_raises_no_keyboard():
    screen = _settings()
    screen.device._bt_pencils[BLUE].dispatch("on_release")
    screen.device._bt_pencils[BLUE].dispatch("on_release")  # closed again in the same frame
    Clock.tick()
    assert screen.device._bt_rename_input.focus is False


def test_the_name_field_stops_at_the_alias_limit():
    screen = _settings()
    screen.device._bt_pencils[BLUE].dispatch("on_release")  # holds "Blue" (a never-filled field ignores typing headless)
    field = screen.device._bt_rename_input
    field.cursor = (len(field.text), 0)
    field.insert_text("y" * 40)
    assert field.text == "Blue" + "y" * (MAX_DEVICE_ALIAS - 4)


def test_a_relabelled_row_shows_its_new_name_or_the_bluetooth_name():
    screen = _settings()
    screen.device.relabel_bt_device(GREY, "Grey")
    assert screen.device._bt_rows[GREY].text == device_row_text("Grey", GREY)
    screen.device.relabel_bt_device(BLUE, "")
    assert screen.device._bt_rows[BLUE].text == device_row_text("MindWave Mobile", BLUE)


def test_a_rescan_moves_an_open_editor_to_its_headsets_new_row():
    """A scan's list can land while a name is typed (scans run off the main thread): the editor stays, on the new list."""
    screen = _settings()
    device = screen.device
    device._bt_pencils[BLUE].dispatch("on_release")
    device.populate_bt_devices(PAIRED)
    rows = device._bt_device_list.children
    assert device._bt_rename_row.parent is device._bt_device_list
    assert rows[rows.index(device._bt_rename_row) + 1] is device._bt_rows[BLUE].parent  # right under BLUE's new row
    device._bt_pencils[BLUE].dispatch("on_release")  # one tap closes it
    assert device._bt_rename_row.parent is None


def test_tapping_a_row_selects_its_headset():
    screen = _settings()
    picked = []
    wire(screen.device, on_device_select=lambda address, name: picked.append((address, name)))
    screen.device._bt_rows[GREY].dispatch("on_release")
    assert picked == [(GREY, "MindWave Mobile")]
