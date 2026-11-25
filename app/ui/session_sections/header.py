"""The Session screen's header: the headset's state, the session's start time and clock, and its state or the
SHAMATHA pill."""
import time

from kivy.graphics import Color, Ellipse, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.ui.device_labels import MOCK_LABEL
from app.ui.theme import C, F, S, ThemedLabel, readable_fg, with_contrast


class HeadsetLabel(ThemedLabel):
    """The headset's name after its marker: a grey ring not connected, an amber ring connecting, a green dot connected,
    a red dot recording (a session running on it; a paused one is connected). The ring or dot tells the link without
    its colour; recording beside connected is told by the running clock too."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._link = "off"  # "off" | "connecting" | "connected"
        self._recording = False
        with self.canvas.after:  # a ring is its disc with a hole in the screen's colour, a dot one in its own colour
            self._paint = Color(1, 1, 1, 1)
            self._disc = Ellipse(size=(0, 0))
            self._hole_paint = Color(1, 1, 1, 1)
            self._hole = Ellipse(size=(0, 0))  # never resized to 0: Kivy keeps drawing a zero-size Ellipse's last shape
        self.bind(pos=self._draw, size=self._draw, texture_size=self._draw, font_size=self._fit_padding)
        C.add_listener(self._draw)
        self._fit_padding()

    @property
    def marker(self) -> tuple[str, str]:
        """The marker drawn now: ("ring" or "dot", its colour role)."""
        if self._link == "connecting":
            return "ring", "CONNECTING"
        if self._link == "connected":
            return "dot", "RECORDING" if self._recording else "CONNECTED"
        return "ring", "TEXT_SECONDARY"

    def show(self, name: str, link: str) -> None:
        self.text = f"[{name}]"
        self._link = link
        self._draw()

    def set_recording(self, recording: bool) -> None:
        self._recording = recording
        self._draw()

    def _marker_size(self) -> tuple[float, float]:
        """(its diameter, its gap to the name): it follows the text size."""
        return self.font_size * 0.75, self.font_size * 0.4

    def _fit_padding(self, *_args) -> None:
        diameter, gap = self._marker_size()
        self.padding = [diameter + gap, 0, 0, 0]  # the marker sits in it: centred with the name as one

    def _draw(self, *_args) -> None:
        shape, role = self.marker
        bg = C.resolve(C.BG)  # the screen's, which the label sits on
        self._paint.rgba = (*with_contrast(C.resolve(getattr(C, role)), bg), 1)
        self._hole_paint.rgba = self._paint.rgba if shape == "dot" else bg
        diameter, _gap = self._marker_size()
        cx, cy = self.center_x - self.texture_size[0] / 2 + diameter / 2, self.center_y
        self._disc.pos, self._disc.size = (cx - diameter / 2, cy - diameter / 2), (diameter, diameter)
        hole = diameter - 2 * max(1.0, diameter * 0.16)
        self._hole.pos, self._hole.size = (cx - hole / 2, cy - hole / 2), (hole, hole)


class SessionHeader(BoxLayout):
    """Three status lines in a row: the headset, the clock, the state."""

    def __init__(self) -> None:
        super().__init__(size_hint_y=None, height=self._box_height(), spacing=S.GAP_SM)
        F.add_listener(self._fit_height)
        self._device_label = HeadsetLabel(
            text=f"[{MOCK_LABEL}]",
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

    def update_device_status(self, connected: bool, device_name: str, connecting: bool = False) -> None:
        """The headset's name and its link: connecting, connected or neither."""
        self._device_label.show(device_name, "connecting" if connecting else "connected" if connected else "off")

    def set_recording(self, recording: bool) -> None:
        """A session running (recording) or not: paused, ended, not started."""
        self._device_label.set_recording(recording)
