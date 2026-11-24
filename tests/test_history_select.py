from app.ui.history_screen import HistoryScreen
from app.ui.hooks import wire


def _history():
    h = HistoryScreen()
    h.session_list._shown = [{"id": 1}, {"id": 2}, {"id": 3}]  # "currently shown" sessions
    return h


def test_select_mode_off_by_default_and_clears_on_exit():
    h = _history()
    assert h.session_list._select_mode is False
    h.set_select_mode(True)
    assert h.session_list._select_mode is True
    h.session_list.toggle_selection(1)
    h.session_list.toggle_selection(3)
    assert h.session_list.selected_ids == {1, 3}
    h.set_select_mode(False)            # leaving select mode drops the selection
    assert h.session_list._select_mode is False
    assert h.session_list.selected_ids == set()


def test_toggle_adds_then_removes():
    h = _history()
    h.set_select_mode(True)
    h.session_list.toggle_selection(2)
    assert h.session_list.selected_ids == {2}
    h.session_list.toggle_selection(2)
    assert h.session_list.selected_ids == set()


def test_select_all_shown_selects_visible_rows_only():
    h = _history()
    h.set_select_mode(True)
    h.session_list.select_all()
    assert h.session_list.selected_ids == {1, 2, 3}


def test_export_selected_fires_callback_with_sorted_ids():
    got = []
    h = _history()
    wire(h, on_export_sessions=lambda ids: got.append(ids))
    h.set_select_mode(True)
    h.session_list.toggle_selection(3)
    h.session_list.toggle_selection(1)
    h.export_selected()
    assert got == [[1, 3]]


def test_export_selected_is_noop_when_nothing_selected():
    got = []
    h = _history()
    wire(h, on_export_sessions=lambda ids: got.append(ids))
    h.set_select_mode(True)
    h.export_selected()
    assert got == []
