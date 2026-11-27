"""Settings → Timer's program editor: the program's timed segments in order, their total, the loaded program's name with
its Save row, and the saved programs."""
import os
from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.logger import logger
from app.ui.hooks import Hook
from app.ui.settings_sections.common import (
    SOURCE_LABELS,
    fill_saved_list,
    open_sound_picker,
    open_source_picker,
    saved_formula_label,
    saved_program_label,
)
from app.ui.theme import C, CenteredTextInput, F, Icons, S, ThemedLabel, fit_height_to_text, text_fills_box
from app.ui.widgets.popups import make_scroll_popup
from app.ui.widgets.styled_button import StyledButton, cancel_button

# The built-in metrics a segment can train on, by their metric keys (native_*, not ns_*).
PROGRAM_BUILTIN_FORMULAS: list[tuple[str, str]] = [
    ("shamatha_score", "Shamatha"),
    ("meditation_score", "Meditation"),
    ("native_attention", "NS Attention"),
    ("native_meditation", "NS Meditation"),
]
_PROGRAM_BUILTIN_LABELS: dict[str, str] = dict(PROGRAM_BUILTIN_FORMULAS)
_END_CUE_OPTIONS: tuple[tuple[str, str | None], ...] = (("Chime", None), ("Warble", "warble"))
# A segment's feedback: "" inherits the global feedback sound.
_SEGMENT_FEEDBACK_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Default (use global)", ""), ("Rain", "noise"), ("Tone", "tone"), ("Custom file...", "custom"),
)
# Each segment cell's column, by its header and its share of the row; the last is the delete button's.
_COLUMNS: tuple[tuple[str, float], ...] = (("Min", 0.16), ("Metric", 0.3), ("Target", 0.14), ("End cue", 0.16),
                                           ("Feedback", 0.16), ("", 0.1))
_INTRO = ("A program runs timed stages in order (top to bottom). Each row:\n"
          "Min = length in minutes   Metric = what to train   Target = goal value\n"
          "End cue = sound when the stage ends   Feedback = per-stage sound")


def formula_label(formula) -> str:
    """A segment's metric as its button names it: a built-in's name, or a saved formula's name (its text if unnamed)."""
    if isinstance(formula, dict):
        return formula.get("name") or formula.get("formula", "Custom")
    return _PROGRAM_BUILTIN_LABELS.get(formula, str(formula))


def end_cue_label(end_cue: str | None) -> str:
    return "Warble" if end_cue == "warble" else "Chime"


def feedback_label(feedback: str) -> str:
    """A segment's feedback as its narrow button names it: Default (the global one), a source's name, or a file's."""
    if not feedback:
        return "Default"
    return SOURCE_LABELS.get(feedback) or os.path.basename(feedback)


def _int_or_zero(text: str) -> int:
    try:
        return int(text or 0)
    except (ValueError, TypeError):
        return 0


class SegmentRow:
    """One segment as the editor shows it: its minutes, metric, target, end cue and feedback, each picked in its own
    cell; `segment()` gives it back as a program stores it."""

    def __init__(self, editor: "ProgramEditor", segment: dict) -> None:
        self._editor = editor
        self.formula = segment.get("formula", "shamatha_score")
        self.end_cue = segment.get("end_sound")
        self.feedback = segment.get("feedback_sound") or ""
        self.box = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP_SM)
        font = F.capped(F.SMALL)  # six fixed columns across a phone
        minutes_w, formula_w, target_w, cue_w, feedback_w, delete_w = (width for _header, width in _COLUMNS)
        self.minutes_input = self._number_cell(segment.get("minutes", 10), font, minutes_w)
        self.formula_button = self._picker_cell(formula_label(self.formula), font, formula_w, self._pick_formula)
        self.target_input = self._number_cell(segment.get("target", 50), font, target_w)
        self.end_cue_button = self._picker_cell(end_cue_label(self.end_cue), font, cue_w, self._pick_end_cue)
        self.feedback_button = self._picker_cell(feedback_label(self.feedback), font, feedback_w, self._pick_feedback)
        delete = StyledButton(text="X", font_size=font, bg_color=C.BG_CARD, text_color=C.DANGER, size_hint_x=delete_w,
                              size_hint_y=None, height=dp(36))
        delete.bind(on_release=lambda *_a: editor.remove(self))
        self.box.add_widget(delete)

    def _number_cell(self, value: int, font, width: float) -> CenteredTextInput:
        cell = CenteredTextInput(text=str(value), input_filter="int", multiline=False, font_size=font,
                                 foreground_color=C.TEXT, background_color=C.BG_INPUT, size_hint_x=width)
        cell.bind(text=lambda *_a: self._editor.edited())
        self.box.add_widget(cell)
        return cell

    def _picker_cell(self, text: str, font, width: float, pick: Callable[[], None]) -> StyledButton:
        cell = StyledButton(text=text, font_size=font, bg_color=C.BG_CARD, text_color=C.TEXT, size_hint_x=width,
                            size_hint_y=None, height=dp(36))
        cell.bind(on_release=lambda *_a: pick())
        self.box.add_widget(cell)
        return cell

    @property
    def minutes(self) -> int:
        """The minutes as typed; 0 for none."""
        return _int_or_zero(self.minutes_input.text)

    def segment(self) -> dict:
        """The segment as a program stores it: at least a minute long, the end cue and feedback only when not the
        defaults."""
        seg: dict = {"minutes": max(self.minutes, 1), "target": _int_or_zero(self.target_input.text),
                     "formula": self.formula}
        if self.end_cue is not None:
            seg["end_sound"] = self.end_cue
        if self.feedback:
            seg["feedback_sound"] = self.feedback
        return seg

    def _pick_formula(self) -> None:
        """A built-in metric or any saved formula, read when the picker opens."""
        rows = []
        for key, label in PROGRAM_BUILTIN_FORMULAS:
            btn = StyledButton(text=label, font_size=F.BODY, bg_color=C.BG_CARD, text_color=C.TEXT, height=dp(40))
            btn.bind(on_release=lambda *_a, k=key: choose(k))
            rows.append(btn)
        for i, entry in enumerate(self._editor.saved_formulas()):
            name = saved_formula_label(i, entry)
            btn = StyledButton(text=name, font_size=F.BODY, bg_color=C.PRIMARY_DIM, height=dp(40))
            btn.bind(on_release=lambda *_a, n=name, f=entry.get("formula", ""): choose({"name": n, "formula": f}))
            rows.append(btn)
        cancel = cancel_button(font_size=F.BODY, height=dp(40))
        popup = make_scroll_popup("Choose metric / formula", rows, footer=cancel, row_h=dp(40))
        cancel.bind(on_release=lambda *_a: popup.dismiss())

        def choose(formula) -> None:
            self.formula = formula
            self.formula_button.text = formula_label(formula)
            logger.info(f"Segment formula -> {formula_label(formula)}")
            self._editor.edited()
            popup.dismiss()

        popup.open()

    def _pick_end_cue(self) -> None:
        open_source_picker("Segment end cue", _END_CUE_OPTIONS, self._set_end_cue)

    def _set_end_cue(self, end_cue: str | None) -> None:
        self.end_cue = end_cue
        self.end_cue_button.text = end_cue_label(end_cue)
        logger.info(f"Segment end-sound -> {end_cue or 'chime'}")
        self._editor.edited()

    def _pick_feedback(self) -> None:
        """Default (the global feedback sound), Rain, Tone, or a custom file, kept as its path."""
        open_sound_picker("Segment feedback sound", _SEGMENT_FEEDBACK_OPTIONS,
                          lambda source, path: self._set_feedback(path or source))

    def _set_feedback(self, feedback: str) -> None:
        self.feedback = feedback
        self.feedback_button.text = feedback_label(feedback)
        logger.info(f"Segment feedback -> {feedback or 'default'}")
        self._editor.edited()


class ProgramEditor:
    """Builds the editor into `box` and reports the user's edits through its hooks; a load shown through `show` reports
    nothing. A segment's metric can be any saved formula, read from `saved_formulas` when its picker opens."""

    on_change = Hook()  # (the edited segments)
    on_save = Hook()  # (the name typed)
    on_load = Hook()  # (the saved program's index)
    on_delete = Hook()  # (the saved program's index)

    def __init__(self, saved_formulas: Callable[[], list[dict]]) -> None:
        self.saved_formulas = saved_formulas
        self.rows: list[SegmentRow] = []
        self._showing = False
        # Its height tracks rows added after the fold opened (see the accordion's height note).
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=S.GAP_SM)
        self.box.bind(minimum_height=self.box.setter("height"))
        intro = ThemedLabel(text=_INTRO, font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint_y=None, halign="left",
                            valign="top")
        fit_height_to_text(intro)
        self.box.add_widget(intro)
        self._loaded_label = self._line("Loaded: (unsaved)", color=C.PRIMARY, bold=True)
        self.box.add_widget(_column_header())
        # Segment 1 at the top; a new one appends at the bottom, above the total.
        self._segments_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=S.GAP_SM)
        self._segments_box.bind(minimum_height=self._segments_box.setter("height"))
        self.box.add_widget(self._segments_box)
        self._total_label = self._line("Total: 0 min", color=C.TEXT, bold=True)
        add = StyledButton(text="+ Add Segment", font_size=F.SMALL, bg_color=C.PRIMARY_DIM, size_hint_y=None,
                           height=dp(34))
        add.bind(on_release=lambda *_a: self.add_segment())
        self.box.add_widget(add)
        self.box.add_widget(self._save_row())
        self._line("Saved Programs:", color=C.TEXT_SECONDARY)
        self._saved_box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(0), spacing=dp(2))
        self.box.add_widget(self._saved_box)

    def _line(self, text: str, **style) -> ThemedLabel:
        label = ThemedLabel(text=text, font_size=F.SMALL, size_hint_y=None, height=dp(22), halign="left",
                            valign="middle", **style)
        text_fills_box(label)
        self.box.add_widget(label)
        return label

    def _save_row(self) -> BoxLayout:
        row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP_SM)
        self._name_input = CenteredTextInput(text="", hint_text="program name", multiline=False, font_size=F.SMALL,
                                             foreground_color=C.TEXT, background_color=C.BG_INPUT, size_hint_x=0.7)
        self._save_button = StyledButton(text="Save", font_size=F.SMALL, bg_color=C.ACCENT, size_hint_x=0.3,
                                         size_hint_y=None, height=dp(36))
        self._save_button.bind(on_release=self._on_save_pressed)
        row.add_widget(self._name_input)
        row.add_widget(self._save_button)
        return row

    def show(self, segments: list[dict], name: str) -> None:
        """A loaded program: its rows rebuilt and its name in the field and the Loaded line, so a re-save overwrites
        it (nothing reported)."""
        self._showing = True
        try:
            for row in self.rows:
                self._segments_box.remove_widget(row.box)
            self.rows.clear()
            for seg in segments:
                self.add_segment(seg)
            self.edited()  # the total, for no segments too
        finally:
            self._showing = False
        self._name_input.text = name or ""
        self._loaded_label.text = f"Loaded: {name}" if name else "Loaded: (unsaved)"

    def add_segment(self, segment: dict | None = None) -> None:
        row = SegmentRow(self, segment or {})
        self.rows.append(row)
        self._segments_box.add_widget(row.box)
        if not self._showing:
            logger.info(f"Add segment -> {len(self.rows)} total")
        self.edited()

    def remove(self, row: SegmentRow) -> None:
        if row in self.rows:
            self.rows.remove(row)
        self._segments_box.remove_widget(row.box)
        logger.info(f"Remove segment -> {len(self.rows)} remaining")
        self.edited()

    def edited(self) -> None:
        """A row added, removed or changed: the total follows, and the user's edit is reported."""
        self._total_label.text = f"Total: {sum(row.minutes for row in self.rows)} min"
        if not self._showing:
            self.on_change(self.segments())

    def segments(self) -> list[dict]:
        return [row.segment() for row in self.rows]

    def _on_save_pressed(self, *_args) -> None:
        name = self._name_input.text.strip()
        logger.info(f"Save program pressed: name={name!r}")
        self.on_save(name)

    def confirm_saved(self) -> None:
        """A success cue on Save. Main thread only."""
        self._save_button.flash_confirm("Saved", icon=Icons.CHECK, confirm_color=C.SHAMATHA)

    def show_saved(self, programs: list[dict]) -> None:
        """The saved programs: [{name, segments}, ...]."""
        fill_saved_list(self._saved_box, programs, saved_program_label, self._on_load_pressed, self._on_delete_pressed)

    def _on_load_pressed(self, index: int) -> None:
        logger.info(f"Load saved program #{index}")
        self.on_load(index)

    def _on_delete_pressed(self, index: int) -> None:
        logger.info(f"Delete saved program #{index}")
        self.on_delete(index)


def _column_header() -> BoxLayout:
    """The columns' names, each as wide as its cells."""
    header = BoxLayout(size_hint_y=None, height=dp(20), spacing=S.GAP_SM)
    for text, width in _COLUMNS:
        label = ThemedLabel(text=text, font_size=F.capped(F.TINY), bold=True, color=C.TEXT_MUTED, size_hint_x=width,
                            halign="center", valign="middle")
        text_fills_box(label)
        header.add_widget(label)
    return header
