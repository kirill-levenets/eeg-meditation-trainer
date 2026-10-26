"""A GraphSeries wired to an app built with __new__, as build() wires it; any dependency can be given instead."""
from unittest.mock import MagicMock

from app.ui.graph_series import GraphSeries
from tests._program_run import make_run
from tests._program_settings import make_programs


def make_graph_series(app, **deps) -> GraphSeries:
    """The app's parts; for the ones it lacks, no program running or loaded and mocks."""
    def attr(name, default):
        value = getattr(app, name, None)
        return default() if value is None else value

    live_screen = getattr(app, "_live_screen", None)
    defaults = {"graphs": lambda: app._all_graphs(),
                "legacy_defaults": getattr(getattr(app, "_settings_screen", None), "_graph_toggles", {}),
                "user_id": lambda: app._current_user_id, "require_user": lambda action: app._require_user(action),
                "detail_program": getattr(getattr(app, "_diary_screen", None), "program_lines_of",
                                          lambda _graph: frozenset())}
    return GraphSeries(attr("_db", MagicMock), MagicMock() if live_screen is None else live_screen.graph,
                       app._formulas, attr("_program_run", make_run), attr("_program_settings", make_programs),
                       attr("_formula_settings", MagicMock), **{**defaults, **deps})
