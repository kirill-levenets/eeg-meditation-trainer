"""The session detail's parts on their own: the band section and the graphs wait for their data, show it as it arrives
and say when it won't come, each on its own; the stats rows reuse their labels; the export dialog hands on the folder
and the name typed."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app import android_jni
from app.ui.detail_sections import export
from app.ui.detail_sections.bands import BandSection
from app.ui.detail_sections.graphs import DetailGraphs, detail_graph_data
from app.ui.detail_sections.stats import StatsRows
from app.ui.diary_screen import DiaryScreen
from app.ui.hooks import wire
from app.ui.widgets.popups import ThemedFileChooser

TOTALS = {"delta": 4.0, "theta": 2.0, "alpha1": 1.0, "alpha2": 1.0, "beta1": 0.5, "beta2": 0.5, "gamma1": 0.2,
          "gamma2": 0.1}
ROWS = [{"shamatha_score": 40 + i, "alpha1_raw": 100.0, "marker": 0} for i in range(6)]


def _page() -> BoxLayout:
    return BoxLayout(orientation="vertical")


def _shown(bands: BandSection):
    return bands._holder.children[0]


def test_band_totals_that_arrived_stay_when_the_rest_fails():
    bands = BandSection(_page())
    bands.show_loading()
    assert _shown(bands) is bands._placeholder and bands._placeholder.text == "Loading…"
    bands.show_totals(TOTALS)
    bands.show_failed()  # the metric rows failed after the totals came
    assert _shown(bands) is bands.totals
    bands.show_loading()  # the next session
    bands.show_failed()
    assert _shown(bands) is bands._placeholder and bands._placeholder.text.startswith("Couldn't load")


def test_each_graph_tab_shows_its_graph_once_its_data_is_in():
    graphs = DetailGraphs(_page())
    graphs.show_loading("shamatha_score")
    data = detail_graph_data(ROWS, {})
    graphs.fill("raw", data)  # the shown tab is Metrics: still waiting
    assert graphs._area.children == [graphs._placeholder] and graphs._placeholder.text == "Loading…"
    graphs._tabs.buttons["raw"].dispatch("on_release")  # a tap on Raw EEG
    assert graphs.tab == "raw" and graphs._area.children == [graphs.raw]
    assert graphs.fill_order() == ["raw", "metrics", "freq"]
    graphs._tabs.buttons["freq"].dispatch("on_release")
    graphs.show_failed()
    assert graphs._area.children == [graphs._placeholder] and graphs._placeholder.text.startswith("Couldn't load")
    graphs.show_tab("raw")
    assert graphs._area.children == [graphs.raw]  # what arrived is still shown


def test_the_legend_marks_the_series_the_session_was_scored_on():
    graphs = DetailGraphs(_page())
    graphs.show_loading("shamatha_score")
    graphs.fill("metrics", detail_graph_data(ROWS, {}))
    marked = [w.text for w in graphs._legend.children if "»" in w.text]
    assert len(marked) == 1 and graphs.metrics.series_name("shamatha_score") in marked[0]
    graphs.show_tab("freq")
    assert not [w for w in graphs._legend.children if "»" in w.text]  # band power is no score


def test_the_stats_rows_reuse_their_labels_and_size_the_grid():
    stats = StatsRows(_page())
    stats.show([("Duration", "10m"), ("Metric", "Shamatha"), ("Threshold", "50")])
    first = list(stats.rows)
    stats.show([("Duration", "5m"), ("Threshold Used", "60")])
    assert stats.rows == first[:2] and [(t.text, v.text) for t, v in stats.rows] == [("Duration", "5m"),
                                                                                       ("Threshold Used", "60")]
    assert len(stats.grid.children) == 4
    assert stats.grid.height == 2 * dp(20) + dp(4) + 2 * dp(4)  # two rows, the spacing between, the padding


def test_a_failed_load_tells_the_what_if_too():
    detail = DiaryScreen()
    detail.show_session({"id": 1, "date_time": "2026-10-10T07:30:00", "duration": 600})
    assert detail.what_if.loading
    detail.show_load_failed()
    assert not detail.what_if.loading and detail.what_if._message.text.startswith("Couldn't load")


def _dialog(monkeypatch, *, on_android: bool):
    """Open the export dialog; (its popup, what Save handed on)."""
    opened, saved = [], []
    monkeypatch.setattr(android_jni, "on_android", lambda: on_android)
    monkeypatch.setattr(export.ThemedPopup, "open", lambda self, *a, **k: opened.append(self))
    export.open_export_dialog(7, lambda folder, name: saved.append((folder, name)))
    return opened[0], saved


def _find(popup, kind):
    return [w for w in popup.content.walk() if isinstance(w, kind)]


def test_on_android_the_dialog_asks_only_the_name(monkeypatch):
    popup, saved = _dialog(monkeypatch, on_android=True)
    assert not _find(popup, ThemedFileChooser)
    name = next(w for w in popup.content.walk() if getattr(w, "text", None) == "session_7.csv")
    name.text = "morning"
    next(w for w in popup.content.walk() if getattr(w, "text", "") == "Save").dispatch("on_release")
    assert saved == [(None, "morning")]


def test_on_desktop_the_dialog_hands_on_the_folder_picked(monkeypatch, tmp_path):
    (tmp_path / "sits").mkdir()
    (tmp_path / "old.csv").write_text("")
    for picked, folder in (([], str(tmp_path)), ([str(tmp_path / "sits")], str(tmp_path / "sits")),
                           ([str(tmp_path / "old.csv")], str(tmp_path))):  # a file picked: the folder it is in
        popup, saved = _dialog(monkeypatch, on_android=False)
        (chooser,) = _find(popup, ThemedFileChooser)
        chooser.path, chooser.selection = str(tmp_path), picked
        next(w for w in popup.content.walk() if getattr(w, "text", "") == "Save").dispatch("on_release")
        assert saved == [(folder, "session_7.csv")]


def test_export_on_the_screen_shows_what_the_export_did(monkeypatch):
    """Export CSV, Save in its dialog, the flow's answer in the result popup: a failed copy is a failure."""
    detail = DiaryScreen()
    detail.show_session({"id": 7, "date_time": "2026-10-10T07:30:00", "duration": 600})
    asked, shown = [], []
    wire(detail, on_export_csv=lambda sid, folder, name: asked.append((sid, folder, name)) or ("Kept in app storage",
                                                                                               False))
    opened = []
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    monkeypatch.setattr(export.ThemedPopup, "open", lambda self, *a, **k: opened.append(self))
    monkeypatch.setattr(export, "make_message_popup", lambda title, message, buttons: shown.append((title, message))
                        or export.ThemedPopup(title=title))
    next(w for w in detail.walk() if getattr(w, "text", "") == "Export CSV").dispatch("on_release")
    (dialog,) = opened
    next(w for w in dialog.content.walk() if getattr(w, "text", "") == "Save").dispatch("on_release")
    assert asked == [(7, None, "session_7.csv")] and shown == [("Export Failed", "Kept in app storage")]
