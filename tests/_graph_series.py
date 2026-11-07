"""A GraphSeries wired to an app built with __new__, as build() wires it; any dependency, or a context field, can be
given instead."""
from unittest.mock import MagicMock

from app.ui.graph_series import GraphSeries
from tests._context import context_fields, make_context


def make_graph_series(app, **deps) -> GraphSeries:
    """The app's parts; for the ones it lacks, mocks."""
    live_screen = getattr(app, "_live_screen", None)
    ctx = make_context(app, **context_fields(deps))
    formula_settings = getattr(app, "_formula_settings", None)
    return GraphSeries(ctx, MagicMock() if live_screen is None else live_screen.graph, app._formulas,
                       MagicMock() if formula_settings is None else formula_settings,
                       **{"graphs": lambda: app._all_graphs(), **deps})
