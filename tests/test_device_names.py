"""Telling headsets apart (#41): every MindWave advertises the same Bluetooth name, so the device list marks the selected
and the connected one, and each headset can be given its own name, used wherever the app names it."""

import os
import tempfile
from unittest.mock import MagicMock

import pytest
from kivy.clock import Clock

from app.config import APP
from app.session.manager import SessionManager
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.device_labels import MAX_DEVICE_ALIAS, device_label, device_row_text
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import C, Icons
from app.ui.wizard_screen import WizardScreen

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


def _app(db: DatabaseManager | None = None) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db or MagicMock()
    app._current_user_id = 1
    app._waiting_for_bt = False
    app._tick_thread = None
    app._real_stream = MagicMock()
    app._real_stream._device_address = BLUE
    app._real_stream._device_name = "MindWave Mobile"
    app._real_stream.is_connected = False
    app._session_manager = SessionManager()
    app._live_screen = MagicMock()
    app._settings_screen = MagicMock()
    app._info_popup = MagicMock()
    if db is not None:
        app._load_device_aliases()
    return app


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
        _app(db)._on_device_rename(BLUE, "MindWave Mobile", "  Blue  ")
    finally:
        db.close()
    db = DatabaseManager(db_path=db_path)  # the next launch
    try:
        app = _app(db)
        assert app._device_name() == "Blue"
        assert app._make_session_name().endswith(" - Blue")
        app._real_stream._device_address = GREY
        assert app._make_session_name().endswith(" - MindWave Mobile")
    finally:
        db.close()


def test_an_alias_names_the_headset_for_every_profile(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        _app(db)._on_device_rename(BLUE, "MindWave Mobile", "Blue")
        other = _app(db)
        other._current_user_id = 2
        other._load_device_aliases()
        assert other._device_name() == "Blue"
    finally:
        db.close()


@pytest.mark.parametrize("text", ["", "   ", "MindWave Mobile"])
def test_clearing_an_alias_or_giving_the_bluetooth_name_goes_back_to_the_bluetooth_name(db_path, text):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(BLUE, "MindWave Mobile", "Blue")
        app._on_device_rename(BLUE, "MindWave Mobile", text)
        assert app._device_name() == "MindWave Mobile"
        assert db.get_json_setting("bt_device_aliases", None) == {}
        app._settings_screen.relabel_bt_device.assert_called_with(BLUE, "")
    finally:
        db.close()


def test_a_long_alias_is_cut_to_fit_a_row(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(BLUE, "MindWave Mobile", "x" * 100)
        assert app._device_name() == "x" * MAX_DEVICE_ALIAS == "x" * 24
    finally:
        db.close()


def test_renaming_the_selected_headset_renames_it_on_screen(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(BLUE, "MindWave Mobile", "Blue")
        app._settings_screen.relabel_bt_device.assert_called_with(BLUE, "Blue")
        assert app._live_screen.update_device_status.call_args.kwargs["device_name"] == "Blue"
        app._settings_screen.update_device_status.assert_called_with(False, meta="Selected: Blue")
        app._real_stream.is_connected = True
        app._on_device_rename(BLUE, "MindWave Mobile", "Blue 2")
        app._live_screen.update_device_status.assert_called_with(True, device_name="Blue 2", connecting=False)
        app._settings_screen.update_device_status.assert_called_with(True, name="Blue 2")
    finally:
        db.close()


def test_in_mock_mode_no_headset_is_in_use_and_a_rename_leaves_the_mock_labels(db_path, monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._real_stream.is_connected = True  # the link outlives a switch to mock data
        assert app._device_state() == (None, None)
        app._on_device_rename(BLUE, "MindWave Mobile", "Blue")
        app._settings_screen.relabel_bt_device.assert_called_with(BLUE, "Blue")
        app._live_screen.update_device_status.assert_not_called()
        app._settings_screen.update_device_status.assert_not_called()
    finally:
        db.close()


def test_renaming_another_headset_leaves_the_selected_ones_labels(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(GREY, "MindWave Mobile", "Grey")
        app._settings_screen.relabel_bt_device.assert_called_with(GREY, "Grey")
        app._live_screen.update_device_status.assert_not_called()
    finally:
        db.close()


def test_the_connecting_overlay_names_the_headset_by_its_alias(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(BLUE, "MindWave Mobile", "Blue")
        app._start_attempt = 1
        app._real_stream.start.return_value = True
        assert app._begin_bt_wait()
        app._live_screen.show_overlay.assert_called_with("Connecting to Blue...")
    finally:
        db.close()


def test_scanned_devices_carry_their_aliases(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(GREY, "MindWave Mobile", "Grey")
        assert app._with_aliases(PAIRED) == [{**PAIRED[0], "alias": ""}, {**PAIRED[1], "alias": "Grey"}]
    finally:
        db.close()


def test_a_corrupt_alias_store_reads_as_none(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        db.set_setting("bt_device_aliases", "[1, 2")
        assert _app(db)._device_name() == "MindWave Mobile"
        db.set_setting("bt_device_aliases", '["Blue"]')
        assert _app(db)._device_name() == "MindWave Mobile"
    finally:
        db.close()


# ---- switching headsets ----


def test_switching_headsets_while_a_session_runs_is_refused():
    app = _app()
    app._session_manager.start()
    app._on_device_select(GREY, "MindWave Mobile")
    app._real_stream.set_device.assert_not_called()
    app._info_popup.assert_called_once()
    assert "switching headsets" in app._info_popup.call_args.args[1]


def test_switching_headsets_while_connecting_is_refused():
    app = _app()
    app._waiting_for_bt = True
    app._on_device_select(GREY, "MindWave Mobile")
    app._real_stream.set_device.assert_not_called()


def test_picking_the_selected_headset_during_a_session_is_not_refused():
    app = _app()
    app._session_manager.start()
    app._on_device_select(BLUE, "MindWave Mobile")
    app._info_popup.assert_not_called()


def test_switching_headsets_between_sessions_selects_the_new_one(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    app = _app()
    app._on_device_select(GREY, "MindWave Mobile")
    app._real_stream.set_device.assert_called_once_with(GREY, "MindWave Mobile")
    app._db.set_user_setting.assert_any_call(1, "bt_device_address", GREY)


def _select_for_real(app):
    """A MagicMock stream doesn't run set_device: do what the real one does (the link to another headset closes)."""
    def set_device(address, name):
        if address != app._real_stream._device_address:
            app._real_stream.is_connected = False
        app._real_stream._device_address, app._real_stream._device_name = address, name
    app._real_stream.set_device.side_effect = set_device


def test_picking_another_headset_shows_it_unconnected_everywhere(db_path):
    db = DatabaseManager(db_path=db_path)
    try:
        app = _app(db)
        app._on_device_rename(GREY, "MindWave Mobile", "Grey")
        _select_for_real(app)
        app._real_stream.is_connected = True  # linked to BLUE between sessions
        app._on_device_select(GREY, "MindWave Mobile")
        app._live_screen.update_device_status.assert_called_with(False, device_name="Grey", connecting=False)
        app._settings_screen.update_device_status.assert_called_with(False, meta="Selected: Grey")
    finally:
        db.close()


def test_picking_the_connected_headset_again_keeps_it_shown_connected():
    app = _app()
    _select_for_real(app)
    app._real_stream.is_connected = True
    app._on_device_select(BLUE, "MindWave Mobile")
    app._settings_screen.update_device_status.assert_called_with(True, name="MindWave Mobile")
    app._live_screen.update_device_status.assert_called_with(True, device_name="MindWave Mobile", connecting=False)


def test_the_list_learns_which_headset_is_selected_and_which_connected():
    app = _app()
    assert app._device_state() == (BLUE, None)
    app._real_stream.is_connected = True
    assert app._device_state() == (BLUE, BLUE)


# ---- the Settings list ----


def _settings(selected=BLUE, connected=None) -> SettingsScreen:
    screen = SettingsScreen()
    state = {"selected": selected, "connected": connected}
    screen.set_device_state_callback(lambda: (state["selected"], state["connected"]))
    screen._state = state
    screen.populate_bt_devices([{**PAIRED[0], "alias": "Blue"}, {**PAIRED[1], "alias": ""}])
    return screen


def test_the_list_names_each_row_by_its_alias_and_address():
    rows = _settings()._bt_rows
    assert rows[BLUE].text == device_row_text("Blue", BLUE)
    assert rows[GREY].text == device_row_text("MindWave Mobile", GREY)


def test_the_selected_row_is_filled_and_the_connected_one_shows_the_link():
    screen = _settings(selected=BLUE, connected=BLUE)
    rows = screen._bt_rows
    assert tuple(rows[BLUE].bg_color) == tuple(C.ACCENT)
    assert tuple(rows[GREY].bg_color) == tuple(C.BG_CARD)
    assert rows[BLUE].icon == Icons.BLUETOOTH
    assert rows[GREY].icon == ""


def test_the_marks_follow_the_connection_whenever_the_status_changes():
    screen = _settings(selected=BLUE, connected=None)
    assert screen._bt_rows[BLUE].icon == ""
    screen._state["connected"] = BLUE
    screen.update_device_status(True, name="Blue")
    assert screen._bt_rows[BLUE].icon == Icons.BLUETOOTH
    screen._state.update(selected=GREY, connected=None)
    screen.dispatch("on_pre_enter")  # coming back to Settings after the link dropped between sessions
    assert screen._bt_rows[BLUE].icon == ""
    assert tuple(screen._bt_rows[GREY].bg_color) == tuple(C.ACCENT)


def test_the_pencil_opens_the_name_editor_under_its_row():
    screen = _settings()
    for address in (BLUE, GREY):
        screen._bt_pencils[address].dispatch("on_release")
        shown = list(reversed(screen._bt_device_list.children))
        assert shown[shown.index(screen._bt_rows[address].parent) + 1] is screen._bt_rename_row
        assert shown.count(screen._bt_rename_row) == 1
    assert screen._bt_rename_input.text == ""  # GREY has no alias yet
    assert screen._bt_rename_input.hint_text == "MindWave Mobile"
    screen._bt_pencils[GREY].dispatch("on_release")  # the pencil again closes it
    assert screen._bt_rename_row.parent is None


def test_the_editor_starts_from_the_alias_and_saves_through_the_callback():
    screen = _settings()
    saved = []
    screen.set_device_rename_callback(lambda address, name, text: saved.append((address, name, text)))
    screen._bt_pencils[BLUE].dispatch("on_release")
    assert screen._bt_rename_input.text == "Blue"
    screen._bt_rename_input.text = "Blue headset"
    screen._bt_rename_input.dispatch("on_text_validate")
    assert saved == [(BLUE, "MindWave Mobile", "Blue headset")]
    assert screen._bt_rename_row.parent is None


def test_an_editor_closed_before_its_focus_lands_raises_no_keyboard():
    screen = _settings()
    screen._bt_pencils[BLUE].dispatch("on_release")
    screen.populate_bt_devices(PAIRED)  # a rescan in the same frame closes it
    Clock.tick()
    assert screen._bt_rename_input.focus is False


def test_the_name_field_stops_at_the_alias_limit():
    screen = _settings()
    screen._bt_pencils[BLUE].dispatch("on_release")  # holds "Blue" (a never-filled field ignores typing headless)
    field = screen._bt_rename_input
    field.cursor = (len(field.text), 0)
    field.insert_text("y" * 40)
    assert field.text == "Blue" + "y" * (MAX_DEVICE_ALIAS - 4)


def test_a_relabelled_row_shows_its_new_name_or_the_bluetooth_name():
    screen = _settings()
    screen.relabel_bt_device(GREY, "Grey")
    assert screen._bt_rows[GREY].text == device_row_text("Grey", GREY)
    screen.relabel_bt_device(BLUE, "")
    assert screen._bt_rows[BLUE].text == device_row_text("MindWave Mobile", BLUE)


def test_a_rescan_keeps_no_stale_editor():
    screen = _settings()
    screen._bt_pencils[BLUE].dispatch("on_release")
    screen.populate_bt_devices(PAIRED)
    assert screen._bt_rename_row.parent is None
    screen._bt_pencils[BLUE].dispatch("on_release")  # one tap opens it again, on the new list
    assert screen._bt_rename_row.parent is screen._bt_device_list


def test_tapping_a_row_selects_its_headset():
    screen = _settings()
    picked = []
    screen.set_device_select_callback(lambda address, name: picked.append((address, name)))
    screen._bt_rows[GREY].dispatch("on_release")
    assert picked == [(GREY, "MindWave Mobile")]


# ---- the first-run wizard ----


def test_the_wizard_lists_headsets_by_alias_and_address():
    wizard = WizardScreen()
    wizard.populate_devices([{**PAIRED[0], "alias": "Blue"}, PAIRED[1]])
    texts = [btn.text for btn in reversed(wizard._device_list.children)]
    assert texts == [device_row_text("Blue", BLUE), device_row_text("MindWave Mobile", GREY)]

