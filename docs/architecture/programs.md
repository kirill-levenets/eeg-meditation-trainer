# Session programs

Ordered timed segments: the model, how a program drives the live graph's series, and its Settings and session-screen controls.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Model and storage

- **Session Program** (`app/session/session_program.py`): headless model.
  `SessionProgram` holds an ordered list of segments (minutes, formula, target, end cue, feedback source);
  it exposes `total_seconds`, `segment_at(elapsed)`, `boundaries` and `threshold_steps(sample_rate)` (`(start_tick, target)` tuples in tick-index space, for the graph).
  Settings → Timer has a **Simple | Program** toggle;
  Program mode shows a segment editor (add/delete rows, formula picker with built-ins + saved custom formulas, target, end cue, feedback) and a saved-programs library (save by name, load by tap, delete).
- `ProgramSettings` (`app/ui/program_settings.py`, the app's `_program_settings`) holds what Settings → Timer edits: `mode` (`simple`/`program`), the editor's `segments` and its `name`.
  They persist per user as `timer_mode` and `session_program_name` (flat KV) and `session_program` (JSON), and are restored on profile load;
  the name shows in Settings through `set_program_name` and in the Session screen's duration picker.
- The `sessions.session_program` column stores the JSON segments of the program each session started with (`ProgramRun.segments_json`; empty when none ran).
  The saved-programs library uses `get/add/update/remove_saved_program` in `DatabaseManager` (a JSON list in the user-settings KV store under `user_{id}_saved_programs`).
  Program Save upserts by name, so re-saving an already-loaded program overwrites it; load reflects the name back so the next save goes to the same record.

## Live series

- **Program shows EXACTLY its metric set, the whole session.**
  The live graph catalog (`live_session.METRICS_COLORS`/`METRICS_SCALES`/`SERIES_NAMES`) carries `"meditation_score"` (colour `C.MED_SCORE`, scale 100, label `"Meditation"`), so a "Meditation" segment is plottable;
  it defaults to **hidden** (the first-run `_graph_toggles`, through `GraphSeries.restore`'s `key in sel`).
  It also carries **three** program-custom lines, `PROGRAM_FORMULA_KEYS = ("program_formula","program_formula_2","program_formula_3")` (colours `C.WARM`/`C.WARM2`/`C.WARM3`, scale 200), one per **distinct** custom formula in a program.
  `program_plan(prog)` (`app/session/session_program.py`, with `PROGRAM_FORMULA_KEYS`) returns `(program_keys, custom_slots, segment_keys)`:
  the set of series to show, the `(slot_key, custom_dict)` for each distinct custom (capped at 3), and the metric key each segment drives (a built-in key or its custom's slot).
  `runnable_plan(prog)` is that plan as a session runs it: a custom formula that doesn't compile (`program_evaluators` arms none for it) gets no line, and its segments drive, show and are scored on `shamatha_score`.
  A slot nothing computes is absent from `metrics` and would read 0 → constant max noise; Settings → Custom Formula's Save refuses such a formula, but one saved before it can still be in a program.
  The plan keeps `program_plan`'s keys as `planned_keys`: older builds scored such a formula on its own slot, and the what-if replay reads their sessions by them ([session-detail](session-detail.md)).
  `ProgramRun.begin` names the `unrunnable` formulas in a popup (`warn`, the app's `_info_popup`): it stays until read, as a meditator who pressed Start may not be looking.
  `ProgramRun` (`app/ui/program_run.py`, the app's `_program_run`) holds the running program: `active` from the start's `begin(prog, feedback_ids, name)` until `end()`.
  `begin` snapshots prior visibility, shows EXACTLY the runnable plan's keys (`show_program_series(graph, plan)` hides the rest), arms one persistent evaluator per custom that compiles into `formula_evs[slot]`, and stores each segment's metric key.
  Each program line is shown the **whole** program and evaluated every tick (`tick` runs `formula_evs` into `metrics[slot]` through `custom_formula.evaluate_series`, as the Settings formulas are).
  `_enter_segment` repoints audio, goal and marker to the segment's key (a built-in key or a program slot);
  `_segment_ui` only relabels and shows a custom segment's line and moves the `»` marker (a built-in segment touches no visibility).
  `end` restores the snapshot, resets all program-slot labels, and force-hides all `PROGRAM_FORMULA_KEYS`.
- `PROGRAM_FORMULA_KEYS` stay out of persistence, so they never leak into `graph_series_*`:
  `GraphSeries.persist` (which `_save_user_settings` runs through `persist_all`) filters them out, and `GraphSeries.restore`/`apply_saved` force-hide them.
  `GraphSeries.present_picker` lists one (as `Program: <name>`) on the live graph **only while the running program computes it** (`ProgramRun.computes`).
  Idle preview (`ProgramSettings.refresh_live_series`, run by `sync_picker`, not while a session runs): in program mode with a loaded program it shows the program's set via `show_program_series` before Start;
  otherwise `GraphSeries.apply_saved` restores the user's saved selection.
  A running program (`ProgramRun.active`) or `governs_live_series()` stops `persist` for the live graph, so a program's visible set never overwrites the saved manual selection:
  Settings → Timer can go back to simple during a program session while the graph still shows the program's set.
- Legend "training now" marker: `LegendBar.set_items(items, active_text=None)` bolds the matching item and prefixes it with `"» "` (geometric triangles render as tofu in this Kivy/Roboto build).
  `LiveSessionScreen.set_training_series(key)` passes the active key to the legend;
  `ProgramRun._segment_ui` sets it at each segment boundary crossing, and `_start_session_common` and `_undo_session_setup` clear it (`None`).

## Settings and pickers

- Settings Timer / Program swap: `_mode_content_box` holds either `_simple_box`, which has the Enable-Timer checkbox (a program forces the timer on), or `_program_box`; the other is detached from the tree.
  `_program_loaded_label` shows `"Loaded: <name>"` via `TimerSection.set_program_name(name)`.
  `_segments_box` holds the segment rows in insertion order, top to bottom.
- `ProgramSettings.sync_picker` syncs the Session screen's `_DurationPickerButton` label: a large `"P"` in program mode with a loaded program, else the duration.
  It re-syncs on entering the Session screen, on profile load and on each mode change, program load or duration pick.
  The duration popup's `"Programs…"` button (`"Program: <name>"` once one is loaded) lists the saved programs, the loaded one highlighted, and loads the one picked (`ProgramSettings.on_load`);
  `LiveSessionScreen.set_session_programs(programs, current_name)` gives it the list and the name.
- Per-segment **feedback source picker** (issue #10): each segment row has a "Feedback" column, a picker with Default / Rain / Tone / Custom file.
  "Default" inherits the global Settings → Audio selection.
  The source switches at each segment boundary via `set_active_feedback` (setVolume-only, tick-/lock-safe).
  See [audio.md](audio.md) for the engine architecture.
