"""History: the chart area (a day heatmap or 14-day bars, its period and the totals) over the session list, which a day
tapped on the chart filters; the parts are in `history_sections/`."""
import datetime

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from app.logger import logger
from app.ui.formatting import format_count
from app.ui.history_sections import common
from app.ui.history_sections.chart_area import ChartArea
from app.ui.history_sections.session_list import SessionList
from app.ui.hooks import Hook, wire
from app.ui.period_totals import day_text, session_day
from app.ui.session_labels import session_title
from app.ui.theme import C, Divider, F, S, ThemedLabel, fill_background, fit_row_to_text, fit_width_to_text
from app.ui.widgets.folds import Fold, FoldChevron, RevealBox, fold_away
from app.ui.widgets.popups import confirm_popup
from app.ui.widgets.styled_button import StyledButton


class HistoryScreen(Screen):
    """The sessions History holds (`load_sessions`, kept current in place) and the day the list is filtered to: the one
    owner of both, which the chart area and the session list show."""

    on_delete_sessions = Hook()  # (ids, done) -> done(True) once deleted
    on_export_sessions = Hook()
    on_chart_collapse = Hook()  # the user folded the chart (True) or opened it

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "history"
        self._sessions: list[dict] = []
        self._filtered_date: str | None = None
        self._settled_log_ev = None
        self._current_header: str = "All sessions"
        self._build_ui()

    def _build_ui(self) -> None:
        self._root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP)
        fill_background(self._root, C.BG)
        self.chart_area = ChartArea()
        wire(self.chart_area, on_day_tap=self._on_day_tap)
        self.session_list = SessionList()
        wire(self.session_list, on_delete=self._confirm_delete, on_selection=self._update_selection_buttons)
        self._build_title_row()
        self._root.add_widget(self.chart_area)
        self._build_date_row()
        self._build_select_bar()
        self._root.add_widget(Divider())
        self._root.add_widget(self.session_list)
        self._root.bind(width=lambda _root, width: self.chart_area.place_for(width))
        self.add_widget(self._root)

    def _build_title_row(self) -> None:
        """The title, and right after it the chevron that folds the chart area away (the list gets its room)."""
        self._title_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP_SM)
        self._title = ThemedLabel(text="History", font_size=F.H1, bold=True, color=C.TEXT, size_hint_x=None)
        fit_width_to_text(self._title)
        self._btn_collapse = FoldChevron()
        self._chart_fold = Fold(self._btn_collapse,
                                lambda folded: fold_away(self._root, self.chart_area, self._title_row, folded))
        wire(self._chart_fold, on_change=lambda folded: self.on_chart_collapse(folded))
        for w in (self._title, self._btn_collapse):
            self._title_row.add_widget(w)
        self._root.add_widget(self._title_row)

    def _build_date_row(self) -> None:
        """The list heading, then Show All while a day is picked and Select outside select mode (_sync_date_row)."""
        self._date_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP)
        self._date_label = ThemedLabel(text="Tap a day to see sessions", font_size=F.BODY, color=C.TEXT_SECONDARY,
                                       halign="left", valign="middle")
        self._date_row.add_widget(self._date_label)
        self._btn_show_all = StyledButton(text="Show All", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                                          font_size=F.SMALL, size_hint_x=None, width=dp(80), height=dp(28), bold=False)
        self._btn_show_all.bind(on_release=lambda *a: self._reset_filter())
        self._btn_select = StyledButton(text="Select", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                                        font_size=F.SMALL, size_hint_x=None, width=dp(72), height=dp(28), bold=False)
        self._btn_select.bind(on_release=lambda *a: self.set_select_mode(True))
        self._date_row.add_widget(self._btn_show_all)
        self._date_row.add_widget(self._btn_select)
        fit_row_to_text(self._date_row, self._date_label, dp(28))  # centres both buttons, attached or not
        self._sync_date_row()
        self._root.add_widget(self._date_row)

    def _build_select_bar(self) -> None:
        """Select mode's actions (issue #7): RevealBox detaches them when hidden, so they can't eat taps meanwhile."""
        self._select_bar = RevealBox(dp(40), spacing=S.GAP_SM)
        self._btn_export = StyledButton(text="Export 0", bg_color=C.ACCENT, font_size=F.SMALL, height=dp(40))
        self._btn_export.disabled = True
        self._btn_export.bind(on_release=lambda *a: self.export_selected())
        self._btn_delete = StyledButton(text="Delete 0", bg_color=C.DANGER, font_size=F.SMALL, height=dp(40))
        self._btn_delete.disabled = True
        self._btn_delete.bind(on_release=lambda *a: self.delete_selected())
        self._btn_select_all = StyledButton(text="Select all", bg_color=C.BG_CARD, text_color=C.TEXT,
                                            font_size=F.SMALL, height=dp(40))
        self._btn_select_all.bind(on_release=lambda *a: self.session_list.select_all())
        self._btn_cancel = StyledButton(text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                                        font_size=F.SMALL, height=dp(40))
        self._btn_cancel.bind(on_release=lambda *a: self.set_select_mode(False))
        self._select_bar.set_content(self._btn_export, self._btn_delete, self._btn_select_all, self._btn_cancel)
        self._root.add_widget(self._select_bar)

    @property
    def chart_collapsed(self) -> bool:
        return self._chart_fold.folded

    def set_chart_collapsed(self, collapsed: bool) -> None:
        """Fold the chart area away, detached, or bring it back under the title."""
        self._chart_fold.set(collapsed)

    def on_pre_enter(self, *_a) -> None:
        self.chart_area.follow_today()

    # ── Select mode and its actions (issue #7) ──

    def set_select_mode(self, on: bool) -> None:
        """Enter or leave select mode: the list's checkboxes, the action bar, and Select gone while it is on."""
        self.session_list.set_select_mode(on)
        self._sync_date_row()
        self._select_bar.reveal(on)

    def export_selected(self) -> None:
        if self.session_list.selected_ids:
            self.on_export_sessions(sorted(self.session_list.selected_ids))

    def delete_selected(self) -> None:
        if self.session_list.selected_ids:
            self._confirm_delete(sorted(self.session_list.selected_ids))

    def _update_selection_buttons(self, n: int) -> None:
        for button, verb in ((self._btn_export, "Export"), (self._btn_delete, "Delete")):
            button.text = f"{verb} {n}"
            button.disabled = n == 0

    def _confirm_delete(self, session_ids: list[int]) -> None:
        """Confirm, then delete one session (a row's delete) or the selection (Delete N) through the one callback."""
        wanted = set(session_ids)
        sessions = [s for s in self._sessions if s.get("id") in wanted]
        if len(session_ids) == 1:
            what = f'Delete session\n"{session_title(sessions[0])}"?' if sessions else "Delete this session?"
        else:
            days = sorted({session_day(s) for s in sessions})
            span = "" if not days else f" on {days[0]}" if len(days) == 1 else f" from {days[0]} to {days[-1]}"
            what = f"Delete {format_count(len(session_ids), 'session')}{span}?"

        def _deleted(ok: bool) -> None:
            if ok and self.session_list.select_mode:
                self.set_select_mode(False)

        def _delete() -> None:
            self.on_delete_sessions(list(session_ids), _deleted)

        confirm_popup("Confirm Delete", f"{what}\nThis can't be undone.", "Delete", _delete, ok_color=C.DANGER)

    # ── The sessions ──

    def load_sessions(self, sessions: list[dict], keep_filter: bool = True) -> None:
        """All of a profile's sessions: the chart's days and totals, and the list (the filtered day's while one is)."""
        self._sessions = sessions
        # A selection holds only this list's sessions: another profile's would be exported with it.
        self.session_list.keep_selected(self.session_list.selected_ids & {s.get("id") for s in sessions})
        if not keep_filter:  # another profile: its own history, from today
            self._set_filter(None)
            self.chart_area.to_today()
        self.chart_area.set_sessions(sessions)
        if self._filtered_date:  # a reload of the same view keeps the user's day filter, as a delete does
            self._show_day(self._filtered_date)
        else:
            self._show_sessions(sessions, "All sessions")

    def remove_sessions(self, session_ids) -> None:
        """Drop deleted sessions from the model and the list, in place: the scroll position and any day filter stay."""
        gone = set(session_ids)
        if not gone:
            return
        self._sessions = [s for s in self._sessions if s.get("id") not in gone]
        self.session_list.remove(gone)
        self.chart_area.set_sessions(self._sessions)
        self._date_label.text = f"{self._current_header} ({format_count(len(self.session_list.shown), 'session')})"

    def update_session(self, sid, **fields) -> None:
        """Apply a saved edit (the fields not None) to that session in the model, in place: no reload."""
        session = next((s for s in self._sessions if s.get("id") == sid), None)
        if session is None:
            return
        session.update({k: v for k, v in fields.items() if v is not None})
        self.session_list.update(sid)

    # ── The day filter ──

    def _on_day_tap(self, date_str: str) -> None:
        """Filter sessions to the tapped day. Tap again to reset."""
        if date_str == self._filtered_date:
            self._reset_filter()
            return
        self._set_filter(date_str)
        self._show_day(date_str)

    def _set_filter(self, date_str: str | None) -> None:
        """The one owner of the day filter: the filtered day, its outline and totals in the chart area, Show All."""
        self._filtered_date = date_str
        self.chart_area.pick_day(date_str)
        self._sync_date_row()

    def _sync_date_row(self) -> None:
        """Show All while a day is picked, Select outside select mode, each detached otherwise: hidden in place, a button
        kept its room beside the heading (which wrapped) and its taps."""
        shown = [(self._btn_show_all, self._filtered_date is not None), (self._btn_select, not self.session_list.select_mode)]
        for btn, _show in shown:
            if btn.parent is not None:
                self._date_row.remove_widget(btn)
        for btn, show in shown:
            if show:
                self._date_row.add_widget(btn)

    def _show_day(self, date_str: str) -> None:
        day_sessions = [s for s in self._sessions if session_day(s) == date_str]
        try:
            nice_date = day_text(datetime.date.fromisoformat(date_str), common.today())
        except (ValueError, TypeError):
            nice_date = date_str
        self._show_sessions(day_sessions, nice_date)

    def _reset_filter(self) -> None:
        """Clear day filter and show all sessions."""
        self._set_filter(None)
        self._show_sessions(self._sessions, "All sessions")

    def _show_sessions(self, sessions: list[dict], header: str) -> None:
        """A new list under its heading, from the top; where it ended up is logged once it settles (#56)."""
        if self._settled_log_ev is not None:
            self._settled_log_ev.cancel()
            self._settled_log_ev = None
        self._current_header = header
        self._date_label.text = f"{header} ({format_count(len(sessions), 'session')})"
        self.session_list.show(sessions)
        self._settled_log_ev = Clock.schedule_once(self._log_settled, 1.0)  # a method: Clock holds it weakly

    def _log_settled(self, _dt) -> None:
        self._log_list_state("settled")

    def _log_list_state(self, tag: str) -> None:
        """The list's rows, heights and scroll state, and the chart's and page's sizes around it (#56)."""
        logger.info(f"History list {tag}: {self.session_list.state_text()} {self.chart_area.state_text()} "
                    f"page_h={self._root.height:.0f}")
