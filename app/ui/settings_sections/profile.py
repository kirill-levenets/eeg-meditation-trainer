"""Settings → User Profile: the active profile, the others to switch to, a new one, and a profile's delete."""

from kivy.metrics import dp

from app.ui.formatting import format_count
from app.ui.hooks import Hook
from app.ui.theme import C, F, Icons, ThemedLabel, text_wraps_at_width
from app.ui.widgets.popups import make_message_popup
from app.ui.widgets.styled_button import StyledButton, cancel_button
from app.ui.widgets.user_picker import UserPickerForm


class ProfileSection:
    """Builds the section's content into `section` and reports the user's actions through its hooks."""

    on_switch = Hook()
    on_create = Hook()
    on_delete = Hook()
    session_counter = Hook(default=0)

    def __init__(self, section) -> None:
        self._current_label = ThemedLabel(text="Current: none", font_size=F.BODY, color=C.PRIMARY, bold=True,
                                          size_hint_y=None, height=dp(24), halign="left")
        text_wraps_at_width(self._current_label)
        section.add_widget(self._current_label)
        self.picker = UserPickerForm(on_create=self._create, on_pick_existing=self._switch,
                                     on_count=self._count_sessions, on_delete=self._confirm_delete)
        section.add_widget(self.picker)

    def show_users(self, users: list[dict], current_user_id: int | None) -> None:
        """The profiles to pick from, and the active one named above them."""
        self.picker.populate_users(users)
        name = next((u["name"] for u in users if u["id"] == current_user_id), "none")  # none: the gate is up
        self._current_label.text = f"Current: {name}"

    def refresh_counts(self) -> None:
        """Draw the profile rows again: each reads its session count as it is drawn."""
        self.picker.redraw()

    def _create(self, name: str) -> None:
        self.on_create(name)

    def _switch(self, user_id: int) -> None:
        self.on_switch(user_id)

    def _count_sessions(self, user_id: int) -> int | None:
        return self.session_counter(user_id)

    def _confirm_delete(self, user_id: int) -> None:
        """A profile's delete, after the user confirms it with its session count in view."""
        name = next((u["name"] for u in self.picker.users if u["id"] == user_id), "")
        n = self._count_sessions(user_id)
        sessions = "Its sessions" if n is None else f"Its {format_count(n, 'session')}"  # None: the count failed
        message = (f'Delete profile "{name}"?\n\n'
                   f"{sessions} and all its settings will be permanently deleted.\n"
                   "This cannot be undone.")
        btn_cancel = cancel_button()
        btn_confirm = StyledButton(text="Delete", icon=Icons.DELETE, bg_color=C.DANGER)
        popup = make_message_popup("Confirm Delete", message, [btn_cancel, btn_confirm])
        btn_cancel.bind(on_release=popup.dismiss)

        def _do_delete(*_args):
            popup.dismiss()
            self.on_delete(user_id)

        btn_confirm.bind(on_release=_do_delete)
        popup.open()
