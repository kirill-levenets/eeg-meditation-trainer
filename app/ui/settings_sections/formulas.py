"""Settings → Custom Formula: three named formula slots with Apply and Save, the saved formulas with their export, and
the formula syntax reference."""
from collections.abc import Callable
from typing import Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.ui.settings_sections.common import fill_saved_list, saved_formula_label
from app.ui.theme import (
    C,
    CenteredTextInput,
    F,
    S,
    StyledButton,
    ThemedLabel,
    fit_height_to_text,
)


class FormulaSection:
    """Builds the section's content into `section` and reports the user's actions through its callbacks."""

    def __init__(self, section) -> None:
        self._on_formula_slot_change: Optional[Callable] = None
        self._on_save_formula: Optional[Callable] = None
        self._on_load_formula: Optional[Callable] = None
        self._on_delete_formula: Optional[Callable] = None
        self._on_export_formulas: Optional[Callable] = None
        self.saved: list[dict] = []  # the saved formulas, which a program segment can also pick
        self._build(section)

    def _build(self, section) -> None:
        formula_desc = ThemedLabel(
            text=(
                "Enter a Python-style formula to track as an extra metric.\n"
                "Leave empty to disable."
            ),
            font_size=F.SMALL,
            size_hint_y=None,
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        fit_height_to_text(formula_desc)
        section.add_widget(formula_desc)

        # Three named formula slots, each with name + formula inputs,
        # Apply/Save buttons, and a status label.
        self._formula_inputs: list[CenteredTextInput] = []
        self._formula_name_inputs: list[CenteredTextInput] = []
        self._formula_statuses: list[ThemedLabel] = []
        for i in range(3):
            slot_header = ThemedLabel(
                text=f"Formula {i + 1}",
                font_size=F.SMALL,
                bold=True,
                size_hint_y=None,
                height=dp(20),
                color=C.TEXT_SECONDARY,
                halign="left",
            )
            slot_header.bind(size=slot_header.setter("text_size"))
            section.add_widget(slot_header)

            name_input = CenteredTextInput(
                text="",
                hint_text=f"name (default Custom {i + 1})",
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(36),
                multiline=False,
                background_color=C.BG_INPUT,
                foreground_color=C.TEXT,
            )
            name_input.bind(on_text_validate=lambda _w, idx=i: self._submit_slot(idx))
            self._formula_name_inputs.append(name_input)
            section.add_widget(name_input)

            formula_input = CenteredTextInput(
                text="",
                hint_text="e.g. alpha1 / (beta1 + 1)",  # one line on a 360 dp phone at the largest text size
                font_size=F.BODY,
                size_hint_y=None,
                height=dp(40),
                multiline=False,
                background_color=C.BG_INPUT,
                foreground_color=C.TEXT,
            )
            formula_input.bind(
                on_text_validate=lambda _w, idx=i: self._submit_slot(idx)
            )
            self._formula_inputs.append(formula_input)
            section.add_widget(formula_input)

            formula_btns = BoxLayout(
                size_hint_y=None, height=dp(34), spacing=S.GAP_SM
            )
            apply_btn = StyledButton(
                text="Apply",
                font_size=F.BODY,
                bg_color=C.PRIMARY,
                size_hint_y=None,
                height=dp(34),
            )
            apply_btn.bind(on_release=lambda _w, idx=i: self._submit_slot(idx))
            formula_btns.add_widget(apply_btn)

            save_btn = StyledButton(
                text="Save",
                font_size=F.BODY,
                bg_color=C.ACCENT,
                size_hint_y=None,
                height=dp(34),
            )
            save_btn.bind(on_release=lambda _w, idx=i: self._save_slot(idx))
            formula_btns.add_widget(save_btn)
            section.add_widget(formula_btns)

            status = ThemedLabel(
                text="",
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(20),
                color=C.ACCENT,
                halign="left",
            )
            status.bind(size=status.setter("text_size"))
            self._formula_statuses.append(status)
            section.add_widget(status)

        # Saved formulas header with export button
        saved_header = BoxLayout(size_hint_y=None, height=dp(26), spacing=S.GAP_SM)
        saved_label = ThemedLabel(
            text="Saved Formulas:",
            font_size=F.SMALL,
            size_hint_x=0.6,
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        saved_label.bind(size=saved_label.setter("text_size"))
        saved_header.add_widget(saved_label)

        export_formulas_btn = StyledButton(
            text="Export to .txt",
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            size_hint_x=0.4,
            size_hint_y=None,
            height=dp(26),
        )
        export_formulas_btn.bind(on_release=self._on_export_formulas_pressed)
        saved_header.add_widget(export_formulas_btn)
        section.add_widget(saved_header)

        self._saved_formulas_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(0),
            spacing=dp(2),
        )
        section.add_widget(self._saved_formulas_box)

        examples = ThemedLabel(
            text=(
                "Examples:\n"
                "  (alpha1 + alpha2) / (beta1 + beta2 + 1)\n"
                "  sqrt(alpha_norm) * 100\n"
                "  meditation_score * 0.7 + shamatha_score * 0.3\n"
                "  avg(alpha1 + beta1, 10)\n"
                "  avg(sqrt(alpha_norm) * 100, 30)\n"
                "  avg(meditation_score, 20) - avg(distraction, 20)"
            ),
            font_size=F.BODY,
            size_hint_y=None,
            color=C.TEXT_MUTED,
            halign="left",
            valign="top",
        )
        fit_height_to_text(examples)
        section.add_widget(examples)

        ref = ThemedLabel(
            text=(
                "Bands: alpha1 alpha2 beta1 beta2\n"
                "  gamma1 gamma2 theta delta\n"
                "Combined: alpha beta gamma\n"
                "Sqrt-relative: s_alpha1 s_alpha2 s_beta1\n"
                "  s_beta2 s_theta s_delta\n"
                "Normalized: alpha_norm beta_norm gamma_norm\n"
                "  theta_norm delta_norm total_power\n"
                "Metrics: meditation_score shamatha_score\n"
                "  distraction sinking subtle_distraction\n"
                "  stability calmness\n"
                "  native_attention native_meditation\n"
                "Functions: sqrt abs log log10 log2 exp pow\n"
                "  min max sin cos tanh\n"
                "Windowed: avg(expr, N) \u2014 mean of last N ticks\n"
                "  N = 1..600 (at 2Hz: 10=5s, 60=30s, 120=1min)"
            ),
            font_size=F.SMALL,
            size_hint_y=None,
            color=C.TEXT_MUTED,
            halign="left",
            valign="top",
        )
        fit_height_to_text(ref)
        section.add_widget(ref)

    def _submit_slot(self, idx: int) -> None:
        if self._on_formula_slot_change:
            name = self._formula_name_inputs[idx].text.strip()
            self._on_formula_slot_change(idx, name, self._formula_inputs[idx].text.strip())

    def _save_slot(self, idx: int) -> None:
        """Save a slot's formula to the library, seeding the entry from its name."""
        if self._on_save_formula:
            self._on_save_formula(idx, self._formula_name_inputs[idx].text.strip(),
                                  self._formula_inputs[idx].text.strip())

    def set_formula_slot_status(self, idx: int, text: str, is_error: bool = False) -> None:
        self._formula_statuses[idx].text = text
        self._formula_statuses[idx].color = C.DANGER if is_error else C.ACCENT

    def set_formula_slot_callback(self, callback: Callable) -> None:
        self._on_formula_slot_change = callback

    def set_formula_slot(self, idx: int, name: str, formula: str) -> None:
        """Reflect a programmatic slot change (load/restore) in the inputs."""
        self._formula_name_inputs[idx].text = name
        self._formula_inputs[idx].text = formula

    def set_save_formula_callback(self, callback: Callable) -> None:
        self._on_save_formula = callback

    def set_load_formula_callback(self, callback: Callable) -> None:
        self._on_load_formula = callback

    def set_delete_formula_callback(self, callback: Callable) -> None:
        self._on_delete_formula = callback

    def set_export_formulas_callback(self, callback: Callable) -> None:
        self._on_export_formulas = callback

    def _on_export_formulas_pressed(self, *args) -> None:
        if self._on_export_formulas:
            self._on_export_formulas()

    def _on_load_formula_pressed(self, idx: int) -> None:
        if self._on_load_formula:
            self._on_load_formula(idx)

    def _on_delete_formula_pressed(self, idx: int) -> None:
        if self._on_delete_formula:
            self._on_delete_formula(idx)

    def populate_saved_formulas(self, formulas) -> None:
        """Update the saved formulas list. formulas: [{name, formula}, ...]"""
        self.saved = list(formulas)
        fill_saved_list(self._saved_formulas_box, formulas, saved_formula_label,
                        self._on_load_formula_pressed, self._on_delete_formula_pressed)
