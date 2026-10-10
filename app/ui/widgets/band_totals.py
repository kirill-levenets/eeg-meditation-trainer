"""Per-band total power breakdown for a whole session (issue #8).

A sortable table with a Detailed (8 sub-bands) / Grouped (5 bands) toggle.
Grouping and sorting are pure view transforms over the DB band totals.
"""
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from app.eeg import band_spec
from app.eeg.band_spec import range_text
from app.ui.theme import ICONS_AVAILABLE, C, F, Icons, S, StyledButton, ThemedLabel

BANDS = list(band_spec.BAND_KEYS)
GROUPS = list(band_spec.GROUP_KEYS)
_GROUP_COLORS = {
    "alpha": (0.1, 0.8, 0.4, 1.0),
    "beta": (0.9, 0.7, 0.1, 1.0),
    "gamma": (1.0, 0.3, 0.3, 1.0),
    "theta": (0.2, 0.5, 0.9, 1.0),
    "delta": (0.4, 0.2, 0.8, 1.0),
}
# Sizes that hold text, in dp at the normal text size; the view takes them through F.box as it renders.
_ROW_H = 22
_BAND_ROW_H = 32  # the name, and its range in a smaller line under it
_W_NAME = 58
_W_POWER = 60
_W_PCT = 44


def band_shares(totals: dict[str, float]) -> dict[str, float]:
    """Each sub-band's share (0..1) of the summed power; zero total -> all zero."""
    vals = {b: float(totals.get(b, 0.0)) for b in BANDS}
    grand = sum(vals.values())
    if grand <= 0:
        return dict.fromkeys(BANDS, 0.0)
    return {b: v / grand for b, v in vals.items()}


def grouped_totals(totals: dict[str, float]) -> dict[str, float]:
    """Collapse the 8 sub-bands into 5 groups (alpha1+alpha2 -> alpha, etc.)."""
    return band_spec.group_powers(lambda k: float(totals.get(k, 0.0)))


def band_rows(
    totals: dict[str, float], *, mode: str = "detailed",
    sort_by: str = "band", descending: bool = False,
) -> list[dict]:
    """Ordered rows (key, name, range, group, total, share) for the table view.

    `mode`: detailed|grouped. `sort_by`: band (frequency order) | power | percent
    (power and percent order identically, by magnitude).
    """
    if mode == "grouped":
        spec, vals, order = band_spec.GROUPS, grouped_totals(totals), GROUPS
    else:
        spec = band_spec.BANDS
        vals = {b: float(totals.get(b, 0.0)) for b in BANDS}
        order = BANDS
    grand = sum(vals.values())
    rows = [
        {"key": b.key, "name": b.name, "range": range_text(b), "group": b.group, "total": vals[b.key],
         "share": (vals[b.key] / grand) if grand > 0 else 0.0}
        for b in spec
    ]
    if sort_by in ("power", "percent"):
        rows.sort(key=lambda r: r["total"], reverse=descending)
    else:
        idx = {k: i for i, k in enumerate(order)}
        rows.sort(key=lambda r: idx[r["key"]], reverse=descending)
    return rows


def format_power(v: float) -> str:
    """Compact power magnitude: 4.21M / 12.3K / 830 / 0."""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:.0f}"


class Bar(Widget):
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


class _HeaderCell(ButtonBehavior, ThemedLabel):
    """A tap-to-sort column header."""

    def __init__(self, on_sort, **kwargs):
        super().__init__(**kwargs)
        self._on_sort = on_sort

    def on_release(self):
        if self._on_sort:
            self._on_sort()


class BandTotalsView(BoxLayout):
    """Sortable per-band session power table with a Detailed/Grouped toggle."""

    def __init__(self, on_change=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(4))
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self.on_change = on_change  # callable(mode, sort_by, descending)
        self._totals: dict[str, float] = dict.fromkeys(BANDS, 0.0)
        self._mode = "detailed"
        self._sort_by = "band"
        self._descending = False
        self._rows: list[dict] = []
        self._value_labels: dict[str, ThemedLabel] = {}
        self._range_labels: dict[str, ThemedLabel] = {}
        self._bars: dict[str, Bar] = {}
        C.add_listener(self._render)
        F.add_listener(self._render)
        self._render()

    # ── public API ──
    def set_totals(self, totals: dict[str, float]) -> None:
        self._totals = {b: float(totals.get(b, 0.0)) for b in BANDS}
        self._render()

    def set_view_state(self, mode: str, sort_by: str, descending: bool) -> None:
        """Restore a persisted view without firing on_change."""
        self._mode = mode if mode in ("detailed", "grouped") else "detailed"
        self._sort_by = sort_by if sort_by in ("band", "power", "percent") else "band"
        self._descending = bool(descending)
        self._render()

    def current_keys(self) -> list[str]:
        return [r["key"] for r in self._rows]

    # ── user actions ──
    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._emit_change()
        self._render()

    def _toggle_sort(self, col: str) -> None:
        if col == self._sort_by:
            self._descending = not self._descending
        else:
            self._sort_by = col
            self._descending = col != "band"  # value columns default to largest-first
        self._emit_change()
        self._render()

    def _emit_change(self) -> None:
        if self.on_change:
            self.on_change(self._mode, self._sort_by, self._descending)

    # ── rendering ──
    def _render(self, *_a) -> None:
        self.clear_widgets()
        self._value_labels.clear()
        self._range_labels.clear()
        self._bars.clear()
        self._rows = band_rows(
            self._totals, mode=self._mode, sort_by=self._sort_by,
            descending=self._descending,
        )
        self.add_widget(self._build_toggle())
        self.add_widget(self._build_header())
        for r in self._rows:
            self.add_widget(self._build_row(r))
        self.height = (sum(child.height for child in self.children) + self.spacing * (len(self.children) - 1)
                       + self.padding[1] + self.padding[3])

    def _build_toggle(self) -> BoxLayout:
        box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24),
                        spacing=dp(1))
        for mode, label in (("detailed", "Detailed"), ("grouped", "Grouped")):
            active = mode == self._mode
            kw = {"text": label, "font_size": F.SMALL, "height": dp(24),
                  "bg_color": C.PRIMARY if active else C.BG_CARD}
            if not active:
                kw["text_color"] = C.TEXT_SECONDARY  # active omits -> AUTO contrast
            btn = StyledButton(**kw)
            btn.bind(on_release=lambda _b, m=mode: self._set_mode(m))
            box.add_widget(btn)
        box.add_widget(Widget())  # trailing spacer so the toggle hugs the left
        return box

    def _header_cell(self, text: str, col: str, width, halign: str) -> _HeaderCell:
        active = self._sort_by == col
        label = text
        if active and ICONS_AVAILABLE:
            # Geometric arrows render as tofu in this Roboto build; use the MDI font.
            glyph = Icons.MENU_DOWN if self._descending else Icons.MENU_UP
            label = f"{text} [font=Icons]{glyph}[/font]"
        cell = _HeaderCell(
            on_sort=lambda: self._toggle_sort(col),
            text=label, markup=True, font_size=F.SMALL, bold=active,
            color=C.PRIMARY if active else C.TEXT_SECONDARY,
            halign=halign, valign="middle", size_hint_x=None, width=width,
        )
        cell.bind(size=cell.setter("text_size"))
        return cell

    def _build_header(self) -> BoxLayout:
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=F.box(_ROW_H),
                        spacing=S.GAP_SM)
        row.add_widget(self._header_cell("Band", "band", F.box(_W_NAME), "left"))
        row.add_widget(Widget())  # share-bar column header (blank)
        row.add_widget(self._header_cell("Power", "power", F.box(_W_POWER), "right"))
        row.add_widget(self._header_cell("%", "percent", F.box(_W_PCT), "right"))
        return row

    def _build_row(self, r: dict) -> BoxLayout:
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=F.box(_BAND_ROW_H),
                        spacing=S.GAP_SM)
        name_lbl = BoxLayout(orientation="vertical", size_hint_x=None, width=F.box(_W_NAME))
        for text, size, color, key in ((r["name"], F.SMALL, C.TEXT_SECONDARY, None),
                                       (r["range"], F.TINY, C.TEXT_MUTED, r["key"])):
            line = ThemedLabel(text=text, font_size=size, color=color, halign="left", valign="middle")
            line.bind(size=line.setter("text_size"))
            name_lbl.add_widget(line)
            if key:
                self._range_labels[key] = line

        track = BoxLayout(orientation="horizontal")
        bar = Bar(_GROUP_COLORS[r["group"]], size_hint_x=r["share"])
        track.add_widget(bar)
        track.add_widget(Widget(size_hint_x=max(0.0, 1.0 - r["share"])))

        power_lbl = ThemedLabel(text=format_power(r["total"]), font_size=F.SMALL, color=C.TEXT,
                          halign="right", valign="middle", size_hint_x=None, width=F.box(_W_POWER))
        power_lbl.bind(size=power_lbl.setter("text_size"))
        pct_lbl = ThemedLabel(text=f"{round(r['share'] * 100)}%", font_size=F.SMALL, color=C.TEXT,
                        halign="right", valign="middle", size_hint_x=None, width=F.box(_W_PCT))
        pct_lbl.bind(size=pct_lbl.setter("text_size"))

        row.add_widget(name_lbl)
        row.add_widget(track)
        row.add_widget(power_lbl)
        row.add_widget(pct_lbl)
        self._value_labels[r["key"]] = pct_lbl
        self._bars[r["key"]] = bar
        return row
