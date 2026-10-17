"""Which series each graph shows: the on-graph series picker, and each graph's selection as the profile saves it."""
from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.metrics.formula_slots import FORMULA_KEYS, FormulaSlots
from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.ui.theme import (
    C,
    S,
    StyledButton,
    ThemedLabel,
    cancel_button,
    make_scroll_popup,
)


def _show_row_state(btn, visible: bool) -> None:
    """A picker row's look: filled and bold while its series shows."""
    btn.bg_color = C.ACCENT if visible else C.BG_CARD
    btn.text_color = None if visible else C.TEXT_SECONDARY
    btn.bold = visible


class GraphSeries:
    """The live metrics graph lists a formula slot only while it is valid, and a program line only while its program
    runs and computes it; a program's own series set is never saved as the profile's selection."""

    def __init__(self, db, live_graph, formulas: FormulaSlots, program_run, program_settings, formula_settings,
                 fullscreen, *, graphs: Callable[[], tuple], legacy_defaults: dict[str, bool],
                 user_id: Callable[[], int | None], require_user: Callable[[str], int | None]) -> None:
        self._db = db
        self._live_graph = live_graph
        self._formulas = formulas
        self._program_run = program_run
        self._program_settings = program_settings
        self._formula_settings = formula_settings
        self._fullscreen = fullscreen
        self._graphs = graphs
        self._legacy_defaults = legacy_defaults
        self._user_id = user_id
        self._require_user = require_user

    def present_picker(self, graph) -> None:
        """Open the shared multi-select series popup for `graph`.

        Reads the graph's own catalog/labels/colors, so one presenter serves
        every graph. Wired to all multi-series graphs by _wire_graph_affordances.
        For the live metrics graph, custom-formula rows also carry a Choose button
        that assigns a saved formula to that slot without leaving the picker.
        """
        is_live = graph is self._live_graph
        rows = []
        for key in graph.series_keys():
            if key in PROGRAM_FORMULA_KEYS and not (is_live and self._program_run.computes(key)):
                continue  # program-controlled: listed only while its program runs and computes it
            btn = StyledButton(text=graph.series_name(key), height=dp(44))
            _show_row_state(btn, graph.is_visible(key))
            btn.bind(on_release=lambda b, k=key: self._toggle(graph, k, b))
            if is_live and key in FORMULA_KEYS:
                row = BoxLayout(orientation="horizontal", spacing=S.GAP_SM, height=dp(44), size_hint_y=None)
                btn.size_hint_x = 1
                choose_btn = StyledButton(
                    text="Choose…", height=dp(44), size_hint_x=None, width=dp(90),
                    bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                )
                slot_idx = FORMULA_KEYS.index(key)
                choose_btn.bind(on_release=lambda _b, si=slot_idx, tb=btn: self._choose_saved_formula(si, tb))
                row.add_widget(btn)
                row.add_widget(choose_btn)
                rows.append(row)
            else:
                rows.append(btn)
        # Neutral, not a fill: a green Close (PRIMARY) collided with the green "selected" pills on the green palettes.
        close_btn = cancel_button("Close", height=dp(44))
        popup = make_scroll_popup("Graph series", rows, footer=close_btn)
        close_btn.bind(on_release=lambda *_a: popup.dismiss())
        popup.bind(on_dismiss=lambda *_a: self.persist(graph))
        popup.open()

    def _choose_saved_formula(self, slot_idx: int, toggle_btn) -> None:
        """Open a second popup listing saved formulas; selecting one assigns it to
        slot_idx and refreshes the picker's toggle button to its new visible state."""
        uid = self._require_user("choose a saved formula")
        if uid is None:
            return
        formulas = self._db.get_saved_formulas(uid)

        def _choose(entry):
            inner_popup.dismiss()
            self._formula_settings.assign_saved(slot_idx, entry)
            _show_row_state(toggle_btn, self._live_graph.is_visible(FORMULA_KEYS[slot_idx]))

        rows = []
        if not formulas:
            rows.append(ThemedLabel(
                text="No saved formulas", color=C.TEXT_SECONDARY,
                height=dp(44), size_hint_y=None,
            ))
        else:
            for entry in formulas:
                row_btn = StyledButton(
                    text=entry.get("name", entry.get("formula", "")[:30]),
                    height=dp(44),
                    bg_color=C.BG_CARD, text_color=C.TEXT,
                )
                row_btn.bind(on_release=lambda _b, e=entry: _choose(e))
                rows.append(row_btn)
        cancel_btn = cancel_button(height=dp(44))
        inner_popup = make_scroll_popup("Choose saved formula", rows, footer=cancel_btn, width_hint=0.8)
        cancel_btn.bind(on_release=lambda *_a: inner_popup.dismiss())
        inner_popup.open()

    def _toggle(self, graph, key: str, btn) -> None:
        """Flip one series on `graph` (stays in the popup for multi-select)."""
        visible = not graph.is_visible(key)
        # The live formula must be valid to plot live custom_formula values;
        # diary custom_formula is recorded data and toggles freely.
        ev = self._formulas.for_key(key)
        if ev is not None and graph is self._live_graph:
            visible = visible and ev.is_valid
        graph.set_visible(key, visible)  # fires the owning screen's legend refresh
        self._fullscreen.refresh_legend()
        _show_row_state(btn, graph.is_visible(key))

    def _pickable(self) -> list:
        """The graphs with a picker: an id to save under and more than one series to choose from."""
        return [g for g in self._graphs() if g.graph_id and len(g.series_keys()) > 1]

    def persist(self, graph) -> None:
        """Persist `graph`'s visible series under its per-graph key (on picker close).

        Skips the live metrics graph while a program sets its series — a running one, or the idle preview of the one
        Settings has loaded: the program-driven set must not overwrite the user's saved manual selection."""
        uid = self._user_id()
        if not (uid and graph.graph_id):
            return
        if graph is self._live_graph and (self._program_run.active or self._program_settings.governs_live_series()):
            return
        self._db.set_user_json_setting(
            uid, f"graph_series_{graph.graph_id}",
            [k for k in graph.visible_keys() if k not in PROGRAM_FORMULA_KEYS],
        )

    def persist_all(self) -> None:
        for graph in self._pickable():
            self.persist(graph)

    def restore(self, user_id: int) -> None:
        """Apply each graph's persisted series selection (graph_series_<id>).

        set_visible drives each graph's own legend refresh. The live metrics graph
        migrates the pre-F2 toggle_<key> rows when it has no JSON yet; other graphs
        default to all-visible (their pre-picker behavior)."""
        for graph in self._pickable():
            self.apply_saved(graph, user_id)

    def apply_saved(self, graph, user_id: int) -> None:
        """Apply one graph's persisted series selection (graph_series_<id>). The live
        metrics graph migrates the pre-F2 toggle_<key> rows when it has no JSON yet and
        gates custom-formula slots on validity; other graphs default to all-visible."""
        series = self._db.get_user_json_setting(user_id, f"graph_series_{graph.graph_id}")
        if series is not None:
            sel = set(series)
        elif graph is self._live_graph:
            sel = self._legacy_live(user_id)
        else:
            sel = set(graph.series_keys())
        for key in graph.series_keys():
            on = key in sel
            if key in PROGRAM_FORMULA_KEYS:
                on = False  # program-controlled; never restored as a user selection
            ev = self._formulas.for_key(key)
            if ev is not None and graph is self._live_graph:
                on = on and ev.is_valid
            graph.set_visible(key, on)

    def _legacy_live(self, user_id: int) -> set[str]:
        """Pre-F2 fallback for the live metrics graph: per-metric toggle_<key> rows
        + custom_formula_visible, defaulting to the first-run toggle set."""
        sel: set[str] = set()
        for key in self._live_graph.series_keys():
            if key in FORMULA_KEYS:  # custom slots never had pre-F2 toggle_ rows
                continue
            saved = self._db.get_user_setting(user_id, f"toggle_{key}")
            active = (saved == "True") if saved is not None else self._legacy_defaults.get(key, True)
            if active:
                sel.add(key)
        if self._db.get_user_setting(user_id, "custom_formula_visible") == "True":
            sel.add("custom_formula")
        return sel
