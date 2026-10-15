"""Settings → Timer / Program: the simple timer, the program editor with its saved programs, and the timer end
sound."""
import os
from collections.abc import Callable
from typing import Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.slider import Slider

from app.logger import logger
from app.ui.settings_sections.common import (
    SOURCE_LABELS,
    checkbox_row,
    fill_saved_list,
    open_audio_file_chooser,
    open_source_picker,
    saved_program_label,
    source_label,
)
from app.ui.theme import (
    C,
    CenteredTextInput,
    F,
    Icons,
    PresetRow,
    S,
    StyledButton,
    ThemedLabel,
    cancel_button,
    fit_height_to_text,
    make_scroll_popup,
)

# Built-in metric keys offered in the per-segment formula picker. These are the
# REAL metric dict keys — native_attention/native_meditation, NOT ns_*.
PROGRAM_BUILTIN_FORMULAS: list[tuple[str, str]] = [
    ("shamatha_score", "Shamatha"),
    ("meditation_score", "Meditation"),
    ("native_attention", "NS Attention"),
    ("native_meditation", "NS Meditation"),
]
_PROGRAM_BUILTIN_LABELS: dict[str, str] = dict(PROGRAM_BUILTIN_FORMULAS)
_TIMER_SOUND_OPTIONS: tuple[tuple[str, str], ...] = (("Default bell", ""), ("Custom file...", "custom"))
# A program segment's feedback: "" inherits the global feedback sound.
_SEGMENT_FEEDBACK_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Default (use global)", ""), ("Rain", "noise"), ("Tone", "tone"), ("Custom file...", "custom"),
)


class TimerSection:
    """Builds the section's content into `section` and reports the user's actions through its callbacks. A segment's
    formula can be any saved formula, read from `saved_formulas` when its picker opens."""

    def __init__(self, section, *, saved_formulas: Callable[[], list[dict]]) -> None:
        self._saved_formulas = saved_formulas
        self._on_timer_sound_change: Optional[Callable] = None
        self._on_test_timer_sound: Optional[Callable] = None
        self._on_stop_timer_sound: Optional[Callable] = None
        self._timer_sound_test_playing: bool = False
        self._on_program_mode_cb: Optional[Callable] = None
        self._on_program_changed_cb: Optional[Callable] = None
        self._on_program_save_cb: Optional[Callable] = None
        self._on_program_load_cb: Optional[Callable] = None
        self._on_program_delete_cb: Optional[Callable] = None
        self._program_mode: str = "simple"
        self._segment_rows: list = []
        self._loading_program: bool = False
        self._timer_sound_path: str = ""  # "" is the default bell
        self._build(section)

    def _build(self, section) -> None:

        # "Enable Timer" is a simple-mode concept (program mode forces the timer
        # on), so it lives inside _simple_box below and hides in program mode.
        timer_toggle_row, self._timer_enable_cb = checkbox_row("Enable Timer", S.ROW_SM, active=False)

        # Mode: Simple | Program segmented toggle (placed before the mode-specific
        # content so the layout reads top-down: mode -> content -> sound).
        mode_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        mode_row.add_widget(ThemedLabel(
            text="Mode:", font_size=F.BODY, color=C.TEXT_SECONDARY,
            size_hint_x=0.25, halign="left", valign="middle",
        ))
        mode_btn_box = BoxLayout(size_hint_x=0.75, spacing=S.GAP)
        self._program_mode_buttons: list[StyledButton] = []
        for mode_key, mode_label in (("simple", "Simple"), ("program", "Program")):
            btn = StyledButton(
                text=mode_label,
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(28),
                bg_color=C.ACCENT if mode_key == "simple" else C.BG_CARD,
            )
            btn._mode_key = mode_key
            btn.bind(on_release=self._on_program_mode_pressed)
            mode_btn_box.add_widget(btn)
            self._program_mode_buttons.append(btn)
        mode_row.add_widget(mode_btn_box)
        section.add_widget(mode_row)

        # Mode-content host: holds EITHER the simple box OR the program box. The
        # inactive box is fully removed from the tree (not just hidden) — a
        # zero-height-but-present container lets its children overflow and, when
        # disabled, swallow taps aimed at the controls around it.
        self._mode_content_box = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=S.GAP_SM,
        )
        self._mode_content_box.bind(
            minimum_height=self._mode_content_box.setter("height")
        )
        section.add_widget(self._mode_content_box)

        # --- Simple-mode controls: duration slider row + presets ---
        self._simple_box = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=S.GAP,
        )
        self._simple_box.bind(minimum_height=self._simple_box.setter("height"))
        self._simple_box.add_widget(timer_toggle_row)  # Enable Timer (simple mode only)
        timer_dur_row = BoxLayout(size_hint_y=None, height=S.ROW_SM, spacing=S.GAP)
        timer_dur_lbl = ThemedLabel(
            text="Duration:", font_size=F.BODY, color=C.TEXT_SECONDARY,
            size_hint_x=0.25, halign="left",
        )
        timer_dur_lbl.bind(size=timer_dur_lbl.setter("text_size"))
        self._timer_duration_slider = Slider(
            min=1, max=120, value=20, step=1, size_hint_x=0.55,
        )
        self._timer_duration_label = ThemedLabel(
            text="20 min", font_size=F.BODY, bold=True, color=C.TEXT,
            size_hint_x=0.2,
        )
        self._timer_duration_slider.bind(
            value=lambda inst, val: setattr(
                self._timer_duration_label, "text", f"{int(val)} min"
            )
        )
        timer_dur_row.add_widget(timer_dur_lbl)
        timer_dur_row.add_widget(self._timer_duration_slider)
        timer_dur_row.add_widget(self._timer_duration_label)
        self._simple_box.add_widget(timer_dur_row)

        timer_presets = PresetRow(
            items=[("5m", 5), ("10m", 10), ("15m", 15), ("20m", 20),
                   ("30m", 30), ("1h", 60), ("1h30", 90), ("2h", 120)],
            callback=lambda v: setattr(self._timer_duration_slider, "value", v),
        )
        self._simple_box.add_widget(timer_presets)

        # Program editor (dynamic vertical box; height tracks rows added after
        # the section is opened — see _AccordionSection height note). Built once,
        # swapped into _mode_content_box by set_program_mode.
        self._program_box = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=S.GAP_SM,
        )
        self._program_box.bind(
            minimum_height=self._program_box.setter("height")
        )

        self._program_total_label = ThemedLabel(
            text="Total: 0 min",
            font_size=F.SMALL, bold=True, color=C.TEXT,
            size_hint_y=None, height=dp(22),
            halign="left", valign="middle",
        )
        self._program_total_label.bind(
            size=self._program_total_label.setter("text_size")
        )

        # At-a-glance "which program is loaded" indicator at the top of the editor.
        self._program_loaded_label = ThemedLabel(
            text="Loaded: (unsaved)",
            font_size=F.SMALL, bold=True, color=C.PRIMARY,
            size_hint_y=None, height=dp(22),
            halign="left", valign="middle",
        )
        self._program_loaded_label.bind(
            size=self._program_loaded_label.setter("text_size")
        )

        self._add_segment_btn = StyledButton(
            text="+ Add Segment",
            font_size=F.SMALL,
            bg_color=C.PRIMARY_DIM,
            size_hint_y=None,
            height=dp(34),
        )
        self._add_segment_btn.bind(
            on_release=lambda *_a: self._add_segment_row()
        )

        program_save_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=S.GAP_SM,
        )
        self._program_name_input = CenteredTextInput(
            text="",
            hint_text="program name",
            multiline=False,
            font_size=F.SMALL,
            foreground_color=C.TEXT,
            background_color=C.BG_INPUT,
            size_hint_x=0.7,
        )
        self._program_save_btn = StyledButton(
            text="Save",
            font_size=F.SMALL,
            bg_color=C.ACCENT,
            size_hint_x=0.3,
            size_hint_y=None,
            height=dp(36),
        )
        self._program_save_btn.bind(on_release=self._on_program_save_pressed)
        program_save_row.add_widget(self._program_name_input)
        program_save_row.add_widget(self._program_save_btn)

        saved_programs_label = ThemedLabel(
            text="Saved Programs:",
            font_size=F.SMALL, color=C.TEXT_SECONDARY,
            size_hint_y=None, height=dp(22),
            halign="left", valign="middle",
        )
        saved_programs_label.bind(
            size=saved_programs_label.setter("text_size")
        )
        self._saved_programs_box = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(0), spacing=dp(2),
        )

        # Segment rows live in their own box at the top so they read in program
        # order (segment 1 at the top) and new rows append at the bottom, above
        # the fixed total/add/save/list block.
        self._segments_box = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=S.GAP_SM,
        )
        self._segments_box.bind(
            minimum_height=self._segments_box.setter("height")
        )
        # What the editor is + what each cell means (the rows are otherwise cryptic).
        program_intro = ThemedLabel(
            text=(
                "A program runs timed stages in order (top to bottom). Each row:\n"
                "Min = length in minutes   Metric = what to train   Target = goal value\n"
                "End cue = sound when the stage ends   Feedback = per-stage sound"
            ),
            font_size=F.SMALL, color=C.TEXT_SECONDARY,
            size_hint_y=None,
            halign="left", valign="top",
        )
        fit_height_to_text(program_intro)

        # Column header aligned to the segment-row cells (same size_hint_x ratios).
        segments_header = BoxLayout(size_hint_y=None, height=dp(20), spacing=S.GAP_SM)
        for _lbl, _w in (("Min", 0.16), ("Metric", 0.3), ("Target", 0.14),
                         ("End cue", 0.16), ("Feedback", 0.16), ("", 0.1)):
            col = ThemedLabel(
                text=_lbl, font_size=F.capped(F.TINY), bold=True, color=C.TEXT_MUTED,
                size_hint_x=_w, halign="center", valign="middle",
            )
            col.bind(size=col.setter("text_size"))
            segments_header.add_widget(col)

        self._program_box.add_widget(program_intro)
        self._program_box.add_widget(self._program_loaded_label)
        self._program_box.add_widget(segments_header)
        self._program_box.add_widget(self._segments_box)
        self._program_box.add_widget(self._program_total_label)
        self._program_box.add_widget(self._add_segment_btn)
        self._program_box.add_widget(program_save_row)
        self._program_box.add_widget(saved_programs_label)
        self._program_box.add_widget(self._saved_programs_box)

        # Timer-end sound (shared by both modes): picked like the feedback sounds, plus Test.
        timer_sound_lbl = ThemedLabel(
            text="Timer End Sound (optional)",
            font_size=F.SMALL,
            color=C.TEXT_SECONDARY,
            size_hint_y=None, height=dp(20),
            halign="left",
        )
        timer_sound_lbl.bind(size=timer_sound_lbl.setter("text_size"))
        section.add_widget(timer_sound_lbl)

        timer_sound_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=S.GAP_SM,
        )
        self._timer_sound_btn = StyledButton(
            text=self._timer_sound_label(self._timer_sound_path),
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
            text_color=C.TEXT,
            size_hint_x=0.75,
            size_hint_y=None,
            height=dp(36),
        )
        self._timer_sound_btn.bind(on_release=lambda *_a: open_source_picker(
            "Timer end sound", _TIMER_SOUND_OPTIONS, self._choose_timer_sound))
        self._timer_sound_test_btn = StyledButton(
            text="Test",
            font_size=F.SMALL,
            bg_color=C.PRIMARY_DIM,
            size_hint_x=0.25,
            size_hint_y=None,
            height=dp(36),
        )
        self._timer_sound_test_btn.bind(on_release=self._on_timer_sound_test)
        timer_sound_row.add_widget(self._timer_sound_btn)
        timer_sound_row.add_widget(self._timer_sound_test_btn)
        section.add_widget(timer_sound_row)

        # Start in Simple mode (simple controls swapped into the content host).
        self.set_program_mode("simple")

    @property
    def program_mode(self) -> str:
        return self._program_mode

    def set_program_mode_callback(self, cb: Callable) -> None:
        self._on_program_mode_cb = cb

    def set_program_changed_callback(self, cb: Callable) -> None:
        self._on_program_changed_cb = cb

    def set_program_save_callback(self, cb: Callable) -> None:
        self._on_program_save_cb = cb

    def set_program_load_callback(self, cb: Callable) -> None:
        self._on_program_load_cb = cb

    def set_program_delete_callback(self, cb: Callable) -> None:
        self._on_program_delete_cb = cb

    def set_program_mode(self, mode: str) -> None:
        """Set toggle + show/hide widgets. Does NOT fire the mode callback."""
        mode = "program" if mode == "program" else "simple"
        self._program_mode = mode
        for btn in self._program_mode_buttons:
            btn.bg_color = C.ACCENT if btn._mode_key == mode else C.BG_CARD
        # Swap the active box into the content host. The inactive box is fully
        # detached (no geometry, no disabled-overlap that would eat taps).
        self._mode_content_box.clear_widgets()
        self._mode_content_box.add_widget(
            self._program_box if mode == "program" else self._simple_box
        )

    def _on_program_mode_pressed(self, btn) -> None:
        mode = getattr(btn, "_mode_key", "simple")
        logger.info(f"Timer mode -> {mode}")
        self.set_program_mode(mode)
        if self._on_program_mode_cb:
            self._on_program_mode_cb(mode)

    def _on_program_save_pressed(self, *_args) -> None:
        name = self._program_name_input.text.strip()
        logger.info(f"Save program pressed: name={name!r}")
        if self._on_program_save_cb:
            self._on_program_save_cb(name)

    def confirm_program_saved(self) -> None:
        """Flash a success cue on the program Save button (issue #33 E). Main-thread only."""
        btn = getattr(self, "_program_save_btn", None)
        if btn is not None:
            btn.flash_confirm("Saved", icon=Icons.CHECK, confirm_color=C.SHAMATHA)

    def _on_program_load_pressed(self, idx: int) -> None:
        logger.info(f"Load saved program #{idx}")
        if self._on_program_load_cb:
            self._on_program_load_cb(idx)

    def _on_program_delete_pressed(self, idx: int) -> None:
        logger.info(f"Delete saved program #{idx}")
        if self._on_program_delete_cb:
            self._on_program_delete_cb(idx)

    def set_saved_programs(self, programs: list[dict]) -> None:
        """Populate the Load list. programs: [{name, segments}, ...]."""
        fill_saved_list(self._saved_programs_box, programs, saved_program_label,
                        self._on_program_load_pressed, self._on_program_delete_pressed)

    def _add_segment_row(self, segment: Optional[dict] = None) -> None:
        """Append one editor row (used by Add button and load_program)."""
        segment = segment or {}
        minutes = segment.get("minutes", 10)
        target = segment.get("target", 50)
        formula = segment.get("formula", "shamatha_score")
        end_sound = segment.get("end_sound")
        feedback_sound = segment.get("feedback_sound") or ""

        row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP_SM)

        cell_font = F.capped(F.SMALL)  # six fixed columns across a phone
        duration_in = CenteredTextInput(
            text=str(minutes), input_filter="int", multiline=False,
            font_size=cell_font, foreground_color=C.TEXT,
            background_color=C.BG_INPUT,
            size_hint_x=0.16,
        )
        formula_btn = StyledButton(
            text=self._formula_label(formula),
            font_size=cell_font, bg_color=C.BG_CARD, text_color=C.TEXT,
            size_hint_x=0.3, size_hint_y=None, height=dp(36),
        )
        target_in = CenteredTextInput(
            text=str(target), input_filter="int", multiline=False,
            font_size=cell_font, foreground_color=C.TEXT,
            background_color=C.BG_INPUT,
            size_hint_x=0.14,
        )
        end_sound_btn = StyledButton(
            text="Warble" if end_sound == "warble" else "Chime",
            font_size=cell_font, bg_color=C.BG_CARD, text_color=C.TEXT,
            size_hint_x=0.16, size_hint_y=None, height=dp(36),
        )
        feedback_btn = StyledButton(
            text=self._feedback_seg_label(feedback_sound), font_size=cell_font,
            bg_color=C.BG_CARD, text_color=C.TEXT, size_hint_x=0.16,
            size_hint_y=None, height=dp(36),
        )
        delete_btn = StyledButton(
            text="X", font_size=cell_font, bg_color=C.BG_CARD,
            text_color=C.DANGER, size_hint_x=0.1, size_hint_y=None,
            height=dp(36),
        )

        row._duration_in = duration_in
        row._target_in = target_in
        row._formula = formula
        row._end_sound = end_sound
        row._feedback_sound = feedback_sound
        row._feedback_btn = feedback_btn
        row._formula_btn = formula_btn

        duration_in.bind(text=lambda *_a: self._on_segment_edited())
        target_in.bind(text=lambda *_a: self._on_segment_edited())
        formula_btn.bind(
            on_release=lambda *_a, r=row: self._open_segment_formula_picker(r)
        )
        end_sound_btn.bind(
            on_release=lambda *_a, r=row, b=end_sound_btn: self._open_segment_end_sound_picker(r, b)
        )
        feedback_btn.bind(
            on_release=lambda *_a, r=row, b=feedback_btn: self._open_segment_feedback_picker(r, b)
        )
        delete_btn.bind(
            on_release=lambda *_a, r=row: self._remove_segment_row(r)
        )

        row.add_widget(duration_in)
        row.add_widget(formula_btn)
        row.add_widget(target_in)
        row.add_widget(end_sound_btn)
        row.add_widget(feedback_btn)
        row.add_widget(delete_btn)

        self._segment_rows.append(row)
        # Default add into the dedicated segments box: a vertical BoxLayout
        # renders children in insertion order top→bottom, so segment 1 stays at
        # the top and each new row appends at the bottom.
        self._segments_box.add_widget(row)

        if not self._loading_program:
            logger.info(f"Add segment -> {len(self._segment_rows)} total")
        self._update_program_total()
        self._emit_program_changed()

    def _remove_segment_row(self, row) -> None:
        if row in self._segment_rows:
            self._segment_rows.remove(row)
        self._segments_box.remove_widget(row)
        logger.info(f"Remove segment -> {len(self._segment_rows)} remaining")
        self._update_program_total()
        self._emit_program_changed()

    def _set_segment_end_sound(self, row, btn, value) -> None:
        row._end_sound = value
        btn.text = "Warble" if value == "warble" else "Chime"
        logger.info(f"Segment end-sound -> {value or 'chime'}")
        self._emit_program_changed()

    def _open_segment_end_sound_picker(self, row, btn) -> None:
        """Pick a segment's end cue: Chime (default) or Warble."""
        open_source_picker("Segment end cue", (("Chime", None), ("Warble", "warble")),
                                 lambda v: self._set_segment_end_sound(row, btn, v))

    def _feedback_seg_label(self, value) -> str:
        """A segment's feedback source as its button shows it: Default (the global one), a source's name, or a file."""
        if not value:
            return "Default"
        return SOURCE_LABELS.get(value) or os.path.basename(value)

    def _set_segment_feedback(self, row, btn, value: str) -> None:
        row._feedback_sound = value
        btn.text = self._feedback_seg_label(value)
        logger.info(f"Segment feedback -> {value or 'default'}")
        self._emit_program_changed()

    def _open_segment_feedback_picker(self, row, btn) -> None:
        """Pick a segment's feedback source: Default (inherit global), Rain, Tone, or a custom file."""
        def choose(value: str) -> None:
            if value == "custom":
                open_audio_file_chooser(lambda p: self._set_segment_feedback(row, btn, p),
                                        title="Segment feedback sound file")
            else:
                self._set_segment_feedback(row, btn, value)

        open_source_picker("Segment feedback sound", _SEGMENT_FEEDBACK_OPTIONS, choose)

    def _formula_label(self, formula) -> str:
        if isinstance(formula, dict):
            return formula.get("name") or formula.get("formula", "Custom")
        return _PROGRAM_BUILTIN_LABELS.get(formula, str(formula))

    def _open_segment_formula_picker(self, row) -> None:
        def _choose(value):
            row._formula = value
            row._formula_btn.text = self._formula_label(value)
            logger.info(f"Segment formula -> {self._formula_label(value)}")
            self._emit_program_changed()
            popup.dismiss()

        rows = []
        for key, label in PROGRAM_BUILTIN_FORMULAS:
            btn = StyledButton(text=label, font_size=F.BODY, bg_color=C.BG_CARD, text_color=C.TEXT, height=dp(40))
            btn.bind(on_release=lambda *_a, k=key: _choose(k))
            rows.append(btn)

        for entry in self._saved_formulas():
            name = entry.get("name") or entry.get("formula", "")[:30]
            formula = entry.get("formula", "")
            btn = StyledButton(text=name, font_size=F.BODY, bg_color=C.PRIMARY_DIM, height=dp(40))
            btn.bind(
                on_release=lambda *_a, n=name, f=formula: _choose(
                    {"name": n, "formula": f}
                )
            )
            rows.append(btn)

        cancel = cancel_button(font_size=F.BODY, height=dp(40))
        popup = make_scroll_popup("Choose metric / formula", rows, footer=cancel, row_h=dp(40))
        cancel.bind(on_release=lambda *_a: popup.dismiss())
        popup.open()

    def _on_segment_edited(self, *_args) -> None:
        self._update_program_total()
        self._emit_program_changed()

    def _update_program_total(self) -> None:
        total = 0
        for row in self._segment_rows:
            try:
                total += int(row._duration_in.text or 0)
            except (ValueError, TypeError):
                pass
        self._program_total_label.text = f"Total: {total} min"

    def get_program_segments(self) -> list[dict]:
        """Serialize the editor rows to the program-segment dict format."""
        segments: list[dict] = []
        for row in self._segment_rows:
            try:
                minutes = int(row._duration_in.text or 0)
            except (ValueError, TypeError):
                minutes = 0
            if minutes < 1:
                minutes = 1
            try:
                target = int(row._target_in.text or 0)
            except (ValueError, TypeError):
                target = 0
            seg: dict = {"minutes": minutes, "target": target, "formula": row._formula}
            if row._end_sound is not None:
                seg["end_sound"] = row._end_sound
            if getattr(row, "_feedback_sound", ""):
                seg["feedback_sound"] = row._feedback_sound
            segments.append(seg)
        return segments

    def _emit_program_changed(self) -> None:
        if self._loading_program:
            return
        if self._on_program_changed_cb:
            self._on_program_changed_cb(self.get_program_segments())

    def load_program(self, segments: list[dict], mode: str) -> None:
        """Clear + rebuild rows from segments; set mode. Does NOT fire changed."""
        self._loading_program = True
        try:
            for row in list(self._segment_rows):
                self._segments_box.remove_widget(row)
            self._segment_rows.clear()
            for seg in segments:
                self._add_segment_row(seg)
            self.set_program_mode(mode)
            self._update_program_total()
        finally:
            self._loading_program = False

    def set_program_name(self, name: str) -> None:
        """Reflect the loaded program's name (top label + name field, so a
        re-save overwrites it)."""
        self._program_name_input.text = name or ""
        self._program_loaded_label.text = f"Loaded: {name}" if name else "Loaded: (unsaved)"

    @property
    def timer_sound_path(self) -> str:
        return self._timer_sound_path

    @timer_sound_path.setter
    def timer_sound_path(self, value: str) -> None:
        """Reflect a loaded timer sound on its button (no callback)."""
        self._timer_sound_path = value or ""
        self._timer_sound_btn.text = self._timer_sound_label(self._timer_sound_path)

    def _timer_sound_label(self, path: str) -> str:
        return source_label("custom", path) if path else "Default bell"

    def _choose_timer_sound(self, value: str) -> None:
        if value == "custom":
            open_audio_file_chooser(self._apply_timer_sound, title="Timer end sound file")
            return
        self._apply_timer_sound("")

    def _apply_timer_sound(self, path: str) -> None:
        self.timer_sound_path = path
        if self._on_timer_sound_change:
            self._on_timer_sound_change(path)

    def set_timer_sound_change_callback(self, callback: Callable) -> None:
        self._on_timer_sound_change = callback

    def set_test_timer_sound_callback(self, callback: Callable) -> None:
        self._on_test_timer_sound = callback

    def set_stop_timer_sound_callback(self, callback: Callable) -> None:
        self._on_stop_timer_sound = callback

    def _on_timer_sound_test(self, *_args) -> None:
        """Toggle play/stop for the test sound — long custom files would
        otherwise keep playing with no UI control to interrupt."""
        if self._timer_sound_test_playing:
            if self._on_stop_timer_sound:
                self._on_stop_timer_sound()
            self.notify_timer_sound_test_ended()
        else:
            if self._on_test_timer_sound:
                self._on_test_timer_sound()
            self._timer_sound_test_playing = True
            self._timer_sound_test_btn.text = "Stop"

    def notify_timer_sound_test_ended(self) -> None:
        """Called by app_manager when the test playback ends naturally
        (Sound.on_stop fires) so the button text reverts."""
        self._timer_sound_test_playing = False
        self._timer_sound_test_btn.text = "Test"

    @property
    def timer_enabled(self) -> bool:
        return self._timer_enable_cb.active

    @timer_enabled.setter
    def timer_enabled(self, value: bool):
        self._timer_enable_cb.active = value

    @property
    def timer_minutes(self) -> int:
        return int(self._timer_duration_slider.value)

    @timer_minutes.setter
    def timer_minutes(self, value: int):
        self._timer_duration_slider.value = value
        self._timer_duration_label.text = f"{value} min"
