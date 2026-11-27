"""Settings → Audio: the feedback sound below the threshold and the reward above it, the alert bells and the sound
test."""

from collections.abc import Callable
from dataclasses import dataclass

from kivy.metrics import dp
from kivy.uix.checkbox import CheckBox

from app.config import APP
from app.ui.hooks import Hook
from app.ui.settings_sections.common import checkbox_row, open_sound_picker, source_label
from app.ui.theme import C, F, ThemedLabel, fit_height_to_text, text_fills_box
from app.ui.widgets.styled_button import StyledButton


@dataclass(frozen=True)
class SourceSpec:
    """A sound channel's picker: its label, the picker's title, its choices and the source shown by default."""

    label: str
    title: str
    options: tuple[tuple[str, str], ...]
    default: str


FEEDBACK = SourceSpec("Feedback sound:", "Feedback sound",
                      (("Off", "none"), ("Rain", "noise"), ("Tone", "tone"), ("Custom file...", "custom")), "noise")
# Reward adds the periodic Crickets cue (issue #11); below-threshold feedback does not.
# ("heartbeat" is the stable internal source id — the timbre is a cricket chirp.)
REWARD = SourceSpec("Reward sound (above threshold):", "Reward sound",
                    (("Off", "none"), ("Rain", "noise"), ("Tone", "tone"), ("Crickets", "heartbeat"),
                     ("Custom file...", "custom")), "none")
# Each alert toggle by the setting it holds.
ALERTS = (("sinking_alert", "Enable Sinking Alert Bell"), ("subtle_alert", "Enable Distraction Chime"),
          ("disconnect_alert", "Audio alert on disconnect / signal loss"))


class SourcePicker:
    """A sound channel's source: its label, a button naming the source, and the picker it opens (a file for Custom)."""

    def __init__(self, section, spec: SourceSpec, on_change: Callable[[str, str], None]) -> None:
        self._spec, self._on_change = spec, on_change
        self.source, self.path = spec.default, ""
        label = ThemedLabel(text=spec.label, font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint_y=None,
                            height=dp(24), halign="left", valign="middle")
        text_fills_box(label)
        section.add_widget(label)
        self.button = StyledButton(text=source_label(self.source, self.path), font_size=F.SMALL, bg_color=C.BG_CARD,
                                   text_color=C.TEXT, size_hint_y=None, height=dp(36))
        self.button.bind(on_release=lambda *_a: open_sound_picker(spec.title, spec.options, self._apply))
        section.add_widget(self.button)

    def show(self, source: str, path: str = "") -> None:
        """A restored or loaded choice, on the button (nothing reported)."""
        self.source = source or self._spec.default
        self.path = path or ""
        self.button.text = source_label(self.source, self.path)

    def _apply(self, source: str, path: str) -> None:
        """The picker's choice, shown and reported."""
        self.show(source, path)
        self._on_change(self.source, self.path)


class AudioSection:
    """Builds the section's content into `section` and reports the user's actions through its hooks."""

    on_test_audio = Hook()
    on_feedback_source_change = Hook()
    on_reward_source_change = Hook()
    on_alert_toggle = Hook()  # (the alert's setting key, on)

    def __init__(self, section) -> None:
        desc = ThemedLabel(
            text=(
                "Rain noise — volume decreases as meditation deepens\n"
                "Test: reward sample, feedback sweep (0-max-0), sinking bell (every 15s),\n"
                "distraction chime (subtle > 30, every 20s), disconnect warble (device lost)"
            ),
            font_size=F.SMALL, size_hint_y=None, color=C.TEXT_SECONDARY, halign="left",
        )
        fit_height_to_text(desc)
        section.add_widget(desc)
        test_btn = StyledButton(text="Test Audio", font_size=F.H3, bold=True, bg_color=C.PRIMARY, size_hint_y=None,
                                height=dp(40))
        test_btn.bind(on_release=lambda *_a: self.on_test_audio())
        section.add_widget(test_btn)
        self.feedback = SourcePicker(section, FEEDBACK, lambda s, p: self.on_feedback_source_change(s, p))
        # Above-threshold reward channel (issue #12): a second sound that rises as the score climbs above the threshold.
        self.reward = SourcePicker(section, REWARD, lambda s, p: self.on_reward_source_change(s, p))
        self.alerts: dict[str, CheckBox] = {}
        for key, text in ALERTS:
            row, box = checkbox_row(text, dp(36), active=key == "disconnect_alert" and APP.DISCONNECT_ALERT_ENABLED)
            box.bind(active=lambda _box, on, k=key: self.on_alert_toggle(k, on))
            section.add_widget(row)
            self.alerts[key] = box
