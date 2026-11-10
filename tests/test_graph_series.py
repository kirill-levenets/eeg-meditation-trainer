import types
from unittest.mock import MagicMock

import pytest

from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.ui import graph_series
from app.ui.hooks import wire
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import StyledButton
from app.ui.widgets.band_totals import BAND_COLORS
from tests._app import reload_with


def _g(colors, scales, graph_id, names=None):
    return ScrollableGraphWidget(colors=colors, scales=scales, graph_id=graph_id, names=names)


# ---- The series picker, persistence, and restore generalized to every graph ----


def _restore(app) -> None:
    app._graph_series.restore(app._current_user_id)


def _toggle(app, graph, key: str) -> None:
    app._graph_series._toggle(graph, key, types.SimpleNamespace())


def test_json_selection_applied_per_graph(fresh_app):
    app, uid = fresh_app, fresh_app._current_user_id
    app._db.set_user_json_setting(uid, "graph_series_live_metrics", ["distraction", "sinking"])
    app._db.set_user_json_setting(uid, "graph_series_diary_freq", ["alpha", "beta"])
    _restore(app)
    graph, freq = app._live_screen.graph, app._diary_screen._freq_graph
    assert graph.is_visible("distraction") and graph.is_visible("sinking") and not graph.is_visible("shamatha_score")
    assert freq.is_visible("alpha") and freq.is_visible("beta") and not freq.is_visible("gamma")


def test_legacy_migration_only_for_live_metrics(fresh_app):
    app, uid = fresh_app, fresh_app._current_user_id
    app._db.set_user_setting(uid, "toggle_native_attention", "True")
    app._db.set_user_setting(uid, "toggle_shamatha_score", "False")
    _restore(app)
    graph = app._live_screen.graph
    assert graph.is_visible("native_attention") and not graph.is_visible("shamatha_score")
    # Diary graphs ignore the legacy live-only keys → default to all-visible, but a program's lines, which follow
    # the session shown.
    diary_m = app._diary_screen._metrics_graph
    assert set(diary_m.visible_keys()) == set(diary_m.series_keys()) - set(PROGRAM_FORMULA_KEYS)


def test_first_run_defaults(fresh_app):
    app = fresh_app  # a new profile's load restored them
    # Live metrics: FIRST_RUN_LIVE_SERIES = Shamatha only.
    assert app._live_screen.graph.visible_keys() == ["shamatha_score"]
    # Other multi-series graphs: all visible.
    band = app._live_screen.band_graph
    assert set(band.visible_keys()) == set(band.series_keys())


def test_single_series_graphs_untouched(fresh_app):
    # 1-series graphs are skipped by restore (a picker there could only blank
    # the line); their sole series stays visible.
    app = fresh_app
    _restore(app)
    assert app._live_screen.raw_graph.is_visible("eeg") and app._diary_screen._raw_eeg_graph.is_visible("eeg")


def test_toggle_flips_and_persists_per_graph(fresh_app):
    app, uid = fresh_app, fresh_app._current_user_id
    graph = app._live_screen.graph  # live: shamatha only
    _toggle(app, graph, "distraction")
    assert graph.is_visible("distraction")
    app._graph_series.persist(graph)
    assert "distraction" in app._db.get_user_json_setting(uid, "graph_series_live_metrics")

    freq = app._diary_screen._freq_graph
    _toggle(app, freq, "gamma")  # gamma was visible by default → now hidden
    assert not freq.is_visible("gamma")
    app._graph_series.persist(freq)
    assert "gamma" not in app._db.get_user_json_setting(uid, "graph_series_diary_freq")


def test_a_detail_showing_a_programs_lines_lists_them_and_saves_none_of_its_set(fresh_app, monkeypatch):
    app, uid = fresh_app, fresh_app._current_user_id
    diary = app._diary_screen._metrics_graph
    shown = frozenset({"shamatha_score", "program_formula"})
    for key in diary.series_keys():
        diary.set_visible(key, key in shown)  # what show_program_series does for a program session
    diary.set_program_lines(shown)
    listed = []

    def capture(_title, rows, footer=None, **_kw):
        listed.extend(getattr(row, "text", None) or row.children[-1].text for row in rows)
        return types.SimpleNamespace(bind=lambda **_k: None, open=lambda: None)

    monkeypatch.setattr(graph_series, "make_scroll_popup", capture)
    app._graph_series.present_picker(diary)
    assert diary.series_name("program_formula") in listed
    app._graph_series.persist(diary)
    assert app._db.get_user_json_setting(uid, "graph_series_diary_metrics") is None


def test_custom_formula_gated_on_live_graph_only(fresh_app):
    app = fresh_app
    graph, slot = app._live_screen.graph, app._formulas.evaluators[0]
    # Live metrics: custom_formula stays hidden while the formula is invalid.
    assert not slot.is_valid
    _toggle(app, graph, "custom_formula")
    assert not graph.is_visible("custom_formula")
    slot.set_formula("alpha1 * 2")
    _toggle(app, graph, "custom_formula")
    assert graph.is_visible("custom_formula")

    # Diary metrics: custom_formula is recorded data → toggles freely.
    diary_m = app._diary_screen._metrics_graph
    slot.set_formula("")
    diary_m.set_visible("custom_formula", False)
    _toggle(app, diary_m, "custom_formula")
    assert diary_m.is_visible("custom_formula")


def test_custom_formula_2_gated_on_its_own_slot(fresh_app):
    # The per-slot gate must key off slot 1's evaluator, not slot 0's.
    app = fresh_app
    graph = app._live_screen.graph
    app._formulas.evaluators[0].set_formula("alpha1 * 2")  # slot 0 runs; slot 1 doesn't
    _toggle(app, graph, "custom_formula_2")
    assert not graph.is_visible("custom_formula_2")
    app._formulas.evaluators[1].set_formula("beta1 * 2")
    _toggle(app, graph, "custom_formula_2")
    assert graph.is_visible("custom_formula_2")


@pytest.mark.parametrize("picked", [False, True])
def test_the_custom_formulas_shown_or_hidden_choice_survives_reload(fresh_app, picked):
    # Reload round-trip: a user who HID the live custom_formula line but kept a valid saved formula must not have it
    # force-shown on next launch, and one who showed it keeps it; the load is the production one (the profile's
    # formulas, then the graphs' series).
    app = fresh_app
    saved = ["shamatha_score", "custom_formula" if picked else "distraction"]
    reload_with(app, {"graph_series_live_metrics": saved}, custom_formula="alpha + beta")
    assert app._formulas.evaluators[0].is_valid  # formula loaded
    assert app._live_screen.graph.is_visible("custom_formula") is picked


def _threshold_ys(g) -> tuple[list[float], float, float]:
    """The y of every threshold dash the graph drew, and its plot area's bottom and top (its outer grid lines)."""
    from app.ui.theme import C
    ys, grid, colour = [], [], None
    for ins in g._gfx.children:
        if ins.__class__.__name__ in ("Color", "ThemedColor"):
            colour = tuple(round(v, 3) for v in ins.rgba)
        elif ins.__class__.__name__ == "Line":
            pts = list(ins.points)[1::2]
            if colour == tuple(round(v, 3) for v in C.THRESHOLD_LINE):
                ys += pts
            elif colour == tuple(round(v, 3) for v in C.GRAPH_GRID):
                grid += pts
    return ys, min(grid), max(grid)


def test_a_threshold_below_zero_is_drawn_on_the_graphs_floor_like_its_values():
    # Values below 0 are drawn on the floor; a threshold there must not fall under the graph.
    from app.ui.raw_eeg_screen import ScrollableGraphWidget
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100}, size=(400, 200), pos=(0, 0))
    for v in (-40.0, 10.0, 60.0):
        g.add_point({"a": v})
    for draw in (lambda: g.set_threshold(-30.0), lambda: g.set_threshold_steps([(0, -30.0)])):
        draw()
        ys, bottom, top = _threshold_ys(g)
        assert ys
        assert all(bottom <= y <= top for y in ys), (ys, bottom)


def test_the_live_screen_and_a_sessions_detail_draw_a_series_in_one_colour():
    from app.ui.diary_screen import DiaryScreen
    from app.ui.live_session import LiveSessionScreen
    live, detail = LiveSessionScreen(), DiaryScreen()
    for key in METRICS_COLORS:
        assert detail._metrics_graph.series_color(key) == live.graph.series_color(key), key
    for key in BAND_COLORS:
        assert detail._freq_graph.series_color(key) == live.band_graph.series_color(key), key


def test_choosing_a_saved_formula_renames_its_picker_row_at_once(fresh_app, monkeypatch):
    # The open picker's row follows Choose at once, as the graph line and the legend do.
    app = fresh_app
    app._db.add_saved_formula(app._current_user_id, "Calm", "alpha1 * 2")
    shown_rows = []
    monkeypatch.setattr(graph_series, "make_scroll_popup",
                        lambda title, rows, **kw: shown_rows.extend(rows) or MagicMock())
    row = StyledButton(text="Formula 1")

    app._graph_series._choose_saved_formula(0, row)
    shown_rows[0].dispatch("on_release")

    assert app._live_screen.graph.series_name("custom_formula") == "Calm"
    assert row.text == "Calm"  # the open picker's row says what the line and the legend say


def test_showing_a_series_already_shown_or_naming_it_as_named_changes_nothing():
    g = _g(METRICS_COLORS, METRICS_SCALES, "diary_metrics")
    changes, redraws = [], []
    wire(g, on_series_change=lambda: changes.append(1))
    g._redraw = lambda: redraws.append(1)
    g.set_visible("shamatha_score", g.is_visible("shamatha_score"))
    g.set_series_name("custom_formula", g.series_name("custom_formula"))
    assert changes == [] and redraws == []
    g.set_visible("shamatha_score", not g.is_visible("shamatha_score"))
    g.set_series_name("custom_formula", "Calm")
    assert changes == [1, 1] and redraws == [1, 1]
