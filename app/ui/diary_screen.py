"""The session detail, opened from History: the session's title and stats, its what-if, band power, notes and graphs,
each part a section in detail_sections/, and its CSV export."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from app.metrics.series_names import SERIES_NAMES
from app.session.scoring import recorded_score
from app.ui.detail_sections.bands import BandSection
from app.ui.detail_sections.export import open_export_dialog, show_export_result
from app.ui.detail_sections.graphs import DetailGraphs
from app.ui.detail_sections.notes import SessionNotes
from app.ui.detail_sections.stats import StatsRows
from app.ui.formatting import format_duration
from app.ui.graph_scroll import GraphAwareScrollView
from app.ui.hooks import Hook, is_wired, wire
from app.ui.session_labels import session_score_rows, session_title
from app.ui.theme import C, F, Icons, S, ThemedLabel, fill_background, text_fills_box
from app.ui.widgets.styled_button import StyledButton
from app.ui.widgets.what_if import WhatIfPanel


class DiaryScreen(Screen):
    """Shows the session it is given, its parts filled as their data arrives, and reports the user's actions through
    its hooks."""

    on_save_notes = Hook(default=False)  # (session id, **fields) -> True once saved
    on_export_csv = Hook()  # (session id, folder or None, name typed) -> (what to tell the user, whether it worked)
    on_back = Hook()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "diary"
        self._session_id: int | None = None
        root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP)
        fill_background(root, C.BG)
        page = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8), size_hint_y=None)
        page.bind(minimum_height=page.setter("height"))
        back = StyledButton(text="Back", icon=Icons.CHEVRON_LEFT, font_size=F.BODY, size_hint=(None, None),
                            width=dp(90), height=dp(32), bg_color=C.BG_CARD, text_color=C.PRIMARY, bold=False)
        back.bind(on_release=lambda *_a: self.on_back())
        page.add_widget(back)
        self._title = ThemedLabel(text="Select a session", font_size=F.H2, bold=True, color=C.TEXT, size_hint_y=None,
                                  height=dp(30), halign="center", valign="middle", shorten=True, shorten_from="right")
        text_fills_box(self._title)
        page.add_widget(self._title)
        self.stats = StatsRows(page)
        # What if the session had run against another threshold (#50): view only.
        self.what_if = WhatIfPanel(on_threshold=self._on_what_if_threshold)
        self._recorded_steps = None  # the metrics graph's line as recorded, which Reset puts back
        page.add_widget(self.what_if)
        self.bands = BandSection(page)
        self.notes = SessionNotes(page)
        wire(self.notes, on_save=self._save_notes)
        buttons = BoxLayout(size_hint_y=None, height=dp(38), spacing=S.GAP)
        export = StyledButton(text="Export CSV", bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM, height=dp(38))
        export.bind(on_release=self._on_export_pressed)
        buttons.add_widget(self.notes.save_button)
        buttons.add_widget(export)
        page.add_widget(buttons)
        self.graphs = DetailGraphs(page)
        scroll = GraphAwareScrollView()
        scroll.add_widget(page)
        root.add_widget(scroll)
        self.add_widget(root)

    def show_session(self, session: dict) -> None:
        """A session just opened: its title, stats and notes at once; the what-if, band power and graphs load."""
        self._session_id = session.get("id")
        self._title.text = session_title(session)
        score = recorded_score(session)

        def duration(key: str) -> str:
            val = session.get(key, "-")
            return format_duration(int(val)) if isinstance(val, (int, float)) else str(val)

        self.stats.show([
            ("Duration", duration("duration")),
            *session_score_rows(session),  # the scored metric, its average and threshold
            ("Time Above Threshold", duration("time_above_threshold")),
            ("Longest Streak", duration("longest_streak")),
            ("Mood Rating", str(session.get("mood_rating", "-"))),
        ])
        self.notes.show(session)
        self.what_if.show_loading()
        self.bands.show_loading()
        self.graphs.show_loading(score[0] if score is not None else None)  # a program's "program" is no series

    def show_load_failed(self) -> None:
        """The parts still waiting for data say they won't get it; the stats and notes keep working."""
        self.bands.show_failed()
        self.graphs.show_failed()
        self.what_if.show_load_failed()

    def set_what_if(self, ticks, session: dict) -> None:
        """Give the what-if panel the session's scored ticks (None: it can't rescore it), once its graphs are in: the
        metrics graph's line is then the recorded one, which Reset puts back."""
        self._recorded_steps = self.graphs.metrics.threshold_steps
        if ticks is not None and session.get("session_program"):
            note = "Each segment starts at its recorded target · nothing is saved"
            titles = [f"{s.index + 1} · {s.name or SERIES_NAMES.get(s.key, s.key)} · recorded {s.target:g}"
                      for s in ticks.segments]
        else:
            recorded = dict(session_score_rows(session))
            note = f"Recorded at {recorded.get('Threshold') or recorded.get('Threshold Used', '')} · nothing is saved"
            titles = None
        self.what_if.set_session(ticks, note, titles, "This session can't be replayed.")

    def _on_what_if_threshold(self, steps: list[tuple[int, float]] | None) -> None:
        """The metrics graph's dashed line follows the what-if, and goes back to the recorded one on Reset."""
        self.graphs.metrics.set_threshold_steps(steps if steps is not None else self._recorded_steps)

    def _save_notes(self, **fields) -> bool:
        return self._session_id is not None and bool(self.on_save_notes(self._session_id, **fields))

    def on_pre_leave(self, *args) -> None:
        # Every way out of the detail (Back, a bottom-nav tab, Android back) is a screen change: none loses an edit.
        self.notes.flush()

    def _on_export_pressed(self, *_args) -> None:
        if self._session_id and is_wired(self, "on_export_csv"):
            session_id = self._session_id
            open_export_dialog(session_id, lambda folder, name: show_export_result(
                *self.on_export_csv(session_id, folder, name)))
