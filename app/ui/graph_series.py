"""Which series each graph shows: the on-graph series picker, and each graph's selection as the profile saves it."""
from collections.abc import Callable
from types import MappingProxyType

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.metrics.formula_slots import FORMULA_KEYS, FormulaSlots
from app.session.session_program import (
    PROGRAM_FORMULA_KEYS,
    RunnablePlan,
    program_line_name,
)
from app.ui.app_context import AppContext
from app.ui.theme import (
    C,
    S,
    StyledButton,
    ThemedLabel,
    cancel_button,
    make_scroll_popup,
)

# The live metrics graph's first-run selection, and the fallback of a profile saved before the per-graph selection.
FIRST_RUN_LIVE_SERIES = MappingProxyType({
    "shamatha_score": True,
    "meditation_score": False,
    "distraction": False,
    "sinking": False,
    "subtle_distraction": False,
    "native_attention": False,
    "native_meditation": False,
})


def _show_row(btn, graph, key: str) -> None:
    """A picker row's look: the series' current name, filled and bold while it shows."""
    btn.text = graph.series_name(key)
    visible = graph.is_visible(key)
    btn.bg_color = C.ACCENT if visible else C.BG_CARD
    btn.text_color = None if visible else C.TEXT_SECONDARY
    btn.bold = visible


def show_program_series(graph, plan: RunnablePlan) -> None:
    """Set the graph to EXACTLY the program's metric set, label each program custom line and mark the set as the
    program's. Shared by a program session's start, the idle preview and a program session's detail in History."""
    for slot, custom in plan.customs:
        graph.set_series_name(slot, program_line_name(custom))
    for k in graph.series_keys():
        graph.set_visible(k, k in plan.keys)
    graph.set_program_lines(plan.keys)


class GraphSeries:
    """The live metrics graph lists a formula slot only while it is valid, and a program line only while its program
    runs and computes it; a session detail lists a program session's lines while it shows them. A program's own
    series set is never saved as the profile's selection. Which lines are a program's, each graph says itself
    (`program_keys`: set by `show_program_series`, cleared by what shows the saved selection again)."""

    def __init__(self, ctx: AppContext, live_graph, formulas: FormulaSlots, formula_settings, *,
                 graphs: Callable[[], tuple]) -> None:
        self._ctx = ctx
        self._live_graph = live_graph
        self._formulas = formulas
        self._formula_settings = formula_settings
        self._graphs = graphs

    def present_picker(self, graph) -> None:
        """Open the shared multi-select series popup for `graph`.

        Reads the graph's own catalog/labels/colors, so one presenter serves
        every graph. Wired to all multi-series graphs by _wire_graph_affordances.
        For the live metrics graph, custom-formula rows also carry a Choose button
        that assigns a saved formula to that slot without leaving the picker.
        """
        is_live = graph is self._live_graph
        # The live graph's program lines are computed only while its session runs or connects (the idle preview's aren't).
        listed_program_lines = graph.program_keys if not is_live or self._ctx.session.live() else frozenset()
        rows = []
        for key in graph.series_keys():
            if key in PROGRAM_FORMULA_KEYS and key not in listed_program_lines:
                continue  # program-controlled: listed only while its program runs and computes it, or a detail shows it
            btn = StyledButton(height=dp(44))
            _show_row(btn, graph, key)
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
        slot_idx and refreshes the picker's toggle button to its new name and visible state."""
        uid = self._ctx.require_user("choose a saved formula")
        if uid is None:
            return
        formulas = self._ctx.db.get_saved_formulas(uid)

        def _choose(entry):
            inner_popup.dismiss()
            self._formula_settings.assign_saved(slot_idx, entry)
            _show_row(toggle_btn, self._live_graph, FORMULA_KEYS[slot_idx])

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
        graph.set_visible(key, visible)  # a change fires the legends' refresh, the fullscreen one too
        _show_row(btn, graph, key)

    def _pickable(self) -> list:
        """The graphs with a picker: an id to save under and more than one series to choose from."""
        return [g for g in self._graphs() if g.graph_id and len(g.series_keys()) > 1]

    def persist(self, graph) -> None:
        """Persist `graph`'s visible series under its per-graph key (on picker close).

        Skips a graph showing a program's set (the live graph under a running program or the idle preview of the one
        Settings has loaded, a detail showing a program session's): it must not overwrite the user's saved selection."""
        uid = self._ctx.user_id()
        if not (uid and graph.graph_id):
            return
        if graph.program_keys:
            return
        self._ctx.db.set_user_json_setting(
            uid, f"graph_series_{graph.graph_id}",
            [k for k in graph.visible_keys() if k not in PROGRAM_FORMULA_KEYS],
        )

    def persist_all(self) -> None:
        for graph in self._pickable():
            self.persist(graph)

    def restore(self, user_id: int) -> None:
        """Apply each graph's persisted series selection (graph_series_<id>).

        set_visible drives each graph's own legend refresh on a change. The live metrics graph
        migrates the pre-F2 toggle_<key> rows when it has no JSON yet; other graphs
        default to all-visible (their pre-picker behavior)."""
        for graph in self._pickable():
            self.apply_saved(graph, user_id)

    def apply_saved(self, graph, user_id: int) -> None:
        """Apply one graph's persisted series selection (graph_series_<id>). The live
        metrics graph migrates the pre-F2 toggle_<key> rows when it has no JSON yet and
        gates custom-formula slots on validity; other graphs default to all-visible. The live graph keeps the series
        of a session that runs or connects."""
        if graph is self._live_graph and self._ctx.session.live():
            return
        graph.set_program_lines()  # the profile's own selection replaces a program's set
        series = self._ctx.db.get_user_json_setting(user_id, f"graph_series_{graph.graph_id}")
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
            saved = self._ctx.db.get_user_setting(user_id, f"toggle_{key}")
            active = (saved == "True") if saved is not None else FIRST_RUN_LIVE_SERIES.get(key, True)
            if active:
                sel.add(key)
        if self._ctx.db.get_user_setting(user_id, "custom_formula_visible") == "True":
            sel.add("custom_formula")
        return sel
