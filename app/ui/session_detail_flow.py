"""The session detail opened from History: it shows at once from the row History holds, then its band totals and graphs
load on a worker and fill in one section per frame (#59)."""
import threading
from collections.abc import Callable

from kivy.clock import Clock

from app.crash_handler import report_soft_error
from app.logger import logger, timed
from app.metrics.formula_slots import session_formulas
from app.session.session_program import recorded_plan
from app.session.what_if import scored_ticks
from app.ui.diary_screen import detail_graph_data


class SessionDetailFlow:
    """Opens a session's detail and fills it; a result for an earlier open, or for a detail no longer on screen, is
    dropped (`_detail_load`)."""

    def __init__(self, db, diary_screen, history_screen, sm, graph_series, *, user_id: Callable[[], int | None],
                 on_main: Callable[[Callable], None], switch_screen: Callable[[str], None]) -> None:
        self._db = db
        self._diary_screen = diary_screen
        self._history_screen = history_screen
        self._sm = sm
        self._graph_series = graph_series
        self._user_id = user_id
        self._on_main = on_main
        self._switch_screen = switch_screen
        self._detail_load = 0  # the session-detail open in progress; a result for an earlier one is dropped
        self._session_detail_back = "history"

    def on_session_select(self, session_id: int) -> None:
        """Open the session detail at once (#59): title, stats and notes from the row History holds, so they can be read
        and edited at once; the band totals and graphs load on a worker and fill in, one section per frame."""
        session = self._history_screen.session_by_id(session_id)
        if session is None:  # not in History's list: nothing was tapped
            logger.warning(f"Session detail: session {session_id} isn't listed")
            return
        self._detail_load += 1
        token = self._detail_load
        d = self._diary_screen
        uid = self._user_id()
        with timed("diary.open"):
            d.set_session_formulas({}, session_formulas(session)[1])  # the legend's names from the first frame
            d.show_session_detail(session)
            d.set_metrics_threshold(float(session.get("threshold_used", 50)))
            d.set_program(session.get("session_program", ""))
            plan = recorded_plan(session.get("session_program") or "")
            if plan is None and uid:  # the profile's own selection, whatever the last session showed
                self._graph_series.apply_saved(d._metrics_graph, uid)
            d.show_program_lines(plan)  # the program's mark goes last: lines it still shows are never saved
            bv = {}
            if uid:
                bv = self._db.get_user_json_setting(uid, "band_breakdown_view", {}) or {}
            d.set_band_view_state(bv.get("mode", "detailed"), bv.get("sort", "band"), bool(bv.get("desc", False)))
            self._session_detail_back = self._sm.current
            self._sm.current = "diary"
        threading.Thread(target=self._load_session_detail, args=(token, session_id, session), daemon=True,
                         name="DiaryLoad").start()

    def _load_session_detail(self, token: int, session_id: int, session: dict) -> None:
        """Worker: the band totals (one query) first, then the metric rows, read once for the graphs and the formula
        replay, built into each graph's data off the main thread; each result goes to _fill_detail as it is ready."""
        d = self._diary_screen
        try:
            with timed("diary.band_totals"):
                totals = self._db.get_session_band_totals(session_id)
            self._on_main(lambda: self._fill_detail(token, [lambda: d.set_band_totals(totals)]))
            with timed("diary.get_metrics"):
                rows = self._db.get_session_metrics(session_id)
            with timed("diary.compute_formulas"):
                series, names = self.compute_session_formulas(session_id, session, rows)
            with timed("diary.graph_data"):
                data = detail_graph_data(rows, series)
        except Exception as e:  # noqa: BLE001 - any failure: the sections say so, never "Loading…" for good
            logger.exception(f"Session detail load failed for session {session_id}")

            def failed(err=e) -> None:
                d.show_load_failed()
                report_soft_error("session_detail_load_failed", f"Session {session_id}'s graphs: {err}")

            self._on_main(lambda: self._fill_detail(token, [failed]))
            return

        def fill(section: str) -> None:
            if section == "metrics":
                d.set_session_formulas(series, names)  # the formula lines' names, before their graph
            d.fill_graph(section, data)

        try:
            ticks = scored_ticks(session, rows, series)
            what_if = lambda: d.set_what_if(ticks, session)
        except Exception:  # noqa: BLE001 - a row it can't score must not take the graphs down with it
            logger.exception(f"What-if scoring failed for session {session_id}")
            what_if = d.show_what_if_failed

        self._on_main(lambda: self._fill_detail(token, [*(lambda s=s: fill(s) for s in d.graph_fill_order()),
                                                        what_if]))

    def _fill_detail(self, token: int, steps: list) -> None:
        """Run one step per frame, so no frame holds them all, while this open is the detail on screen: after Back,
        another tab or another session's open, the rest is dropped."""
        if token != self._detail_load or self._sm.current != "diary" or not steps:
            return
        steps[0]()
        if len(steps) > 1:
            Clock.schedule_once(lambda dt: self._fill_detail(token, steps[1:]), 0)  # 0 from a callback: next frame

    def persist_band_view(self, mode: str, sort_by: str, descending: bool) -> None:
        """Persist the diary band-table view (mode/sort) per user."""
        uid = self._user_id()
        if not uid:
            return  # silent-ok: view-pref persistence; no concrete user = nothing to save
        self._db.set_user_json_setting(uid, "band_breakdown_view", {"mode": mode, "sort": sort_by, "desc": descending})

    def compute_session_formulas(self, session_id: int, session: dict,
                                 rows: list[dict] | None = None) -> tuple[dict, dict]:
        """Recompute the session's recorded formula series + names from its band powers, over `rows` when already
        read. Pure DB + compute, no Kivy — safe to call off the main thread."""
        evaluators, names = session_formulas(session)
        series = self._db.recompute_formula_series(session_id, evaluators, rows) if evaluators else {}
        return series, names

    def inject_session_formulas(self, session_id: int, session: dict) -> None:
        """Recompute + apply the session's recorded formulas (synchronous)."""
        series, names = self.compute_session_formulas(session_id, session)
        self._diary_screen.set_session_formulas(series, names)

    def on_diary_back(self) -> None:
        """Return from diary detail to previous screen (usually history)."""
        self._switch_screen(self._session_detail_back)
