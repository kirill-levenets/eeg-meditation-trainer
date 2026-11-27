"""The session detail's CSV export dialog: the file's name, and on desktop the folder it goes to; on Android it goes to
Documents/EEGMeditation, since the app can't browse shared storage by path."""
import os
from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app import android_jni
from app.ui.theme import C, CenteredTextInput, F, Icons, S, ThemedLabel, fit_height_to_text
from app.ui.widgets.popups import ThemedFileChooser, ThemedPopup, make_message_popup
from app.ui.widgets.styled_button import StyledButton, cancel_button


def open_export_dialog(session_id: int, on_save: Callable[[str | None, str], None]) -> None:
    """Ask where the session's CSV goes; Save closes the dialog and hands on (the folder, None on Android; the name
    typed)."""
    on_android = android_jni.on_android()
    content = BoxLayout(orientation="vertical", spacing=S.GAP, padding=S.GAP)
    chooser = None
    if on_android:
        where = ThemedLabel(text="Will appear in:\nDocuments/EEGMeditation/", font_size=F.SMALL,
                            color=C.TEXT_SECONDARY, size_hint_y=None, halign="left", valign="middle")
        fit_height_to_text(where)
        content.add_widget(where)
    else:
        chooser = ThemedFileChooser(path=os.path.expanduser("~"), dirselect=True, filters=["!.*"])
        content.add_widget(chooser)
    name_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP)
    name_row.add_widget(ThemedLabel(text="File name:", font_size=F.BODY, size_hint_x=0.25, color=C.TEXT_SECONDARY))
    name = CenteredTextInput(text=f"session_{session_id}.csv", multiline=False, font_size=F.BODY, size_hint_x=0.75,
                             foreground_color=C.TEXT, background_color=C.BG_INPUT)
    name_row.add_widget(name)
    content.add_widget(name_row)
    buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP)
    cancel = cancel_button(height=dp(40))
    save = StyledButton(text="Save", icon=Icons.CHECK, bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM, height=dp(40))
    buttons.add_widget(cancel)
    buttons.add_widget(save)
    content.add_widget(buttons)
    popup = ThemedPopup(title="Export CSV", content=content, size_hint=(0.9, None) if on_android else (0.95, 0.85))

    def saved(*_a) -> None:
        popup.dismiss()
        on_save(_chosen_folder(chooser) if chooser is not None else None, name.text)

    cancel.bind(on_release=popup.dismiss)
    save.bind(on_release=saved)
    popup.open()


def _chosen_folder(chooser) -> str:
    """The folder picked, the one a picked file is in, or with nothing picked the one shown."""
    if not chooser.selection:
        return chooser.path
    picked = chooser.selection[0]
    return picked if os.path.isdir(picked) else os.path.dirname(picked)


def show_export_result(message: str, success: bool = True):
    """What the export did, in a popup; returns it."""
    ok = StyledButton(text="OK", bg_color=C.ACCENT if success else C.DANGER)
    popup = make_message_popup("Export Complete" if success else "Export Failed", message, [ok])
    ok.bind(on_release=popup.dismiss)
    popup.open()
    return popup
