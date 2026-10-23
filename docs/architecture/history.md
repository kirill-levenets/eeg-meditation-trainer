# History

The History screen: calendar/14-day chart, totals, the RecycleView session list, select mode.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## History screen

- **History screen** (`history_screen.py`): a chart, `CalendarHeatmap` (GitHub-style, by average shamatha) or `Last14DaysBars` (a bar per day), with the Cal / 14d buttons beside it.
  Both take the same `day_avg` dict (`set_data(day_values)`) and the `on_day_tap` hook, so tap-to-filter works in both.
  The per-user setting `history_view_mode` (`"calendar"` | `"bars"`, default `"calendar"`) selects one through `HistoryScreen.set_view_mode(mode)`.
  **Totals table** (#58): Day / Week / Month rows around the filtered day, or today when none, then an All time row (`period_totals.ALL_TIME`, `date.min`–`date.max`, the same whichever day is shown);
  columns Total, On target, Best streak.
  `app/ui/period_totals.py` is the pure model:
  `periods_around(day, today)` gives `(label, first day, last day)` for the day, its Monday–Sunday week (the calendar's) and its month, labelled "Wed 7 Oct", "28 Sep – 4 Oct", "October";
  a day or month of another year than today's says which ("Tue 30 Dec 2025", "December 2025").
  The list heading names a picked day the same way (`day_text(day, today)`, which the day row takes too), "Fri 9 Oct (3 sessions)"; its row grows when the heading wraps at a larger text size (`fit_row_to_text`).
  `period_totals(sessions, start, end)` sums `duration` and `time_above_threshold` and takes the max `longest_streak` (a streak doesn't span sessions) over the sessions whose day falls in the range;
  "on target" is each session against its own target, a program's segments and a moved threshold included (recorded since #83).
  Sessions from before #51 measured their time above on Meditation; the sum takes each as stored.
  A session's day is `session_day(session)` (`date_time[:10]`, compared as strings: ISO dates order as strings do), which the calendar's day buckets and the day filter use too;
  the totals run no query, only over History's own session list.
  The table is built once (`_build_totals`) and refilled by `_update_totals` from `_set_day_data` (load, delete), `_set_filter` (tap, Show all) and `on_pre_enter`;
  `on_pre_enter` (also called from `_refresh_ui_after_resume` when History is the current screen) re-runs `_set_day_data` only when `_today()` differs from the day it last drew for (`_drawn_for`).
  The calendar, the bars and the totals all take "today" from `_today()`, and an entry on the same day redraws nothing; a period without sessions shows "–".
  `_place_totals`, bound to the page's width, puts the table under the chart, or beside it (between the chart and the Cal / 14d buttons; `_TOTALS_BESIDE_W` = 290 dp, its widest texts) once the page fits the heatmap at its smallest cells next to it:
  `_TOTALS_BESIDE_FROM`, from the heatmap's margins, weeks and minimum cell, ~670 dp.
  On a landscape phone (~730 dp) the full-width heatmap is ~230 dp tall and leaves the list no room under it; beside the table it is ~170 dp.
  A narrower landscape window keeps the table under the chart, where the heatmap would otherwise draw beneath it.
  The chart row and the table (when under it) live in one `_chart_area` (vertical, `minimum_height` → `height`).
  The chevron right after the title, which takes its text's width (`_btn_collapse`, a `theme.FoldChevron` driven by a `theme.Fold`), folds `_chart_area` away by **detaching** it from the page (`fold_away`) and puts it back under `_title_row`;
  the list takes the room, and nothing is hidden in place (a disabled or zero-height widget still takes taps).
  `FoldChevron` is the one fold button, also the session detail's: the accordion's chevrons, down open and right folded (`show_folded` through `StyledButton.set_icon`), "Hide"/"Show" without the icon font;
  40 dp wide, as an icon-only `StyledButton` narrower than ~36 dp crops its glyph to a tick.
  Folding leaves the tapped day and the totals untouched.
  The state is the per-user registry setting `history_chart_collapsed` (`chart_collapsed` / `set_chart_collapsed` on the screen); the fold's `on_chart_collapse` hook persists it.
  **Multi-select CSV export** (issue #7): a **Select** button enters select mode;
  `set_select_mode(on)` re-syncs the rows on screen so each gains a leading checkbox and drops its rename/delete (attached and detached, not hidden in place, which keeps the touch layer clean; no row is rebuilt, see [Session list](#session-list)).
  In select mode the `_list_touch_down` router toggles a row's selection on tap, and Select all selects every session in the current filter, including rows never shown.
  A `RevealBox` action bar (Export N / Delete N / Select all / Cancel) is attached only in select mode.
  **Delete N** (#57) → `delete_selected()` → `_confirm_delete(ids)`, the one confirm for a row's delete and the selection (one session: its `session_title`; several: the count, the days and, when they span profiles, how many);
  then `on_delete_sessions(ids, done)`: `done(True)` ends select mode, a failure keeps the selection.
  The confirm is the shared `theme.confirm_popup`, which decides once: Kivy still delivers taps to a popup while it fades out, so a Delete tapped during the fade after Cancel would otherwise delete the selection.
  A selection survives a day-filter change, as Export's does: the count on the button and the confirm's day span show what goes.
  `_selected_ids` and `toggle_session_selection` / `select_all_shown` / `export_selected` are the model (unit-tested).
  `export_selected` calls the `on_export_sessions` hook with sorted ids → `AppManager._on_export_sessions_csv`:
  it loops `export_session_csv` off-thread into `csv_export.build_sessions_zip(path, {sid: csv})` (one `session_<id>.csv` entry each, skips empty) and delivers it through the shared `android_share.copy_to_documents` (desktop and Android).
- **The chart's period** (#44).
  Both charts are `_DayChart`s that `_draw` `window(end)` for the one period end `HistoryScreen` owns, read through their `period_source` hook:
  `period_end` is today plus `_period_offset` days (0 for today's page, negative for an earlier one).
  Kept as an offset, a page stays as many days back as the day moves on, still meeting today's, with no bookkeeping at midnight.
  A chart off screen doesn't draw (`_redraw` is a no-op while detached); `set_view_mode` draws the one it shows.
  It has to: upright on a narrow phone the calendar keeps its smallest cells, as tall as the bars, so a chart shown again lands where it was and no size or position change redraws it.
  - **Windows:** `Last14DaysBars.window(end)` is the 14 days ending at `end`.
    `CalendarHeatmap.window(end)` is `WEEKS_VISIBLE` (18) whole weeks from a Monday, the last one `end`'s, but never past today:
    drawing only up to `end` would leave each page's last-week days after `end` on no page, since a page steps 18 weeks.
  - **Paging:** `shift_period(direction)` steps the shown view's `step(end, ±1)` (14 days or 18 weeks).
    Forward stops at today (an offset at or past 0 becomes 0); back stops once the window holds the first session (`_first_day`, from the day buckets).
  - **Controls:** ‹ and › (`C.PRIMARY` glyphs on the card, so a disabled one greys) around the period's dates (`period_text`: `period_totals.day_range`, the totals' week format, plus the year wherever it isn't this one);
    a tap on the dates goes back to today.
    `_place_totals` places the row with the table: upright, over the chart inside `_graph_wrap`, so `_graph_row` is the chart's height plus `_PERIOD_H` (`_fit_graph_row`);
    sideways, over the table in `_side_col` beside the chart, which is taller than both, so the list loses nothing.
    Switching views keeps the period end; another profile (`load_sessions(keep_filter=False)`) starts at today, like the day filter.
  - **Touches:** `_DayChart` grabs a touch on the chart, a wheel tick excepted, and decides on the lift.
    A sideways move of at least `_SWIPE` (40 dp), more sideways than vertical, pages (right brings earlier days in);
    one within `_TAP_SLOP` (20 dp) is a tap on the day under where the finger came down;
    anything between does nothing, so a swipe that starts on a day picks none.
    The day filter doesn't follow the period: a picked day stays picked on any page, named by the date label over the list.

## Session list

- **The History list is a RecycleView** (#42):
  `_SessionList` (`_StableScrollView` + `RecycleView`) holds one data item per shown session (`_item(session)`: sid, the `session_labels` title, stats line and notes line, score colour, `card_h`, `height`);
  it builds `_SessionRow` widgets only for the rows on screen, reused while scrolling.
  So a load, a day filter, Show all or Select/Cancel costs the rows on screen, not a widget tree per session (16 widgets each, seconds on the phone with a few hundred sessions); a load shows no spinner.
  State a row shows but the session doesn't own (`_select_mode`, `_selected_ids`, `_renaming_sid`) lives on the screen, and `_SessionRow.sync(owner)` applies it from `refresh_view_attrs` **and** `on_parent`:
  Kivy reuses a row that returns to the index it last showed *without* calling `refresh_view_attrs`, so it would keep the checkbox or editor of a change made while it was off screen.
  The row keeps its owner as a `weakref`: Kivy keeps unused rows in a module-level cache, `kivy.uix.recycleview.views._cached_views`;
  a strong owner would keep every dropped History screen alive, re-rendering its labels on each text size or theme change (`tests/test_history_list.py` checks it).
  `_sync_rows()` re-syncs the visible rows after a select-mode or selection change (no data change, no new widgets).
  Every list operation is a data update: `_show_sessions` (a new list, from the top);
  `remove_sessions(ids)` drops the items and the model entries (`_sessions`, `_shown`, `_selected_ids`), refreshes the header count and the charts' `day_avg` via `_set_day_data()`, and keeps the scroll position and any day filter;
  `_update_item(sid)` re-derives one item's name and height after a rename opens, closes or saves.
  Inline rename is one editor (`_rename_row`, a `theme.RenameRow`, with its `_rename_input`) attached to the row showing `_renaming_sid`, whose item is `_RENAME_H` taller;
  a row scrolled off screen detaches it (`on_parent(None)`) and its focus drops unless a row takes it back (`_rename_focus_check`), so the editor follows its session with the typed text.
  The pencil focuses it a frame later (`RenameRow.focus_soon`, only if it is still shown): Kivy unfocuses every input a tap didn't land on after that tap's touch-up, so focusing it in the tap leaves no keyboard.
  `load_sessions` keeps only selected ids that are in the new list: another profile's would be exported with it.
  Row height comes from the data, not from measured widgets: `_ROW_H` (two lines) or `_ROW_H_NOTES` (three, when the session has notes; the notes label is detached, not emptied, on a two-line row), plus `_RENAME_H` while the editor is open;
  every row label is one line, cut with an ellipsis (`shorten`).
  **Kivy's ScrollView rescales an overscroll** (the blank list, rows built and none visible until restart, #56):
  on every content-height change `_update_effect_y_bounds` re-derives the effect's pixel position as `max * scroll_y`, and past an edge `scroll_y` is outside [0, 1];
  while the list is overscrolled (a fling past the end) and its height changes, the overscroll in pixels grows with the list, the damped-scroll spring pumps it further and the view runs off the content.
  The content height comes from the data, but still changes under the user (a delete, the select bar showing).
  So when it really changes `_StableScrollView._update_effect_y_bounds` keeps the **pixel offset from the top** (no overscroll growth, no rounding drift, nothing sliding under the finger);
  when the bounds are unchanged it defers to Kivy, which calls it on every touch start/stop: a clamp there would kill the normal edge bounce.
  A new list starts with `effect_y.reset(effect_y.max)` (top, velocity and overscroll 0), since a fling still in flight overwrites an assigned `scroll_y`.
  Scroll programmatically through the effect (`effect_y.reset(effect_y.max * y)`): an assigned `scroll_y` leaves the effect's value behind and its next update moves the list back.
  Any other ScrollView whose content changes while the user may be scrolling needs the same override.
  The day filter has one owner, `_set_filter(date | None)` (the filtered day, both charts' highlight, the Show-all button).
  A reload of the same profile keeps it (`load_sessions(..., keep_filter=)`, decided by `AppManager._history_view`); another profile clears it.
  `_activate_user` and `_on_user_delete` mark History dirty.
  `_sync_date_row` lays out the list heading's row: Show All attached only while a day is picked, Select only outside select mode, each detached otherwise;
  a button hidden in place would keep its room beside the heading, which then wraps, and its taps.
  `_show_sessions` sets `_shown` even for an empty list (then `_empty_label` shows): a stale `_shown` would let Select show and export the previous profile's sessions.
  `_log_list_state` logs the session count, the row widgets, list and viewport height, `scroll_y`, the scroll effect's value, bounds and velocity, `chart_h`, `chart_w` and `page_h`, 1 s after a new list (`settled`, cancelled by the next list).
  `chart_h` is the chart row, the chart's height plus, upright, the period row's (`_PERIOD_H`, 28 dp): the bars' fixed 132 dp, the calendar's width-derived (~150 dp upright).
  `chart_w` is the calendar's width: Kivy's default 100, or 0, while the 14-day bars are shown, since the calendar is then detached.
  Kivy's scroll effect rounds a resting position to a whole pixel, so with a list of fractional height its top is within a pixel of `effect_y.max`, not on it.
