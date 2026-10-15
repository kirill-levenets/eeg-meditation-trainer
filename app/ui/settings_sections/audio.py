"""Settings → Audio: the feedback sound below the threshold and the reward above it, the alert bells and the sound
test."""
from collections.abc import Callable
from typing import Optional

from kivy.metrics import dp

from app.config import APP
from app.ui.settings_sections.common import (
    checkbox_row,
    open_audio_file_chooser,
    open_source_picker,
    source_label,
)
from app.ui.theme import C, F, StyledButton, ThemedLabel, fit_height_to_text

_FEEDBACK_SOURCE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Off", "none"), ("Rain", "noise"), ("Tone", "tone"), ("Custom file...", "custom"),
)
# Reward adds the periodic Crickets cue (issue #11); below-threshold feedback does not.
# ("heartbeat" is the stable internal source id — the timbre is a cricket chirp.)
_REWARD_SOURCE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Off", "none"), ("Rain", "noise"), ("Tone", "tone"),
    ("Crickets", "heartbeat"), ("Custom file...", "custom"),
)


class AudioSection:
    """Builds the section's content into `section` and reports the user's actions through its callbacks."""

    def __init__(self, section) -> None:
        self._on_test_audio: Optional[Callable] = None
        self._on_sinking_alert_toggle: Optional[Callable] = None
        self._on_subtle_alert_toggle: Optional[Callable] = None
        self._on_disconnect_alert_toggle: Optional[Callable] = None
        self._on_feedback_source_change: Optional[Callable] = None
        self._feedback_source: str = "noise"
        self._feedback_sound_path: str = ""
        self._feedback_source_btn: Optional[StyledButton] = None
        self._on_reward_source_change: Optional[Callable] = None
        self._reward_source: str = "none"   # above-threshold reward (off by default)
        self._reward_sound_path: str = ""
        self._reward_source_btn: Optional[StyledButton] = None
        self._build(section)

    def _build(self, section) -> None:

        audio_desc = ThemedLabel(
            text=(
                "Rain noise — volume decreases as meditation deepens\n"
                "Test: reward sample, feedback sweep (0-max-0), sinking bell (every 15s),\n"
                "distraction chime (subtle > 30, every 20s), disconnect warble (device lost)"
            ),
            font_size=F.SMALL,
            size_hint_y=None,
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        fit_height_to_text(audio_desc)
        section.add_widget(audio_desc)

        # Test Audio button
        self._test_audio_btn = StyledButton(
            text="Test Audio",
            font_size=F.H3,
            bold=True,
            bg_color=C.PRIMARY,
            size_hint_y=None,
            height=dp(40),
        )
        self._test_audio_btn.bind(on_release=self._on_test_audio_pressed)
        section.add_widget(self._test_audio_btn)

        fb_label = ThemedLabel(
            text="Feedback sound:", font_size=F.SMALL, color=C.TEXT_SECONDARY,
            size_hint_y=None, height=dp(24), halign="left", valign="middle",
        )
        fb_label.bind(size=fb_label.setter("text_size"))
        section.add_widget(fb_label)

        self._feedback_source_btn = StyledButton(
            text=source_label(self._feedback_source, self._feedback_sound_path),
            font_size=F.SMALL, bg_color=C.BG_CARD, text_color=C.TEXT,
            size_hint_y=None, height=dp(36),
        )
        self._feedback_source_btn.bind(on_release=lambda *_a: self._open_feedback_source_picker())
        section.add_widget(self._feedback_source_btn)

        # Above-threshold reward channel (issue #12): a second sound that rises as the
        # score climbs above the threshold. Off by default.
        rw_label = ThemedLabel(
            text="Reward sound (above threshold):", font_size=F.SMALL, color=C.TEXT_SECONDARY,
            size_hint_y=None, height=dp(24), halign="left", valign="middle",
        )
        rw_label.bind(size=rw_label.setter("text_size"))
        section.add_widget(rw_label)

        self._reward_source_btn = StyledButton(
            text=source_label(self._reward_source, self._reward_sound_path),
            font_size=F.SMALL, bg_color=C.BG_CARD, text_color=C.TEXT,
            size_hint_y=None, height=dp(36),
        )
        self._reward_source_btn.bind(on_release=lambda *_a: self._open_reward_source_picker())
        section.add_widget(self._reward_source_btn)

        # Sinking alert toggle
        sinking_row, self._sinking_alert_cb = checkbox_row("Enable Sinking Alert Bell", dp(36), active=False)
        self._sinking_alert_cb.bind(active=self._on_sinking_alert_change)
        section.add_widget(sinking_row)

        # Subtle distraction alert toggle
        subtle_row, self._subtle_alert_cb = checkbox_row("Enable Distraction Chime", dp(36), active=False)
        self._subtle_alert_cb.bind(active=self._on_subtle_alert_change)
        section.add_widget(subtle_row)

        # Disconnect alert toggle
        disconnect_row, self._disconnect_alert_cb = checkbox_row(
            "Audio alert on disconnect / signal loss", dp(36), active=APP.DISCONNECT_ALERT_ENABLED)
        self._disconnect_alert_cb.bind(active=self._on_disconnect_alert_change)
        section.add_widget(disconnect_row)

    def _on_test_audio_pressed(self, *args) -> None:
        if self._on_test_audio:
            self._on_test_audio()

    def _on_sinking_alert_change(self, checkbox, active) -> None:
        if self._on_sinking_alert_toggle:
            self._on_sinking_alert_toggle(active)

    def _on_subtle_alert_change(self, checkbox, active) -> None:
        if self._on_subtle_alert_toggle:
            self._on_subtle_alert_toggle(active)

    def _on_disconnect_alert_change(self, checkbox, active) -> None:
        if self._on_disconnect_alert_toggle:
            self._on_disconnect_alert_toggle(active)

    def set_test_audio_callback(self, callback: Callable) -> None:
        self._on_test_audio = callback

    def set_feedback_source_callback(self, callback: Callable) -> None:
        self._on_feedback_source_change = callback

    @property
    def feedback_source(self) -> str:
        return self._feedback_source

    def set_feedback_source(self, source: str, path: str = "") -> None:
        """Reflect a restored/loaded feedback selection on the picker button (no callback)."""
        self._feedback_source = source or "noise"
        self._feedback_sound_path = path or ""
        if self._feedback_source_btn is not None:
            self._feedback_source_btn.text = source_label(self._feedback_source, self._feedback_sound_path)

    def _open_feedback_source_picker(self) -> None:
        open_source_picker("Feedback sound", _FEEDBACK_SOURCE_OPTIONS, self._choose_feedback_source)

    def _choose_feedback_source(self, value: str) -> None:
        if value == "custom":
            open_audio_file_chooser(
                lambda p: self._apply_feedback_source("custom", p), title="Feedback sound file")
            return
        self._apply_feedback_source(value, "")

    def _apply_feedback_source(self, source: str, path: str) -> None:
        self.set_feedback_source(source, path)
        if self._on_feedback_source_change:
            self._on_feedback_source_change(self._feedback_source, self._feedback_sound_path)

    def set_reward_source_callback(self, callback: Callable) -> None:
        self._on_reward_source_change = callback

    def set_reward_source(self, source: str, path: str = "") -> None:
        """Reflect a restored/loaded reward selection on the picker button (no callback)."""
        self._reward_source = source or "none"
        self._reward_sound_path = path or ""
        if self._reward_source_btn is not None:
            self._reward_source_btn.text = source_label(self._reward_source, self._reward_sound_path)

    def _open_reward_source_picker(self) -> None:
        open_source_picker("Reward sound", _REWARD_SOURCE_OPTIONS, self._choose_reward_source)

    def _choose_reward_source(self, value: str) -> None:
        if value == "custom":
            open_audio_file_chooser(
                lambda p: self._apply_reward_source("custom", p), title="Reward sound file")
            return
        self._apply_reward_source(value, "")

    def _apply_reward_source(self, source: str, path: str) -> None:
        self.set_reward_source(source, path)
        if self._on_reward_source_change:
            self._on_reward_source_change(self._reward_source, self._reward_sound_path)

    def set_sinking_alert_callback(self, callback: Callable) -> None:
        self._on_sinking_alert_toggle = callback

    def set_subtle_alert_callback(self, callback: Callable) -> None:
        self._on_subtle_alert_toggle = callback

    def set_disconnect_alert_callback(self, callback: Callable) -> None:
        self._on_disconnect_alert_toggle = callback
