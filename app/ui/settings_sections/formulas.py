"""Settings → Custom Formula: three named formula slots with Apply and Save, the saved formulas with their export, and
the formula syntax reference."""
from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.metrics.formula_slots import FORMULA_KEYS
from app.ui.hooks import Hook
from app.ui.settings_sections.common import fill_saved_list, saved_formula_label
from app.ui.theme import C, CenteredTextInput, F, S, ThemedLabel, fit_height_to_text, text_fills_box
from app.ui.widgets.styled_button import StyledButton

_EXAMPLES = ("Examples:\n"
             "  (alpha1 + alpha2) / (beta1 + beta2 + 1)\n"
             "  sqrt(alpha_norm) * 100\n"
             "  meditation_score * 0.7 + shamatha_score * 0.3\n"
             "  avg(alpha1 + beta1, 10)\n"
             "  avg(sqrt(alpha_norm) * 100, 30)\n"
             "  avg(meditation_score, 20) - avg(distraction, 20)")
_REFERENCE = ("Bands: alpha1 alpha2 beta1 beta2\n"
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
              "  N = 1..600 (at 2Hz: 10=5s, 60=30s, 120=1min)")


class FormulaSlot:
    """One formula as Settings edits it: its name and expression, Apply and Save, and a line saying how the last
    one went."""

    def __init__(self, section, index: int, apply: Callable[[], None], save: Callable[[], None]) -> None:
        header = ThemedLabel(text=f"Formula {index + 1}", font_size=F.SMALL, bold=True, size_hint_y=None, height=dp(20),
                             color=C.TEXT_SECONDARY, halign="left")
        text_fills_box(header)
        section.add_widget(header)
        self._name_input = CenteredTextInput(text="", hint_text=f"name (default Custom {index + 1})", font_size=F.SMALL,
                                             size_hint_y=None, height=dp(36), multiline=False,
                                             background_color=C.BG_INPUT, foreground_color=C.TEXT)
        self._name_input.bind(on_text_validate=lambda _w: apply())
        section.add_widget(self._name_input)
        # The hint fits one line on a 360 dp phone at the largest text size.
        self._formula_input = CenteredTextInput(text="", hint_text="e.g. alpha1 / (beta1 + 1)", font_size=F.BODY,
                                                size_hint_y=None, height=dp(40), multiline=False,
                                                background_color=C.BG_INPUT, foreground_color=C.TEXT)
        self._formula_input.bind(on_text_validate=lambda _w: apply())
        section.add_widget(self._formula_input)
        buttons = BoxLayout(size_hint_y=None, height=dp(34), spacing=S.GAP_SM)
        for text, colour, action in (("Apply", C.PRIMARY, apply), ("Save", C.ACCENT, save)):
            button = StyledButton(text=text, font_size=F.BODY, bg_color=colour, size_hint_y=None, height=dp(34))
            button.bind(on_release=lambda _w, act=action: act())
            buttons.add_widget(button)
        section.add_widget(buttons)
        self._status = ThemedLabel(text="", font_size=F.SMALL, size_hint_y=None, height=dp(20), color=C.ACCENT,
                                   halign="left")
        text_fills_box(self._status)
        section.add_widget(self._status)

    @property
    def name(self) -> str:
        return self._name_input.text.strip()

    @property
    def formula(self) -> str:
        return self._formula_input.text.strip()

    def show(self, name: str, formula: str) -> None:
        """A slot changed by a load, a restore or a refusal, in its inputs."""
        self._name_input.text = name
        self._formula_input.text = formula

    def show_status(self, text: str, is_error: bool = False) -> None:
        self._status.text = text
        self._status.color = C.DANGER if is_error else C.ACCENT


class FormulaSection:
    """Builds the section's content into `section` and reports the user's actions through its hooks: a slot's by the
    slot's index."""

    on_formula_slot_change = Hook()  # (index, name, formula)
    on_save_formula = Hook()  # (index, name, formula)
    on_load_formula = Hook()  # (the saved formula's index)
    on_delete_formula = Hook()  # (the saved formula's index)
    on_export_formulas = Hook()

    def __init__(self, section) -> None:
        self.saved: list[dict] = []  # the saved formulas, which a program segment can also pick
        section.add_widget(_text("Enter a Python-style formula to track as an extra metric.\nLeave empty to disable.",
                                 F.SMALL, C.TEXT_SECONDARY))
        self.slots = [FormulaSlot(section, i, lambda i=i: self._apply(i), lambda i=i: self._save(i))
                      for i in range(len(FORMULA_KEYS))]
        section.add_widget(self._saved_header())
        self._saved_box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(0), spacing=dp(2))
        section.add_widget(self._saved_box)
        section.add_widget(_text(_EXAMPLES, F.BODY, C.TEXT_MUTED, valign="top"))
        section.add_widget(_text(_REFERENCE, F.SMALL, C.TEXT_MUTED, valign="top"))

    def _saved_header(self) -> BoxLayout:
        header = BoxLayout(size_hint_y=None, height=dp(26), spacing=S.GAP_SM)
        label = ThemedLabel(text="Saved Formulas:", font_size=F.SMALL, size_hint_x=0.6, color=C.TEXT_SECONDARY,
                            halign="left")
        text_fills_box(label)
        header.add_widget(label)
        export = StyledButton(text="Export to .txt", font_size=F.SMALL, bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                              size_hint_x=0.4, size_hint_y=None, height=dp(26))
        export.bind(on_release=lambda *_a: self.on_export_formulas())
        header.add_widget(export)
        return header

    def _apply(self, index: int) -> None:
        slot = self.slots[index]
        self.on_formula_slot_change(index, slot.name, slot.formula)

    def _save(self, index: int) -> None:
        """Save a slot's formula to the library, its entry named by the slot's name."""
        slot = self.slots[index]
        self.on_save_formula(index, slot.name, slot.formula)

    def show_saved(self, formulas: list[dict]) -> None:
        """The saved formulas: [{name, formula}, ...]."""
        self.saved = list(formulas)
        fill_saved_list(self._saved_box, formulas, saved_formula_label, lambda i: self.on_load_formula(i),
                        lambda i: self.on_delete_formula(i))


def _text(text: str, font_size, color, **kwargs) -> ThemedLabel:
    """A multi-line label as tall as its text."""
    label = ThemedLabel(text=text, font_size=font_size, size_hint_y=None, color=color, halign="left", **kwargs)
    fit_height_to_text(label)
    return label
