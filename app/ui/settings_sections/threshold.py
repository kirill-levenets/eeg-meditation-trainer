"""Settings → Threshold: the threshold slider with its steps and presets, and the metric that drives the sound (a
custom formula's slot included). Two owners, so two classes in the one fold."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.slider import Slider

from app.config import METRICS
from app.ui.hooks import Hook
from app.ui.settings_sections.common import checkbox_row
from app.ui.theme import C, F, S, ThemedLabel, text_fills_box
from app.ui.widgets.choice_toggle import ChoiceToggle
from app.ui.widgets.rows import PresetRow
from app.ui.widgets.styled_button import StyledButton

METRIC_OPTIONS = {
    "shamatha_score": "Shamatha Score",
    "native_meditation": "NS Meditation",
    "native_attention": "NS Attention",
    "custom_formula": "Custom Formula",
}


class ThresholdSlider:
    """The threshold: a slider with -/+ steps of 5 and presets; while a program runs a touch on them goes to the lock."""

    on_change = Hook()

    def __init__(self, section) -> None:
        self._lock: Callable[[], bool] | None = None
        slider_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=S.GAP_SM)
        minus_btn = StyledButton(text="−", font_size=F.H2, bg_color=C.BG_CARD, size_hint_x=None, width=dp(48))
        plus_btn = StyledButton(text="+", font_size=F.H2, bg_color=C.BG_CARD, size_hint_x=None, width=dp(48))
        self._slider = Slider(min=20, max=180, value=METRICS.MEDITATION_THRESHOLD_DEFAULT, step=1, size_hint_x=1)
        self._value_label = ThemedLabel(text=str(METRICS.MEDITATION_THRESHOLD_DEFAULT), font_size=F.H2, bold=True,
                                        color=C.TEXT, size_hint_x=None, width=dp(48))
        self._slider.bind(value=self._on_slider_value)
        minus_btn.bind(on_release=lambda *_a: self._step(-5))
        plus_btn.bind(on_release=lambda *_a: self._step(5))
        for widget in (minus_btn, self._slider, self._value_label, plus_btn):
            slider_row.add_widget(widget)
        section.add_widget(slider_row)
        presets = PresetRow(values=[50, 80, 100, 130, 160], callback=lambda v: setattr(self._slider, "value", v))
        section.add_widget(presets)
        self._controls = (slider_row, presets)
        for controls in self._controls:
            controls.fbind("on_touch_down", self._on_controls_touch)

    @property
    def value(self) -> int:
        return int(self._slider.value)

    @value.setter
    def value(self, value: int) -> None:
        self._slider.value = value

    def lock(self, on_touch: Callable[[], bool] | None) -> None:
        """Dim the controls; a touch on them goes to `on_touch` instead, whenever that refuses it."""
        self._lock = on_touch
        for controls in self._controls:
            controls.opacity = 0.5 if on_touch else 1.0

    def _on_slider_value(self, _slider, value) -> None:
        self._value_label.text = str(int(value))
        self.on_change(int(value))

    def _step(self, delta: int) -> None:
        """Nudge the threshold by `delta`, clamped to the slider's range (the slider's value change does the rest)."""
        s = self._slider
        s.value = max(s.min, min(s.max, int(s.value) + delta))

    def _on_controls_touch(self, controls, touch) -> bool:
        if self._lock is None or not controls.collide_point(*touch.pos):
            return False
        # True: the slider, the -/+ buttons and the presets never see it, a mouse wheel included (it steps the slider)
        return bool(self._lock())


class MetricPicker:
    """The metric that drives the sound, as its radios show it, and a custom formula's slot; the choice itself is the
    profile's setting (AudioMetric), which these controls show and report changes to."""

    on_metric_change = Hook()
    on_formula_index = Hook()

    def __init__(self, section) -> None:
        heading = ThemedLabel(text="Audio control metric:", font_size=F.BODY, size_hint_y=None, height=dp(24),
                              color=C.TEXT_SECONDARY, halign="left")
        text_fills_box(heading)
        section.add_widget(heading)
        self._radios = {}
        for key, display_name in METRIC_OPTIONS.items():
            row, radio = checkbox_row(display_name, dp(32), group="audio_metric", active=(key == "shamatha_score"))
            radio.bind(active=lambda _radio, active, k=key: active and self.on_metric_change(k))
            section.add_widget(row)
            self._radios[key] = radio
        index_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP)
        index_row.add_widget(ThemedLabel(text="    Slot:", font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint_x=0.25,
                                         halign="left", valign="middle"))
        self._slot_toggle = ChoiceToggle([(0, "1"), (1, "2"), (2, "3")], 0, self._on_slot_chosen,
                                         button={"font_size": F.SMALL, "size_hint_y": None, "height": dp(28)},
                                         size_hint_x=0.75, spacing=S.GAP)
        index_row.add_widget(self._slot_toggle)
        section.add_widget(index_row)

    @property
    def metric(self) -> str:
        """The metric its radios show."""
        return next((key for key, radio in self._radios.items() if radio.active), "shamatha_score")

    @metric.setter
    def metric(self, key: str) -> None:
        for k, radio in self._radios.items():
            radio.active = (k == key)

    @property
    def formula_index(self) -> int:
        """The formula slot its buttons show."""
        return self._slot_toggle.chosen

    @formula_index.setter
    def formula_index(self, idx: int) -> None:
        self._slot_toggle.show(idx)

    def _on_slot_chosen(self, idx: int) -> None:
        self.on_formula_index(idx)
