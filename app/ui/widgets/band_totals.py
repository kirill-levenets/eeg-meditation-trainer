"""Per-band total power breakdown for a whole session (issue #8)."""
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from app.ui.theme import C, F, S

BANDS = ["delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2"]

# (key, display name, color group) — sub-bands share their group's colour,
# mirroring the frequency-band chart palette.
_BAND_META = [
    ("delta", "Delta", "delta"),
    ("theta", "Theta", "theta"),
    ("alpha1", "Alpha 1", "alpha"),
    ("alpha2", "Alpha 2", "alpha"),
    ("beta1", "Beta 1", "beta"),
    ("beta2", "Beta 2", "beta"),
    ("gamma1", "Gamma 1", "gamma"),
    ("gamma2", "Gamma 2", "gamma"),
]
_GROUP_COLORS = {
    "alpha": (0.1, 0.8, 0.4, 1.0),
    "beta": (0.9, 0.7, 0.1, 1.0),
    "gamma": (1.0, 0.3, 0.3, 1.0),
    "theta": (0.2, 0.5, 0.9, 1.0),
    "delta": (0.4, 0.2, 0.8, 1.0),
}
_ROW_H = dp(20)


def band_shares(totals: dict[str, float]) -> dict[str, float]:
    """Each band's share (0..1) of the summed power; zero total -> all zero."""
    vals = {b: float(totals.get(b, 0.0)) for b in BANDS}
    grand = sum(vals.values())
    if grand <= 0:
        return dict.fromkeys(BANDS, 0.0)
    return {b: v / grand for b, v in vals.items()}


def format_power(v: float) -> str:
    """Compact power magnitude: 4.21M / 12.3K / 830 / 0."""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:.0f}"


class _Bar(Widget):
    """A solid rounded bar filling its own box in `color`."""

    def __init__(self, color, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._col = Color(*color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(3)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_a):
        self._rect.pos = self.pos
        self._rect.size = self.size


class BandTotalsView(BoxLayout):
    """Eight-band session power breakdown: label · share bar · total + percent."""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(4))
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._totals: dict[str, float] = dict.fromkeys(BANDS, 0.0)
        self._value_labels: dict[str, Label] = {}
        self._bars: dict[str, _Bar] = {}
        self.height = len(BANDS) * (_ROW_H + dp(4))
        C.add_listener(self._render)
        self._render()

    def set_totals(self, totals: dict[str, float]) -> None:
        self._totals = {b: float(totals.get(b, 0.0)) for b in BANDS}
        self._render()

    def _render(self, *_a) -> None:
        self.clear_widgets()
        self._value_labels.clear()
        self._bars.clear()
        shares = band_shares(self._totals)
        for key, name, group in _BAND_META:
            share = shares[key]
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=_ROW_H,
                            spacing=S.GAP_SM)
            name_lbl = Label(text=name, font_size=F.SMALL, color=C.TEXT_SECONDARY,
                             halign="left", size_hint_x=None, width=dp(58))
            name_lbl.bind(size=name_lbl.setter("text_size"))

            track = BoxLayout(orientation="horizontal")
            bar = _Bar(_GROUP_COLORS[group], size_hint_x=share)
            spacer = Widget(size_hint_x=max(0.0, 1.0 - share))
            track.add_widget(bar)
            track.add_widget(spacer)

            val_lbl = Label(
                text=f"{format_power(self._totals[key])}  {round(share * 100)}%",
                font_size=F.SMALL, color=C.TEXT, halign="right",
                size_hint_x=None, width=dp(100),
            )
            val_lbl.bind(size=val_lbl.setter("text_size"))

            row.add_widget(name_lbl)
            row.add_widget(track)
            row.add_widget(val_lbl)
            self.add_widget(row)
            self._value_labels[key] = val_lbl
            self._bars[key] = bar
