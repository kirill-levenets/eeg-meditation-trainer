"""History's charts draw each day as one cell, the picked day outlined, and place their labels at the drawn cells: a
month's name over its first week, a bar's day under it and its score on top. A tap only reports the day."""
import datetime

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.tests.common import UnitTestTouch

from app.ui.history_sections import common
from app.ui.history_sections.charts import CalendarHeatmap, Last14DaysBars
from app.ui.hooks import wire
from app.ui.theme import ThemedLabel

TODAY = datetime.date(2026, 10, 9)  # a Friday
DATA = {"2026-10-05": 62.4, "2026-10-07": 81.0, "2026-09-30": 40.0}


@pytest.fixture
def mounted(monkeypatch):
    monkeypatch.setattr(common, "today", lambda: TODAY)
    EventLoop.ensure_window()
    charts = []

    def mount(chart_class):
        chart = chart_class(size_hint_x=None, width=dp(360), pos=(0, 0))
        Window.add_widget(chart)
        charts.append(chart)
        chart.set_data(DATA)
        return chart

    yield mount
    for chart in charts:
        Window.remove_widget(chart)


def _outlines(chart) -> list[tuple]:
    """The (x, y, w, h) of each white outline drawn: a Rectangle right after a Color(1, 1, 1, 0.9)."""
    out, colour = [], None
    for instruction in chart.canvas.children:
        if isinstance(instruction, Color):
            colour = tuple(instruction.rgba)
        elif isinstance(instruction, Rectangle) and not isinstance(instruction, RoundedRectangle) \
                and colour == (1.0, 1.0, 1.0, 0.9):
            out.append((*instruction.pos, *instruction.size))
    return out


def _labels(chart) -> list[ThemedLabel]:
    return [w for w in chart.children if isinstance(w, ThemedLabel)]


@pytest.mark.parametrize("chart_class", [CalendarHeatmap, Last14DaysBars])
def test_only_the_picked_day_is_outlined_around_its_cell(mounted, chart_class):
    chart = mounted(chart_class)
    assert _outlines(chart) == []
    chart.select("2026-10-07")
    x, y, w, h = chart._cell_positions["2026-10-07"]
    [outline] = _outlines(chart)
    assert outline == pytest.approx((x - dp(1), y - dp(1), w + dp(2), h + dp(2)))
    chart.select(None)
    assert _outlines(chart) == []


def test_a_month_is_named_over_its_first_weeks_column(mounted):
    chart = mounted(CalendarHeatmap)
    months = {label.text: label for label in _labels(chart) if len(label.text) == 3}
    assert set(months) == {"Jul", "Aug", "Sep", "Oct"}  # June starts before the 18 weeks shown
    for name, label in months.items():
        first = next(datetime.date.fromisoformat(day) for day in chart._cell_positions
                     if datetime.date.fromisoformat(day).strftime("%b") == name
                     and datetime.date.fromisoformat(day).day <= 7 and datetime.date.fromisoformat(day).weekday() <= 3)
        assert label.x == pytest.approx(chart._cell_positions[first.isoformat()][0]), name


def test_a_bar_has_its_day_under_it_and_its_score_on_top(mounted):
    chart = mounted(Last14DaysBars)
    labels = _labels(chart)
    for day, (x, y, w, h) in chart._cell_positions.items():
        centre = x + w / 2
        under = [lb for lb in labels if lb.y == pytest.approx(chart.y) and lb.center_x == pytest.approx(centre)]
        assert len(under) == 1, day
        on_top = [lb for lb in labels if lb.y == pytest.approx(y + h) and lb.center_x == pytest.approx(centre)]
        assert [lb.text for lb in on_top] == ([str(int(round(DATA[day])))] if day in DATA else []), day


@pytest.mark.parametrize("chart_class", [CalendarHeatmap, Last14DaysBars])
def test_a_tap_reports_its_day_and_leaves_the_outline_to_the_owner(mounted, chart_class):
    chart = mounted(chart_class)
    tapped = []
    wire(chart, on_day_tap=tapped.append)
    x, y, w, h = chart._cell_positions["2026-10-05"]
    touch = UnitTestTouch(x + w / 2, y + h / 2)
    touch.touch_down()
    touch.touch_up()
    assert tapped == ["2026-10-05"] and _outlines(chart) == []


def test_a_resize_leaves_one_set_of_cells_and_labels(mounted):
    chart = mounted(CalendarHeatmap)
    before = chart.height
    chart.width = dp(500)  # wider cells: a new height, which draws again inside the draw
    assert chart.height > before
    labels = [(lb.text, round(lb.x), round(lb.y)) for lb in _labels(chart)]
    assert len(labels) == len(set(labels)) == 4 + 4  # M, W, F, S and Jul to Oct
    cells = [i for i in chart.canvas.children if isinstance(i, RoundedRectangle)]
    assert len(cells) == len(chart._cell_positions) == 124  # 8 Jun to today, one cell each
