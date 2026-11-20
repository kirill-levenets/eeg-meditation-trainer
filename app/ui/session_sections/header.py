"""The Session screen's header: the headset's state, the session's start time and clock, and its state or the
SHAMATHA pill."""
import time

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.ui.theme import C, F, S, ThemedLabel, readable_fg


class SessionHeader(BoxLayout):
    """Three status lines in a row: the headset, the clock, the state."""

    def __init__(self) -> None:
        super().__init__(size_hint_y=None, height=self._box_height(), spacing=S.GAP_SM)
        F.add_listener(self._fit_height)
        self._device_label = ThemedLabel(
            text="[Mock EEG]",
            size_hint_x=1 / 3,
            color=C.DEVICE_IDLE,
            font_size=F.capped(F.SMALL),  # a 10 dp status line
        )
        self._timer_label = ThemedLabel(
            text="00:00",
            size_hint_x=1 / 3,
            font_size=F.capped(F.BODY),
            bold=True,
            color=C.TEXT,
        )
        self._start_time: str = ""  # the session's start "HH:MM", shown before its elapsed time
        self._state_label = ThemedLabel(
            size_hint_x=1 / 3,
            font_size=F.capped(F.BODY),
        )
        # "In shamatha" chip — a rounded pill drawn behind the status text, sized to
        # the text and toggled via set_shamatha(). Alpha 0 = hidden.
        with self._state_label.canvas.before:
            self._shamatha_bg = Color(*C.SHAMATHA[:3], 0)
            self._shamatha_rect = RoundedRectangle(radius=[dp(9)])
        self._show_idle_state()
        self._state_label.bind(
            pos=self._position_shamatha_chip,
            size=self._position_shamatha_chip,
            texture_size=self._position_shamatha_chip,
        )
        self.add_widget(self._device_label)
        self.add_widget(self._timer_label)
        self.add_widget(self._state_label)

    @staticmethod
    def _box_height() -> float:
        return F.box(10, F.CAPPED_MAX)  # its text is capped (a status line), and spills a little past it at normal

    def _fit_height(self) -> None:
        self.height = self._box_height()

    def update_timer(self, text: str) -> None:
        if self._start_time:
            self._timer_label.text = f"{self._start_time} · {text}"
        else:
            self._timer_label.text = text

    def set_start_time(self, epoch: float) -> None:
        lt = time.localtime(epoch)
        self._start_time = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"

    def clear(self) -> None:
        """What a fresh screen shows: no start time, a zero clock, IDLE."""
        self._start_time = ""
        self._timer_label.text = "00:00"
        self._show_idle_state()

    def _show_idle_state(self) -> None:
        """The state a fresh screen shows: IDLE, no shamatha chip."""
        self._last_state = "IDLE"
        self.set_shamatha(False)

    def _apply_state_style(self, state: str) -> None:
        self._state_label.text = state
        self._state_label.bold = False
        color_map = {
            "Stable Focus": C.STATE_FOCUS,
            "Subtle Distraction": C.STATE_SUBTLE,
            "Gross Distraction": C.STATE_DISTRACTED,
            "Sinking": C.STATE_SINKING,
            "Neutral": C.STATE_NEUTRAL,
            "IDLE": C.TEXT_SECONDARY,
        }
        self._state_label.color = color_map.get(state, C.STATE_NEUTRAL)

    def update_state(self, state: str) -> None:
        self._last_state = state
        # While in the shamatha zone the chip owns the label; classified-state
        # ticks are remembered but must not overwrite it.
        if not self._shamatha_active:
            self._apply_state_style(state)

    def set_shamatha(self, active: bool) -> None:
        """Toggle the 'in shamatha' emphasis on the status label (main thread)."""
        self._shamatha_active = active
        if active:
            self._state_label.text = "SHAMATHA"
            self._state_label.bold = True
            self._state_label.color = readable_fg(C.SHAMATHA)
            self._shamatha_bg.rgb = C.SHAMATHA[:3]
            self._shamatha_bg.a = 1
        else:
            self._shamatha_bg.a = 0
            self._apply_state_style(self._last_state)

    def _position_shamatha_chip(self, *_args) -> None:
        lbl = self._state_label
        tw, th = lbl.texture_size
        w = tw + dp(16)
        h = th + dp(6)
        cx = lbl.x + lbl.width / 2
        cy = lbl.y + lbl.height / 2
        self._shamatha_rect.pos = (cx - w / 2, cy - h / 2)
        self._shamatha_rect.size = (w, h)

    def update_device_status(
        self, connected: bool, device_name: str = "", connecting: bool = False
    ) -> None:
        if connecting:
            name = device_name or "Device"
            self._device_label.text = f"[{name}] ..."
            self._device_label.color = C.CONNECTING
        elif connected:
            label = f"[{device_name}] *" if device_name else "[Mock EEG] *"
            self._device_label.text = label
            self._device_label.color = C.CONNECTED
        elif device_name:
            self._device_label.text = f"[{device_name}]"
            self._device_label.color = C.DEVICE_IDLE
        else:
            self._device_label.text = "[Disconnected]"
            self._device_label.color = C.DISCONNECTED
