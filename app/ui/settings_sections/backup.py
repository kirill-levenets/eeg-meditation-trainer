"""Settings → Data Backup: the backup and restore buttons and the last backup's status."""

from kivy.metrics import dp

from app.ui.hooks import Hook
from app.ui.theme import C, F, ThemedLabel, text_wraps_at_width
from app.ui.widgets.styled_button import StyledButton


class BackupSection:
    """Builds the section's content into `section` and reports the user's actions through its hooks."""

    on_backup = Hook()
    on_restore = Hook()

    def __init__(self, section) -> None:
        backup_btn = StyledButton(text="Backup database", bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM, font_size=F.BODY,
                                  size_hint_y=None, height=dp(40))
        restore_btn = StyledButton(text="Restore database", bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM,
                                   font_size=F.BODY, size_hint_y=None, height=dp(40))
        self._status = ThemedLabel(text="", font_size=F.SMALL, color=C.TEXT_MUTED, size_hint_y=None, height=dp(22),
                                   halign="left", valign="middle")
        text_wraps_at_width(self._status)
        backup_btn.bind(on_release=lambda *_a: self.on_backup())
        restore_btn.bind(on_release=lambda *_a: self.on_restore())
        for widget in (backup_btn, restore_btn, self._status):
            section.add_widget(widget)

    def show_status(self, text: str) -> None:
        self._status.text = text
