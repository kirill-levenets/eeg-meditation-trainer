"""The Session screen's parts: its controls enable what each state takes and report their taps, its graphs show one view
at a time with only that view's graphs drawing, and each kind of graph is drawn alike on it and on the session
detail."""
import pytest
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout

from app.metrics.series_names import SERIES_NAMES
from app.ui.diary_screen import DiaryScreen
from app.ui.hooks import wire
from app.ui.live_session import LiveSessionScreen
from app.ui.session_sections.control_bar import ControlBar
from app.ui.session_sections.end_card import EndCard
from app.ui.session_sections.live_graphs import LiveGraphs
from app.ui.theme import THEMES, C


def _enabled(bar: ControlBar) -> dict:
    return {"start": not bar.start.disabled, "duration": not bar.duration.button.disabled,
            "pause": None if bar.pause.disabled else bar.pause.text, "stop": not bar.stop.disabled,
            "mark": not bar.mark.disabled}


def test_the_controls_take_what_each_state_allows():
    bar = ControlBar()
    idle = {"start": True, "duration": True, "pause": None, "stop": False, "mark": False}
    assert _enabled(bar) == idle
    bar.show_running()
    assert _enabled(bar) == {"start": False, "duration": False, "pause": "Pause", "stop": True, "mark": True}
    bar.show_paused()
    assert _enabled(bar) == {"start": False, "duration": False, "pause": "Resume", "stop": True, "mark": False}
    bar.show_idle()
    assert _enabled(bar) == idle and bar.pause.text == "Pause"


def test_each_control_reports_its_tap():
    bar, tapped = ControlBar(), []
    wire(bar, **{hook: (lambda h=hook: tapped.append(h)) for hook in ("on_start", "on_pause", "on_stop", "on_mark")})
    for button in (bar.start, bar.pause, bar.stop, bar.mark):
        button.dispatch("on_release")
    assert tapped == ["on_start", "on_pause", "on_stop", "on_mark"]


def test_one_view_at_a_time_and_only_its_graphs_draw():
    graphs = LiveGraphs()
    assert graphs.view == "metrics" and graphs.metrics._drawing_enabled
    assert not graphs.raw._drawing_enabled and not graphs.band._drawing_enabled
    graphs.toggle.buttons["raw"].dispatch("on_release")
    assert graphs.view == "raw" and graphs.area.children == [graphs._raw_view] and graphs.toggle.chosen == "raw"
    assert not graphs.metrics._drawing_enabled and graphs.raw._drawing_enabled and graphs.band._drawing_enabled
    graphs.toggle.buttons["metrics"].dispatch("on_release")
    assert graphs.view == "metrics" and graphs.area.children == [graphs._metrics_view]
    assert graphs.metrics._drawing_enabled and not graphs.raw._drawing_enabled


@pytest.fixture
def theme():
    saved = C.theme_name
    yield
    C.set_theme(saved)


def test_each_kind_of_graph_is_drawn_alike_on_both_screens(theme):
    live, detail = LiveSessionScreen().graphs, DiaryScreen().graphs
    for on_live, on_detail in ((live.metrics, detail.metrics), (live.raw, detail.raw), (live.band, detail.freq)):
        assert on_live._colors is on_detail._colors and on_live._scales is on_detail._scales
        assert (on_live._names, on_live._sample_rate, on_live._viewport_points, on_live._bipolar, on_live._auto_scale) \
            == (on_detail._names, on_detail._sample_rate, on_detail._viewport_points, on_detail._bipolar,
                on_detail._auto_scale)
    for name in THEMES:  # the raw EEG line in its theme's colour on the detail too
        C.set_theme(name)
        assert detail.raw.series_color("eeg") == live.raw.series_color("eeg") == C.resolve(C.MEDITATION)


def _legend(graphs: LiveGraphs) -> list[str]:
    return [w.text for w in reversed(graphs._legend.children)]


def test_the_series_a_program_segment_trains_is_marked_in_the_legend_and_the_stats_strip():
    screen = LiveSessionScreen()
    for key in ("shamatha_score", "meditation_score"):
        screen.graphs.metrics.set_visible(key, True)
    screen.set_training_series("meditation_score")
    marked = [text for text in _legend(screen.graphs) if "»" in text]
    assert len(marked) == 1 and SERIES_NAMES["meditation_score"] in marked[0]
    assert any(SERIES_NAMES["meditation_score"] in w.text for w in screen.stats.walk() if hasattr(w, "text"))
    screen.set_training_series(None)  # a segment's end, or a simple session: no mark
    assert not [text for text in _legend(screen.graphs) if "»" in text]


def test_a_tall_end_card_scrolls_within_the_screen():
    card = EndCard(FloatLayout())
    card.show(1, {"duration": 600, "time_above_threshold": 300, "longest_streak": 60}, title="Morning sit")
    card.height, card._panel.height = dp(150), dp(400)  # a panel taller than the screen: a landscape phone, large text
    pad = card.padding
    assert card._scroll.height == dp(150) - pad[1] - pad[3]
    card._panel.height = dp(100)  # one that fits: as tall as itself
    assert card._scroll.height == dp(100)
