"""The session detail's notes: the notes, tags and mood a user keeps for a session, and their Save."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.slider import Slider

from app.ui.hooks import Hook
from app.ui.theme import C, CenteredTextInput, F, S, ThemedLabel, ThemedTextInput, fit_height_to_text
from app.ui.widgets.styled_button import StyledButton


def _field_label(text: str) -> ThemedLabel:
    label = ThemedLabel(text=text, font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_y=None, halign="left",
                        valign="bottom", padding=[0, dp(4)])
    fit_height_to_text(label)
    return label


class SessionNotes:
    """Builds the fields into `layout` and `save_button` for its owner to place; a save, Save's or a leave's, reports
    the fields through `on_save`, which returns True once they are saved. Only what differs from what was shown or
    last saved is saved on a leave."""

    on_save = Hook(default=False)  # (**fields: notes, tags, mood) -> saved

    def __init__(self, layout) -> None:
        layout.add_widget(_field_label("Notes:"))
        self.notes_input = ThemedTextInput(hint_text="Enter session notes...", multiline=True, size_hint_y=None,
                                           height=dp(80), font_size=F.BODY, foreground_color=C.TEXT,
                                           background_color=C.BG_INPUT, cursor_color=C.PRIMARY)
        layout.add_widget(self.notes_input)
        layout.add_widget(_field_label("Tags (comma-separated):"))
        self.tags_input = CenteredTextInput(hint_text="morning, calm, focused...", multiline=False, size_hint_y=None,
                                            height=dp(34), font_size=F.BODY, foreground_color=C.TEXT,
                                            background_color=C.BG_INPUT, cursor_color=C.PRIMARY)
        layout.add_widget(self.tags_input)
        mood_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=S.GAP)
        mood_row.add_widget(ThemedLabel(text="Mood:", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_x=0.2))
        self.mood_slider = Slider(min=1, max=5, value=3, step=1, size_hint_x=0.6)
        mood_value = ThemedLabel(text="3", font_size=F.H3, bold=True, color=C.TEXT, size_hint_x=0.2)
        self.mood_slider.bind(value=lambda _slider, value: setattr(mood_value, "text", str(int(value))))
        mood_row.add_widget(self.mood_slider)
        mood_row.add_widget(mood_value)
        layout.add_widget(mood_row)
        self.save_button = StyledButton(text="Save Notes", bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM, height=dp(38))
        self.save_button.bind(on_release=lambda *_a: self._save(**self._fields()))  # what the screen shows, mood too
        self._saved: dict | None = None  # the fields as shown or last saved

    def show(self, session: dict) -> None:
        self.notes_input.text = session.get("notes", "")
        self.tags_input.text = session.get("tags", "")
        self.mood_slider.value = session.get("mood_rating", 3) or 3
        # Compared with what the fields show, not the row: an unrated session shows mood 3 and isn't an edit.
        self._saved = self._fields()

    def _fields(self) -> dict:
        return {"notes": self.notes_input.text, "tags": self.tags_input.text, "mood": int(self.mood_slider.value)}

    def flush(self) -> None:
        """Save the fields that changed since they were shown or last saved: leaving can't rate an unrated session."""
        saved = self._saved or {}
        changes = {key: now for key, now in self._fields().items() if saved.get(key) != now}
        if changes:
            self._save(**changes)

    def _save(self, **fields) -> None:
        shown = self._fields()
        if self.on_save(**fields):
            self._saved = shown
