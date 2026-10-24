# Session detail (diary)

The session detail opened from History: stats, notes, graphs, the what-if threshold panel (#50) and the band breakdown.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Detail screen

- **Diary detail** (`diary_screen.py`): session stats, notes/tags/mood, graph tabs (metrics/raw/freq).
  Opened only from History (`show_session_detail(session)`), with a back button, titled by `session_title` like its row (one line, cut with an ellipsis).
  Its stats grid (`_set_detail_rows`, like the end card's) is Duration, the `session_score_rows` rows, Time Above Threshold, Longest Streak and Mood Rating;
  the one average it shows is the scored metric's (Avg Shamatha for a session that saved no metric).
  Avg Meditation, Avg Shamatha and Time Shamatha ≥ 90 aren't on the cards but are still stored; the calendar uses Avg Shamatha.
  **Notes are never lost** (#40):
  `show_session_detail` snapshots the fields as shown (`_saved_notes_state`: what the widgets show, not the row, so an unrated session's slider shows 3), and `on_pre_leave` → `flush_notes()` saves the fields that differ (`_changes()`).
  Back, a bottom-nav tab and Android back are all screen changes, so one hook covers them.
  `_flush_on_leave` (on_pause / on_stop) flushes the detail only while it is the current screen: leaving already tried, and a retry on every pause would repeat a failed save's error (e.g. for a session deleted since).
  Leaving sends only the changed fields, so it can't rate an unrated session; **Save Notes** sends what the screen shows, mood included (so an unrated session can be saved as 3).
  A successful save moves the snapshot; a failed one stays pending and is retried on leave.
  Per-session custom-formula series are **replayed**: the load worker (`_load_session_detail`) runs `_compute_session_formulas`,
  which rebuilds the evaluators from the session's recorded `custom_formulas` JSON (`recorded_formulas`) and recomputes their series via `recompute_formula_series` over the rows it already read.
  Formula series aren't stored per tick:
  `detail_graph_data(rows, series)` takes them from the replay (a slot the session didn't record stays empty), and the metrics graph's fill step calls `set_session_formulas(series, names)` first, which names the series.
  **Try another threshold** (#50, the what-if):
  `WhatIfPanel` (`app/ui/widgets/what_if.py`) under the stats grid: threshold controls (a slider, ±5) and Reset over the time above threshold and longest streak at them, view only;
  one control for a simple session, one per segment for a program.
  The engine is `app/session/what_if.py`:
  `scored_ticks(session, rows, formula_series, replay_formulas)` gives each tick's value and recorded target and the `Segment`s the controls move.
  A simple session has one segment over every tick, its values from the stored per-tick record (#83) when every row has one;
  else from its saved metric (its stored column, or the formula replay's series for a formula slot; meditation for a session from before #51, which is what its recorded numbers were measured on) at `threshold_used`.
  A program has one segment per program segment, each with the metric the session ran it on, its target as the live session reads it (`segment_target`: a whole number, 50 when missing or unreadable
  — the graph's steps, the live goal and the start's threshold use it too) and, when it scored a custom formula's line, that formula's `name`; a segment the session never reached is dropped.
  The metric is `runnable_plan`'s, Shamatha for a formula that doesn't compile, unless the session is from an older build that scored such a formula on its own line (read as 0):
  then it is `planned_keys`, read when the record shows that line or there is no record, and a session without one then can't be replayed, as its formula has no series.
  A segment starts where the per-tick record shows the live session switching to its metric and target, searched from the last switch found:
  the live session switches on elapsed time and `TickThread._loop` drops an overrun tick, so the switch drifts off minutes x 2.
  A segment like the one before it can't be told apart, so it starts its minutes after it, capped at the next switch found;
  a segment left with no tick is dropped, and the rest keep their program `index`, which numbers their titles.
  Without a record a segment starts by its minutes, as the graph's steps do (`SessionProgram.threshold_steps(2)`), never by the row timestamp, which is the EEG stream's clock.
  Values come from the per-tick record, else from the stored columns and the program's formulas run over the whole session by the `replay_formulas` callable the load worker passes (`recompute_formula_series` over the rows it read;
  the engine calls it, with the plan's evaluators, only when there is no record): every released build evaluates a program's formulas on every tick from the start.
  `scored_ticks` returns None when it can't be replayed: a formula the replay couldn't rebuild (formula series aren't stored per tick), a program that can't be read or has no tick.
  `rescore(ticks, overrides)` re-runs the live accrual (`GoalAccrual`) with each segment's ticks against its override, or with None against their own recorded targets;
  so as recorded it gives back the recorded numbers by construction (known-answer tests against the real `SessionManager`).
  The whole session's streak carries across a segment boundary, a segment's stays within it;
  `per_segment=False` skips the segments' own stats (a simple session's recompute: ~1 ms for 3 h on desktop).
  `line_steps(ticks, overrides)` is the graph's line: each moved segment's value from its start, an untouched one's recorded steps clipped to it.
  The panel starts as recorded and a moved control applies its threshold to every tick of its segment; recomputes are coalesced to one per frame (`Clock.create_trigger`).
  A program's segments are titled `<n> · <metric> · recorded <target>` (`DiaryScreen.set_what_if`: n from the segment's `index`, the name through `SERIES_NAMES`) and show their own `Above · Streak`;
  the totals under them are titled `Whole session` (attached for a program only).
  The load worker builds the ticks in their own guarded step after the graph data, so a row it can't score fails only the panel (`show_what_if_failed`), not the graphs;
  the panel's fill step runs last, so it can keep the metrics graph's recorded line (`threshold_steps`, a read accessor), which Reset puts back.
  A slider's range covers its segment's values and recorded targets (a formula can go below 0 or past 180); the graph draws a threshold outside its 0–scale range on its floor or ceiling, as it draws such values.
  A session it can't rescore gets a message in place of the controls ("This session can't be replayed."), as do the open ("Loading…") and a failed load;
  the line under the title ("Recorded at <targets> · nothing is saved", or for a program "Each segment starts at its recorded target · nothing is saved") goes with the controls.
  Reset, in the always-attached header, is enabled only while a control is moved;
  every message state clears the session from the panel (and its segment controls: a late value from one is ignored) and disables it, so Reset while the next session loads can't put the last one's line on its graph.
  The chevron right after the title (`_btn_collapse`, History's `theme.FoldChevron`) folds the body away, detached, with Reset left in the header:
  whichever of the controls or the message it shows comes back on unfold, and a session or message set while folded stays folded.
  It is saved per profile as the registry setting `what_if_collapsed` (`DiaryScreen.what_if` exposes the panel).

- **Only the shown tab's graph draws**:
  `_switch_graph_tab` enables drawing on the shown graph and pauses the others (`set_drawing_enabled`; enabling redraws), as the live screen's `_set_view` does for its hidden view
  — so a fit, a data load or a theme switch costs nothing on the hidden tabs.
  The three tabs are one zoom group (see [graphs](graphs.md)).

## Loading

- **The session detail opens at once** (#59):
  `_on_session_select` shows it in the tap's frame from the row History holds (`HistoryScreen.session_by_id`; `get_all_sessions` is `SELECT *`, and notes and renames update it in place):
  title, stats and notes, editable at once, with no full-screen spinner.
  Its band totals and graphs show a non-modal "Loading…" (`_band_placeholder`, `_graph_placeholder`; `DiaryScreen._ready` holds the sections whose data is in)
  while the worker `_load_session_detail` reads the band totals (one `SUM` query, sent first), then the metric rows **once**
  — the formula replay runs over the same rows (`_compute_session_formulas(sid, session, rows)` → `recompute_formula_series(..., rows)`)
  — and builds each graph's series, the raw-EEG tail and the markers off the main thread (`diary_screen.detail_graph_data`, pure).
  `_fill_detail(token, steps)` then puts one section in per frame (`Clock.schedule_once(…, 0)` from a callback runs next frame), the shown tab's graph first (`graph_fill_order`), through `DiaryScreen.fill_graph`.
  Every open takes a load token (`_detail_load`):
  a result for an earlier open, or for a detail no longer on screen (Back, another tab), is dropped, so opening B right after A shows only B.
  A failed load reports `session_detail_load_failed` and the sections say "Couldn't load this session's data."; the stats and notes keep working.
  `load_metrics_preview(rows)` is the same builder and fills, synchronously, as `_inject_session_formulas` is the formula replay's: both for tests.
  The metric-row read (`SELECT *` into dicts) is nearly all of the graphs' wait.
  DB reads off-thread are safe (`check_same_thread=False` + WAL).
- Diary raw-EEG `_synthesize_waveform` synthesizes only the **tail** the graph retains (`_RAW_MAX_SAMPLES = sample_rate*60`), starting the global sample index at the first kept tick so the tail is phase-identical to a full synthesis;
  it returns `(waveform, start_tick)` so raw markers map tail-relative.
  On a long session a full synthesis would compute ~99 % of its samples only to discard them.

## Band breakdown

- **Per-band power breakdown** (#8): the diary detail shows total power per frequency band over the whole session via `BandTotalsView` (`app/ui/widgets/band_totals.py`):
  a **sortable table** of band-colored share bars + Power and % columns, with a **Detailed (8 sub-bands) / Grouped (5)** toggle.
  Each row's name has its frequency range in a smaller muted line under it (`range_text`, from `app/eeg/band_spec.py`, the one table of band keys, names and ranges), so the 58 dp name column needs no widening.
  The `FoldChevron` right after its title (`_band_header`) folds it:
  `set_band_collapsed` detaches `_band_holder` (the table or its placeholder, which keeps updating while detached) and puts it back under the header;
  saved per profile as `band_power_collapsed` in the settings registry, like `what_if_collapsed`.
  Computed **on read**: `DatabaseManager.get_session_band_totals(session_id)` runs one `SELECT SUM(<band>_raw)` over the per-tick band powers already recorded, so nothing is stored for it and the live tick path is untouched.
  Grouping and sorting are pure view transforms: `grouped_totals(totals)` (alpha1+alpha2→alpha, etc.) and `band_rows(totals, mode, sort_by, descending)` build the ordered rows; `band_shares`/`format_power` are unit-tested too.
  Tapping a column header (`_HeaderCell`, a `ButtonBehavior` label) sorts (`band` = frequency order, `power`/`percent` = magnitude, largest first); tapping the active column reverses.
  The active column's sort arrow uses the **MDI `Icons` font via Kivy markup**: geometric ↑↓ render as tofu in this Roboto build, the same constraint as the `»` legend marker.
  View state (`mode`/`sort`/`desc`) persists per user as the JSON setting `band_breakdown_view`: the widget's `on_change` → `DiaryScreen.on_band_view_change` (a hook) → `AppManager._persist_band_view`;
  restored when the detail opens (`_on_session_select` → `set_band_view_state`), before the totals arrive from the detail's worker, its first step (`_load_session_detail` → `set_band_totals`).
  The live end-summary deliberately does **not** show it (fixed, full layout).
