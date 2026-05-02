from app.ui.widgets.user_picker import UserPickerForm


def test_form_create_callback_fires_with_typed_name():
    received = []
    form = UserPickerForm(
        on_create=lambda name: received.append(("create", name)),
        on_pick_existing=lambda uid: received.append(("pick", uid)),
    )
    form._name_input.text = "  Alice  "
    form._on_create_pressed()
    assert received == [("create", "Alice")]


def test_form_create_blocked_for_short_name():
    received = []
    form = UserPickerForm(
        on_create=lambda name: received.append(("create", name)),
        on_pick_existing=lambda uid: received.append(("pick", uid)),
    )
    form._name_input.text = "A"
    form._on_create_pressed()
    assert received == []
    err = form._error_label.text.lower()
    assert "at least 2" in err or "too short" in err


def test_form_existing_panel_hidden_when_no_users():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.populate_users([])
    assert form._existing_panel.opacity == 0
    assert form._existing_panel.disabled is True


def test_form_existing_panel_shown_when_users_exist():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.populate_users([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    assert form._existing_panel.opacity == 1
    assert form._existing_panel.disabled is False


def test_form_pick_existing_callback_fires():
    received = []
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: received.append(uid),
    )
    form.populate_users([{"id": 7, "name": "Charlie"}])
    form._on_existing_row_tap(7)
    assert received == [7]


def test_show_duplicate_error_populates_inline_region():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.show_duplicate_error(user_id=42, name="Alice")
    assert form._error_row.opacity == 1
    assert "Alice" in form._error_label.text


def test_use_existing_button_fires_pick_callback():
    received = []
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: received.append(uid),
    )
    form.show_duplicate_error(user_id=99, name="Dana")
    form._btn_use_existing.dispatch("on_release")
    assert received == [99]


def test_use_existing_clears_error_region():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.show_duplicate_error(user_id=42, name="Alice")
    assert form._error_row.opacity == 1
    form._btn_use_existing.dispatch("on_release")
    assert form._error_row.opacity == 0
    assert form._error_row.disabled is True


def test_change_name_button_clears_error_region():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.show_duplicate_error(user_id=1, name="X")
    form._btn_change_name.dispatch("on_release")
    assert form._error_row.opacity == 0
    assert form._error_row.disabled is True


def test_clear_resets_input_and_error():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form._name_input.text = "abc"
    form.show_duplicate_error(user_id=1, name="X")
    form.clear()
    assert form._name_input.text == ""
    assert form._error_row.opacity == 0


def test_typing_filters_existing_profiles_list():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.populate_users([
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Alfred"},
    ])
    # Empty input → all 3 visible
    assert "(3)" in form._existing_header.text

    form._name_input.text = "al"  # case-insensitive substring
    # Two matches: "Alice", "Alfred"
    assert "(2)" in form._existing_header.text
    assert form._existing_panel.opacity == 1
    assert "matches" in form._existing_header.text.lower()


def test_typing_unique_name_collapses_dropdown():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.populate_users([{"id": 1, "name": "Alice"}])
    form._name_input.text = "Bob"
    # No matches → panel hidden
    assert form._existing_panel.opacity == 0
    assert form._existing_panel.disabled is True


def test_clearing_input_restores_full_list():
    form = UserPickerForm(
        on_create=lambda name: None,
        on_pick_existing=lambda uid: None,
    )
    form.populate_users([
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ])
    form._name_input.text = "xyz"
    assert form._existing_panel.opacity == 0
    form._name_input.text = ""
    assert form._existing_panel.opacity == 1
    assert "(2)" in form._existing_header.text
