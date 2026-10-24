# Metrics and scoring

The metrics engine, custom formulas, and how a session is scored: the scored metric (#51) and the threshold in force (#83).
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Metrics engine

- The update loop runs at 2 Hz (`AppConfig.UPDATE_FREQUENCY = 0.5s`); a graph holds up to `APP.GRAPH_POINTS_MAX` = 21600 points (3 h).
- **Metrics pipeline** (`app/metrics/engine.py`): from the band powers, smoothed by the rolling buffers of `app/eeg/buffer.py`, it computes the meditation score, shamatha score, distraction, sinking and subtle distraction.
  **Distraction and sinking are ported from the original Vernihor app** (`reference_distraction`/`reference_sinking`), not sigmoids:
  both are gated to 0 by alpha dominance and modulated by `(140 − S')`, where `S'` is shamatha *before* the final −20 offset and clamp (`MetricsEngine.last_s_prime`);
  distraction is the raw `100·(β1+β2)/α1` ratio, sinking is `(45 − a2p)/0.26` then gamma-damped.
  Their gates use `sqrt_pct_8band`, `round(sqrt(raw/P8)·100)`: an 8-band sqrt-relative percent (0–100), distinct from the 6-band sqrt-relative units (`compute_sqrt_relative_bands`) the shamatha formula uses.
  Subtle distraction uses sigmoid normalization of short-window variance.
  Each saved session is stamped with `MetricsEngine.ENGINE_VERSION` (`sessions.engine_version`: "2" = ported formulas, "" = pre-versioning sigmoid era) so stored values stay attributable;
  the diary reads the stored distraction/sinking rather than recomputing them, so old sessions render unchanged.
  Power-line noise detection is in `app/metrics/noise_detector.py`.
- **Custom formula engine** (`app/metrics/custom_formula.py`): AST-parsed user-defined expressions with whitelisted functions and `avg(expr, N)` windowed averages.

## Custom formulas

- Three custom-formula evaluators are keyed by `FORMULA_KEYS = ("custom_formula", "custom_formula_2", "custom_formula_3")`.
  `FormulaSlots` (`app/metrics/formula_slots.py`, the app's `_formulas`) holds them: `evaluators[i]`, the display names `names[i]` (default `"Custom 1/2/3"`), and `for_key(key)`, which maps a series key to its `CustomFormulaEvaluator`.
  Settings → Custom Formula edits them through `FormulaSettings` (`app/ui/formula_settings.py`, the app's `_formula_settings`):
  a slot's apply, the saved formulas' save/load/delete/export, and the profile's load (slots, graph names, Settings inputs) and persist.
  Whether a formula can run is one check, `custom_formula.compile_formula` (an evaluator, or None and why), shared by Save, a slot and a program's plan.
  Save refuses a formula that doesn't compile, since a program segment can pick any saved formula ([programs](programs.md#live-series)).
  A slot's Apply, a tap in Saved Formulas and Choose… leave the slot as it was when the formula doesn't compile: `on_slot_change` checks before it renames, and returns the error;
  `assign_saved`, the one path of a tap in Saved Formulas and of Choose…, shows it in a popup and clears the slot's status, since neither list is near it.
  Saved formulas and programs keep unique names through `settings_sections.common.save_under_unique_name`: a new name is added, an existing one is overwritten after a confirmation.
  Export writes the library to a private file and delivers it with `copy_to_documents` ([storage](storage.md#exports-to-shared-storage)): `Documents/EEGMeditation/` through MediaStore on Android, `~/Documents/EEGMeditation/` on desktop.
  A popup says where (`info`, the app's `_info_popup`), as the backup's does: slot 1's status line is far from the button and clipped at the larger text sizes.
  Each tick `evaluate_into` writes every valid slot into `metrics` through `custom_formula.evaluate_series`, the same function a running program's formulas use.
  Slot names reach the graph via `graph.set_series_name(key, name)`.
  Active names and expressions persist as `active_formulas` (JSON list of `{name, formula}`, per user), the audio-driving slot index as `audio_formula_index` (flat KV string, per user).
  At load `formula_slots.read_active` seeds slot 1 from the legacy `custom_formula` scalar if no JSON exists yet.
  When "Custom Formula" is the audio metric, `_audio_metric_key = FORMULA_KEYS[_audio_formula_index]`.
  `_audio_drive_key()` resolves the live drive key: the program's transient `ProgramRun.audio_key` while a program runs, else the user's baseline.
  It falls back to `shamatha_score` for an invalid (empty or unparsable) formula slot **or** a `PROGRAM_FORMULA_KEYS` value outside a program: both are absent from `metrics`, so they would read 0 → constant max noise.
  `_baseline_audio_metric(key)` keeps program slots out of the persisted/baseline `audio_metric`, sanitizing on both save and load (load also heals a leaked value).
  On the *live metrics* graph the series picker has a **Choose…** button on each custom-formula row, which opens the saved-formula library (`GraphSeries._choose_saved_formula(slot_idx, toggle_btn)`).
  The chosen entry goes to `FormulaSettings.assign_saved(slot_idx, entry)`, which sets the evaluator, the graph name and visibility (`on_slot_change`, persisted) and the Settings UI in one step;
  the picker's row then re-reads its name and state from the graph (`_show_row`, as every row does).
  All three formula series share one Y-axis (scale 200, reference at 100).
- Every checkpoint (`SessionRecorder.checkpoint`: the 60 s flush, leaving the app, a backup, the final save) records the active custom formulas so the diary can replay them:
  the row's `custom_formulas` comes from `_session_row_fields()` → `_session_custom_formulas_json()` (`FormulaSlots.session_record`), a JSON string of the valid slots (`slot`, `name`, `formula`, `visible`, `drove_audio`).
  `formula_slots.recorded_formulas` reads it back.
  `DatabaseManager.checkpoint_session(..., custom_formulas: str = "")` stores the **already-serialized string** (the contract; callers `json.dumps` at the site).
  Each slot's `visible` is `graph.is_visible(key)`, a pure dict read, safe on the tick thread.
  A formula's per-tick values are not stored: the diary recomputes them from these definitions and the stored bands (see [session-detail.md](session-detail.md)).

## Scoring

- `SessionManager.set_active_goal(metric_key, target=None)` accrues `time_above_threshold`/`longest_streak` (and `avg_score`) against that metric and target (`None` → the threshold in force);
  it scores at the formula's own scale, independent of `meditation_threshold`'s 0–100 clamp.
  **A session is scored on the metric that drives the feedback sound (#51).**
  In a simple session (decided by `ProgramRun.active`, fixed at session start, never the editable `ProgramSettings.mode` toggle) `_update_tick` calls `_score_on_drive_key()` → `set_active_goal(self._audio_drive_key())` every tick;
  it feeds the audio from that same resolved key, so scoring and sound can't diverge (an invalid formula's shamatha fallback moves both).
  The legend's `»` marks the scored series through the tick's single `_ui_update` dispatch:
  `_scored_mark(key)` leaves `_scored_key` untouched while the screen is locked, so the first tick after it marks the change; a program session's segments set the mark instead.
  The per-tick accrual is `app/session/scoring.GoalAccrual`, also behind `goal_stats(values, goal)`, the recompute from stored ticks.
  `recorded_score(session)` reads a stored row's `(key, name, avg)`.
  Rows from before #51 have an empty `score_metric_key`, so `recorded_score` returns `None`:
  nothing is deduced (their streak was measured on meditation, but the metric was never saved), and stored rows are never rewritten;
  the UI shows their average shamatha and Threshold Used (`app/ui/session_labels.py`).
  SessionManager reports no key and a NULL `avg_score` when no tick was scored (a session stopped within its first tick).
  **A running simple session's scored metric can't change**: `SessionManager` keeps one running sum, time above and streak, so a mid-session switch would mix two metrics' scales under the last one's name.
  While a simple session runs or connects, `_on_audio_metric_change`, `_on_audio_formula_index` (when a formula slot drives) and `FormulaSettings.on_slot_change` (a formula change to the slot the sound is set to; a name-only rename passes) refuse;
  they put Settings back (`_show_audio_metric`, `set_formula_slot`).
  The check is `_scoring_locked(doing)`: not `ProgramRun.active`, then the shared refusal; a program is scored on its segments' metrics, so the control stays free.
  The other slots and, in a simple session, the threshold stay editable.
  Every such refusal is `_refused_while_session_runs(doing, why="")`: "Session in progress" / "<why> Stop the current session before <doing>.";
  the others are the profile switch, a headset switch, both Restore checks, Settings › Audio's Test and a running program's threshold.
  Every checkpoint passes its stats through `_with_score`, which fills the key (the current drive key when none was scored) and adds `score_metric_name` (the live graph's `series_name(key)`, e.g. a formula's name).
  For a program it sets `"program"`, the name the program had when the session started (`ProgramRun.name`, `"Program"` if unsaved; Settings may load or save another during the session) and a NULL `avg_score`.
  `ProgramRun.tick` (called in `_update_tick`, program mode only) detects a boundary crossing with the pure `ProgramRun.transition` helper;
  `_enter_segment` then fires the prior segment's end cue (`AudioEngine.play_transition_cue()` chime, or warble), sets the **transient** `audio_key` to the segment's metric key (precomputed by `begin`);
  it also calls `set_active_goal` and moves the legend marker.
  `audio_key` must not overwrite the user's persisted `_audio_metric_key`: a program slot would leak into the baseline, and a later simple session would read that absent key as 0 → constant max noise.
  Every program custom line is evaluated every tick (persistent `formula_evs`, see [programs.md](programs.md)).
  Auto-stop reuses the timer-expiry path: the program total seeds the timer at session start.
- **The threshold in force** (#83):
  `SessionManager` scores a tick against `set_active_goal`'s target (a program segment), else `_threshold`, which `set_threshold(value)` and `start(threshold)` move.
  `start()` without one keeps it, which is how a session that waited for the headset starts with a threshold changed during the wait; `threshold_used` stays the Start value (the row's).
  `_put_threshold_in_force(value)` is the one place the Settings threshold takes effect, on the metrics engine, the sound, the SHAMATHA pill (`_shamatha_threshold`), `SessionManager.set_threshold` and the graph's scalar line together;
  it is the only writer of `_shamatha_threshold`.
  `_start_session_common` calls it directly, with a program's first target (a lingering tick thread from the last session must not block it).
  The slider's settle and the registry's profile load go through `_apply_threshold(value)`, which does nothing while `_program_owns_threshold()` (`_program_run.active and _session_pipeline_live()`);
  a running program's segments own its targets, and re-picking the active profile mid-program reloads its settings, which must not put the slider's value over a segment's target.
  During a running program the threshold controls are locked:
  `_start_session_common` calls `SettingsScreen.lock_threshold(_refuse_program_threshold)` after the start's setup (so a start that fails in it leaves the controls as they were), and every ending (`_undo_session_setup`) calls `lock_threshold(None)`.
  The rows are dimmed (opacity 0.5).
  A guard bound to the slider row's and the preset row's `on_touch_down` (bound handlers run before the widget's own and stop it by returning True) hands every touch on the slider, ±5 and the presets to `_refuse_program_threshold` while locked;
  it takes the touch only when that refused, mouse-wheel events included (Kivy's Slider steps its value on them).
  The refusal is `_refused_while_session_runs("changing the threshold", why=...)`, shown on every touch (a once-only message is missed after several ± clicks).
  It refuses only while the session pipeline is live, so between a program's end on the tick thread and its queued unlock the controls work rather than go dead.
  Nothing moves, so nothing is reverted or saved: a slider moved and put back on its settle would jump under a resting finger, and its value could be flushed in between.
  The slider applies the threshold through `_after_settle("apply_threshold", …)`, the per-name Clock trigger `_persist_user_setting_later` is built on (restarted on every change, 0.5 s `_PERSIST_SETTLE_S`);
  so a drag is one change at the value it settles on, not a target per slider step on every tick it spans.
  Start cancels a pending one (`_cancel_settle("apply_threshold")`), since the start reads the slider itself.
  A profile load that moves the slider schedules one too, which applies the same value again (harmless).
  With no session pipeline live, a slider change (`_on_threshold_change`, which Kivy calls only when the value changes, a profile switch to another stored threshold included) clears a finished session off the Session screen;
  `_clear_live_display` does it (graphs, mirrors, threshold steps and readout; also run at Start and on a change of profile), since the finished session's stepped line would otherwise outrank the new scalar line.
  Re-applying an unchanged Settings value clears nothing: after a program the threshold in force is a segment's target, so comparing against it would wipe the graphs on a mere profile reload.
  `add_metric` returns what the tick was scored on (`{score_key, score_value, score_target}`, `{}` when not RUNNING);
  it keeps the `(first tick, target)` steps with `scoring.extend_steps`, whose values are the stats' `score_targets` (JSON; `''` with no scored tick).
  `SessionRecorder.record` merges that into the tick's row; a tick the session paused or stopped under (`{}`) is not part of it: no row, mirror point or graph point, and a pending marker goes on the next recorded tick.
  Targets are kept per tick, not per session: a formula's values aren't stored otherwise, and a recompute (#50, `app/session/what_if.py`) needs what each tick was measured against.
