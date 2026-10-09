"""One table of the headset's bands: key, name and frequency range, in the order the headset sends them; the band table,
the band graphs and the stream all read it."""

import pytest
from kivy.base import EventLoop
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window

from app.eeg.band_spec import BANDS, GROUP_NAMES, GROUPS, group_powers, range_text
from app.eeg.neurosky_stream import BAND_NAMES
from app.metrics.custom_formula import ALLOWED_VARIABLES
from app.ui.diary_screen import DiaryScreen, detail_graph_data
from app.ui.live_session import LiveSessionScreen
from app.ui.theme import F
from app.ui.widgets.band_totals import _W_NAME, BandTotalsView

# NeuroSky's ThinkGear Communications Protocol, ASIC_EEG_POWER (0x83): "delta (0.5 - 2.75Hz), theta (3.5 - 6.75Hz),
# low-alpha (7.5 - 9.25Hz), high-alpha (10 - 11.75Hz), low-beta (13 - 16.75Hz), high-beta (18 - 29.75Hz),
# low-gamma (31 - 39.75Hz), and mid-gamma (41 - 49.75Hz)"
PROTOCOL = [("delta", 0.5, 2.75), ("theta", 3.5, 6.75), ("alpha1", 7.5, 9.25), ("alpha2", 10, 11.75),
            ("beta1", 13, 16.75), ("beta2", 18, 29.75), ("gamma1", 31, 39.75), ("gamma2", 41, 49.75)]


def test_the_bands_are_the_protocols_in_its_order():
    assert [(b.key, b.low_hz, b.high_hz) for b in BANDS] == PROTOCOL


def test_the_stream_reads_the_bands_in_that_order():
    assert BAND_NAMES == tuple(key for key, _low, _high in PROTOCOL)


def test_the_names_stay_the_apps():
    assert [b.name for b in BANDS] == ["Delta", "Theta", "Alpha 1", "Alpha 2", "Beta 1", "Beta 2", "Gamma 1", "Gamma 2"]
    assert [(g.key, g.name) for g in GROUPS] == [("delta", "Delta"), ("theta", "Theta"), ("alpha", "Alpha"),
                                                 ("beta", "Beta"), ("gamma", "Gamma")]


def test_a_grouped_band_spans_its_sub_bands():
    for group in GROUPS:
        subs = [b for b in BANDS if b.group == group.key]
        assert subs
        assert (group.low_hz, group.high_hz) == (min(b.low_hz for b in subs), max(b.high_hz for b in subs))
    assert [(g.key, g.low_hz, g.high_hz) for g in GROUPS[2:]] == [("alpha", 7.5, 11.75), ("beta", 13, 29.75),
                                                                   ("gamma", 31, 49.75)]


def test_every_band_and_group_is_a_formula_variable():
    assert {b.key for b in BANDS} | {g.key for g in GROUPS} <= ALLOWED_VARIABLES


def test_a_grouped_band_sums_its_sub_bands():
    power = {"delta": 1.0, "theta": 2.0, "alpha1": 3.0, "alpha2": 4.0, "beta1": 5.0, "beta2": 6.0, "gamma1": 7.0,
             "gamma2": 8.0}
    assert group_powers(power.__getitem__) == {"delta": 1.0, "theta": 2.0, "alpha": 7.0, "beta": 11.0, "gamma": 15.0}


def test_the_shared_names_cant_be_changed_in_place():
    with pytest.raises(TypeError):
        GROUP_NAMES["alpha"] = "Renamed"


def test_a_range_reads_in_hertz():
    assert [range_text(b) for b in BANDS[:4]] == ["0.5–2.75 Hz", "3.5–6.75 Hz", "7.5–9.25 Hz", "10–11.75 Hz"]
    assert range_text(GROUPS[2]) == "7.5–11.75 Hz"


# ---- the band table ----


def test_each_row_shows_its_range_under_its_name():
    view = BandTotalsView()
    assert {k: lbl.text for k, lbl in view._range_labels.items()} == {b.key: range_text(b) for b in BANDS}
    view.set_view_state("grouped", "band", False)
    assert {k: lbl.text for k, lbl in view._range_labels.items()} == {g.key: range_text(g) for g in GROUPS}


def test_names_and_ranges_fit_the_name_column():
    for band in (*BANDS, *GROUPS):
        for text, size in ((band.name, F.SMALL), (range_text(band), F.TINY)):
            label = CoreLabel(text=text, font_size=size)
            label.refresh()
            assert label.texture.size[0] <= _W_NAME, text


@pytest.mark.parametrize("mode", ["detailed", "grouped"])
def test_no_row_falls_outside_the_table(mode):
    EventLoop.ensure_window()
    view = BandTotalsView(size_hint_x=None, width=336)
    view.set_view_state(mode, "band", False)
    Window.add_widget(view)
    try:
        for _ in range(4):
            EventLoop.idle()
        assert min(child.y for child in view.children) >= view.y - 0.5
        assert max(child.top for child in view.children) <= view.top + 0.5
    finally:
        Window.remove_widget(view)


# ---- the band graphs ----


SAMPLE = {"delta": 1.0, "theta": 2.0, "alpha1": 3.0, "alpha2": 4.0, "beta1": 5.0, "beta2": 6.0, "gamma1": 7.0,
          "gamma2": 8.0}


def test_the_live_band_graph_plots_the_grouped_powers():
    screen = LiveSessionScreen()
    screen.add_raw_sample(dict(SAMPLE))
    plotted = {key: points[-1] for key, points in screen._band_graph._data.items()}
    assert plotted == group_powers(SAMPLE.__getitem__)
    assert screen._raw_graph._data["eeg"][-1] == sum(SAMPLE.values())


def test_the_detail_band_graph_plots_the_grouped_powers():
    row = {f"{key}_raw": value for key, value in SAMPLE.items()}
    series, _markers = detail_graph_data([row], {})["freq"]
    assert {key: values[-1] for key, values in series.items()} == group_powers(SAMPLE.__getitem__)


def test_the_band_graphs_name_their_bands_from_the_table():
    names = {g.key: g.name for g in GROUPS}
    assert LiveSessionScreen()._band_graph._names == names
    assert DiaryScreen()._freq_graph._names == names
