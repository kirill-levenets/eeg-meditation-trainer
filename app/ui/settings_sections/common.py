"""Pieces more than one Settings section builds with: the sound file chooser, the list-select source picker, the saved
formulas/programs list and the checkbox row."""
import os
from collections.abc import Callable

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox

from app.config import APP
from app.crash_handler import report_soft_error
from app.storage import android_saf as _saf
from app.ui.theme import (
    C,
    F,
    S,
    StyledButton,
    ThemedFileChooser,
    ThemedLabel,
    ThemedPopup,
    cancel_button,
    fit_row_to_text,
    make_scroll_popup,
)

# Feedback / reward sound sources, offered through the shared source picker.
SOURCE_LABELS: dict[str, str] = {
    "none": "Off", "noise": "Rain", "tone": "Tone", "heartbeat": "Crickets", "custom": "Custom",
}

# Some providers type ogg and flac as application/*, not audio/*.
_AUDIO_TYPES = ("audio/*", "application/ogg", "application/x-flac")


def open_audio_file_chooser(on_select: Callable[[str], None], title: str = "Choose audio file") -> None:
    """The one sound picker; on Android the system's, since an app can't browse storage by path."""
    if _saf.is_available():
        def _on_uri(uri: str | None) -> None:
            if uri:
                _saf.import_document(uri, os.path.join(os.path.dirname(APP.DB_PATH), "sounds"), "sound",
                                     lambda path: Clock.schedule_once(lambda _dt: _sound_imported(path, on_select)))

        _saf.open_document(_on_uri, _AUDIO_TYPES)
        return
    chooser = ThemedFileChooser(
        path=os.path.expanduser("~"),
        filters=["*.wav", "*.mp3", "*.ogg", "*.flac", "*.m4a"],
    )
    content = BoxLayout(orientation="vertical", spacing=dp(8))
    content.add_widget(chooser)
    btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
    btn_cancel = cancel_button(font_size=F.SMALL)
    btn_select = StyledButton(text="Select", font_size=F.SMALL, bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM)
    btn_row.add_widget(btn_cancel)
    btn_row.add_widget(btn_select)
    content.add_widget(btn_row)
    popup = ThemedPopup(title=title, content=content, size_hint=(0.9, 0.85))

    def _on_select(*_):
        sel = chooser.selection
        if sel:
            on_select(sel[0])
        popup.dismiss()

    btn_cancel.bind(on_release=popup.dismiss)
    btn_select.bind(on_release=_on_select)
    popup.open()


def _sound_imported(path: str | None, on_select: Callable[[str], None]) -> None:
    if path:
        on_select(path)
    else:
        report_soft_error("sound_pick_failed", "Could not read the selected sound file", force=True)


def source_label(source: str, path: str = "") -> str:
    """Human label for a feedback/reward source id, shown on the picker button."""
    if source == "custom":
        return f"Custom: {os.path.basename(path)}" if path else "Custom file..."
    return SOURCE_LABELS.get(source or "none", "Off")


def open_source_picker(title: str, options, on_choose: Callable) -> None:
    """Shared source picker (uses the standard list-select popup): a list of
    (label, value) rows; a 'custom' value opens the file chooser via on_choose."""
    holder: dict = {}
    rows = []
    for label, value in options:
        b = StyledButton(text=label, font_size=F.SMALL, bg_color=C.BG_CARD, text_color=C.TEXT)
        b.bind(on_release=lambda *_a, v=value: (holder["popup"].dismiss(), on_choose(v)))
        rows.append(b)
    cancel = cancel_button()
    holder["popup"] = make_scroll_popup(title, rows, footer=cancel, width_hint=0.8)
    cancel.bind(on_release=lambda *_a: holder["popup"].dismiss())
    holder["popup"].open()


def saved_formula_label(index: int, entry: dict) -> str:
    """A saved formula as its list row and its delete confirmation name it."""
    return entry.get("name", entry.get("formula", "")[:30])


def saved_program_label(index: int, entry: dict) -> str:
    """A saved program as its list row and its delete confirmation name it."""
    return entry.get("name", f"Program {index + 1}")


def fill_saved_list(box, entries, label: Callable, on_load: Callable, on_delete: Callable) -> None:
    """One row per saved formula or program: its name loads it, X deletes it."""
    box.clear_widgets()
    row_height = dp(30)
    box.height = row_height * len(entries) if entries else dp(0)
    for i, entry in enumerate(entries):
        row = BoxLayout(size_hint_y=None, height=row_height, spacing=S.GAP_SM)
        load_btn = StyledButton(text=label(i, entry), font_size=F.SMALL, bg_color=C.BG_CARD, text_color=C.TEXT,
                                size_hint_x=0.85, size_hint_y=None, height=row_height, bold=False)
        load_btn.bind(on_release=lambda *_a, i=i: on_load(i))
        row.add_widget(load_btn)
        del_btn = StyledButton(text="X", font_size=F.SMALL, bg_color=C.BG_CARD, text_color=C.DANGER,
                               size_hint_x=0.15, size_hint_y=None, height=row_height)
        del_btn.bind(on_release=lambda *_a, i=i: on_delete(i))
        row.add_widget(del_btn)
        box.add_widget(row)


def checkbox_row(text: str, height: float, **checkbox_kwargs) -> tuple[BoxLayout, CheckBox]:
    """A checkbox and its label on one row, which grows if the label wraps at a larger text size."""
    row = BoxLayout(size_hint_y=None, height=height, spacing=S.GAP)
    checkbox = CheckBox(size_hint_x=0.15, size_hint_y=None, height=height, **checkbox_kwargs)
    label = ThemedLabel(text=text, font_size=F.BODY, color=C.TEXT, size_hint_x=0.85, halign="left", valign="middle")
    row.add_widget(checkbox)
    row.add_widget(label)
    fit_row_to_text(row, label, height)
    return row, checkbox
