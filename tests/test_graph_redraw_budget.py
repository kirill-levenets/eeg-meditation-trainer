"""New data redraws a graph within a budget: after a slow redraw the next waits, so a long session's fitted graph can't
take the main thread; the user's own actions still redraw at once."""
import time

import pytest

from app.ui import raw_eeg_screen as rg
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget


@pytest.fixture
def graph(monkeypatch):
    g = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES, viewport_seconds=60)
    g.size = (800, 400)
    draws = []
    monkeypatch.setattr(g, "_draw", lambda: draws.append(g._total_points))
    g.draws = draws
    return g


def _last_redraw_took(g, seconds: float) -> None:
    g._redraw_cost = seconds
    g._redraw_end = time.perf_counter()


def test_new_data_after_a_cheap_redraw_draws_at_once(graph):
    _last_redraw_took(graph, rg._SLOW_REDRAW_S / 2)
    graph.add_point({"shamatha_score": 50.0})
    assert graph.draws == [1]
    assert graph._deferred_redraw is None


def test_new_data_after_a_slow_redraw_waits_for_one_redraw_within_the_budget(graph):
    _last_redraw_took(graph, 0.2)
    for _ in range(3):
        graph.add_point({"shamatha_score": 50.0})
    assert graph.draws == []
    event = graph._deferred_redraw
    assert event is not None and event.timeout == pytest.approx(0.2 / rg._REDRAW_BUDGET, abs=0.1)
    event.callback(0)  # the Clock fires it
    assert graph.draws == [3]  # one redraw shows every point that waited
    assert graph._deferred_redraw is None


def test_new_data_once_the_budget_has_passed_draws_at_once(graph):
    graph._redraw_cost = 0.2
    graph._redraw_end = time.perf_counter() - 0.2 / rg._REDRAW_BUDGET - 0.01
    graph.add_point({"shamatha_score": 50.0})
    assert graph.draws == [1]


def test_a_users_action_redraws_at_once_and_drops_the_waiting_redraw(graph):
    _last_redraw_took(graph, 0.2)
    graph.add_point({"shamatha_score": 50.0})
    pending = graph._deferred_redraw
    assert pending is not None
    graph.set_visible("shamatha_score", False)
    assert graph.draws == [1]
    assert graph._deferred_redraw is None
    assert not pending.is_triggered  # cancelled: it would only have drawn the same data again
