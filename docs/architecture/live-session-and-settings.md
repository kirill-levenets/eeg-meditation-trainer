# Session screen, Settings, first run

The live Session screen, the Settings screen and the first run.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Session screen

- **Session screen** (`live_session.py`): Metrics/Raw EEG toggle (inline, no separate screen), connection overlay with status + countdown, and the session-end summary card with quick notes.
  `show_summary(sid, stats, title=)` fills the card: Duration, the `session_score_rows` rows, Time Above Threshold and Longest Streak, 22 dp lines with no gap (`_set_summary_rows` attaches as many pooled rows as the session has).
  `_layout_summary` arranges it by the card's width, re-run on every width change, so a phone turned with the card open re-flows it with the typed notes kept:
  from 520 dp inside the card (a landscape phone, ~670) two columns, the stats left and the notes field over **Save notes** right (the field takes the stats' height less Save notes, a few lines);
  else one column, the stats over the notes field, two lines of its text tall (`_notes_h`, `F.box(44)`: Save notes' height at the normal text size), with Save notes beside it;
  Delete and OK under both.
  The title follows the arrangement by the same rule, `_summary_in_two_columns`, applied to its own width, which spans the card's inside (`_fit_summary_title`, so it can't depend on which of the two width changes Kivy dispatches first):
  `Session saved · <session_title>` on one line over two columns, the name on a line of its own under `Session saved` over one, either cut with an ellipsis to its line (`_cut_to_width`), never wrapped further.
  Bottom-bar action buttons (Start/Pause/Stop/Mark) put the icon over the text (`StyledButton(vertical=True)`).
  Adaptive landscape layout: `_compute_graph_height_adaptive` uses a fixed graph height when the viewport is tall, or switches to scroll mode when the graph would fall below `dp(400)`.
  The bottom bar lives inside the body ScrollView.
- **The Session screen shows one profile's session.**
  `_live_display_uid` is the profile whose session the screen shows (graphs, readout, end card): set at Start, cleared by `_abort_bt_wait` when the start never became a session (the Start already emptied the display).
  `_drop_shown_session` takes it off the screen:
  the end card, if open, closes through `_close_summary` (notes saved unless the session is gone, bell stopped; the one way every card closes, OK included);
  then `_clear_live_display` empties the graphs, their mirrors and the readout (`LiveSessionScreen.clear_readout`: what a fresh screen shows).
  It runs when another profile is picked (`_activate_user`), when that profile is deleted, and when History deletes the shown session (`_recorder.session_id`, kept after the stop).
  Re-picking the shown profile resets nothing (`_on_user_switch` allows that mid-session, and a reset there would wipe the running session's graph).
  An idle threshold change (#83) clears the display but keeps the owner, so a later switch still closes an open card.
  The stats bar shows the `LiveScore` each tick hands it (`update_stats`), refreshed once more at the session's end and on resume (ticks are skipped while locked), and `set_stats_mode` redraws it when a profile's LIVE/AVG choice loads.
- Stats bar (#113): three slots on the metric the session is scored on, the end card's numbers as they build up.
  LIVE: the scored value, the Target it is scored against (the threshold, or a program segment's target) and the current Streak; AVG: the Average, the time On target and the Best streak.
  The AVG titles are History's period-totals words, which fit a third of a 360 dp phone at the largest size where the end card's "Time Above Threshold" and "Longest Streak" don't.
  The first LIVE title is the name on the graph of the series the legend marks `»` (`set_training_series`, which redraws the bar); it stays after the session ends (`_score_name_key`) until `clear_readout`, and reads "Score" before any.
  A program's segments are scored on different metrics, so its AVG average is the running segment's ("Segment avg"); the time above and the streaks are the whole session's, as on the end card.
  The bar reads `SessionManager.live_score()`, running totals, not `compute_statistics`, which walks every tick and runs only at a checkpoint or the save.
  LIVE / AVG is a `ChoiceToggle` (both positions shown, the chosen one filled); the choice persists per profile as the `stats_view_mode` setting.
  Values are `F.capped(F.H2)` so "59m 59s" keeps to its third; only the first title, a metric's name, is cut with an ellipsis.
  `test_the_stats_bars_titles_and_values_keep_to_their_thirds` checks every other title and every value at the largest size, at 1 and at 2.75 px per dp.
- **Shamatha-reached status emphasis** (issue #13): while the live `shamatha_score` holds at/above the session threshold the header status label becomes a bold `SHAMATHA` on a green `C.SHAMATHA` rounded pill;
  otherwise it shows the classified state.
  The pill is a `Color`+`RoundedRectangle` in `_state_label.canvas.before` sized to the text (`_position_shamatha_chip`, bound to the label's `texture_size`).
  `set_shamatha(active)` toggles its alpha and the text/`readable_fg(C.SHAMATHA)` colour; `update_state` records `_last_state` but skips restyling while the chip is active, so the tick stream can't overwrite it.
  Crossing is detected by the pure `AppManager._shamatha_transition(active, above, streak, enter_ticks=3, exit_ticks=3)` on the tick thread (debounced: 3 ticks / 1.5 s each way against 2 Hz noise);
  only the *change* is dispatched to `set_shamatha`.
  Gated on the threshold in force, not per-segment program targets: a program's start puts its first segment's target in force (`_put_threshold_in_force`), and that gates the pill for the whole run.
  Reset at session start/stop and re-synced on Android resume.
  The pill's `Color` stays a plain instruction (its alpha is the on/off toggle; a `ThemedColor` would reset it on a switch): `C.SHAMATHA` is the same in every palette, so it needs no repaint.

## Settings screen

- **Settings screen** (`settings_screen.py`): `ThemedAccordion` sections:
  User Profile, **Timer / Program**, Device, Data Backup, Threshold (max 180), Audio, Display, Custom Formula, Theme, Developer Tools (crash triggers), Help & Troubleshooting (`help_language()`: Android's locale, or on desktop `LANGUAGE`'s list and then `LC_ALL`/`LC_MESSAGES`/`LANG`; the first language with a help file, else English; Windows and macOS builds usually set none of these).
  The larger sections are their own classes in `settings_sections/`, built into their accordion section and reached as attributes of the screen:
  `settings_screen.formulas` is `FormulaSection`, `.timer` is `TimerSection`, `.device` is `DeviceSection`, `.audio` is `AudioSection`, `.display` is `DisplaySection`;
  what more than one section builds with is in `settings_sections/common.py`.
  User Profile uses the shared `UserPickerForm`; Data Backup has Backup/Restore buttons.
  Graph series are picked on the graph (the series picker); `_graph_toggles` is only the first-run default set.
  Custom Formula has **three named slots** (Formula 1/2/3, named Custom 1–3 by default), each with name input, expression input, Apply, Save, and per-slot status.
  In Threshold, a `[1][2][3]` button group below the "Custom Formula" audio-metric radio selects which slot drives the audio (the `on_audio_formula_index` hook → `_on_audio_formula_index` in `app_manager`).
  **Timer / Program** has a **Simple | Program** toggle: Simple = single duration + Enable-Timer checkbox;
  Program = the segment editor (`TimerSection`, `settings_sections/timer.py`: `_segments_box`, rows with duration, formula, target, end-cue picker (Chime/Warble), feedback-source picker);
  with it the loaded-program label (`_program_loaded_label`) and the saved-programs library (save/load/delete named programs).
  The toggle swaps `_simple_box` or `_program_box` into `_mode_content_box` via `clear_widgets()`/`add_widget()`: a zero-height disabled container still lets children overflow and swallow taps, so the inactive box must be fully detached.
- **Locked-screen sessions** (Settings → Device, Android):
  whether battery optimisation applies to the app and the buttons that open the phone's settings, from `PowerExemption.refresh` ([app-platform](app-platform.md#background-running-android)).
  `DeviceSection.show_power_state` attaches the row, so off Android it never shows; a row with nothing to open has no button row.
- **Device list** (Settings → Device): one row per paired device, `device_row_text(alias or Bluetooth name, address)` (`app/ui/device_labels.py`): every MindWave advertises the same name, so the address tells rows apart.
  - **Marks:** the selected headset's row has the accent fill and the connected one the Bluetooth glyph (`DeviceSection.mark_bt_devices`); in mock mode no headset is in use, so none is marked.
    The screen reads them from `Headset.state()` (`app/ui/headset.py`, the app's `_headset`) whenever it shows device status:
    a list populate, `update_device_status`, and `on_pre_enter`, since the link can drop between sessions with nothing on screen.
    Every row is built with the glyph so its slot exists (`StyledButton` makes an icon label only at construction) and `set_icon("")` blanks it.
  - **Names:** the pencil opens the inline editor History's rename uses (`theme.RenameRow`, stopping at `MAX_DEVICE_ALIAS` while typing) under the row;
    Save or Enter calls `Headset.on_rename(address, bluetooth_name, text)`, which stores the alias and relabels the row (`relabel_bt_device`);
    for the headset in use it also relabels the status line and the Session screen's label (`Headset.show_selected`, which a pick in the list goes through too).
    Aliases are app-wide, not per profile: `bt_device_aliases`, a JSON `{address: alias}` in `app_settings` (`get_json_setting`), because a headset is the same object whichever profile uses it;
    the selected headset stays per profile (`bt_device_address`).
    Blank, or the Bluetooth name itself, drops an alias, and one is cut to `MAX_DEVICE_ALIAS` (24) characters to keep its row on one line.
  - Everything that names the selected headset (status line, the Session screen's label, the connect overlays, session names) goes through `Headset.name()`.
    A session's name is taken at its first checkpoint, so a later alias doesn't rename it.

## First run

- **First run is the user gate's popup** (`_show_first_run_popup`, see [app-platform](app-platform.md#user-gate-and-profiles)): a `UserPickerForm` to create a profile or pick an existing one (e.g. after a restore) without retyping the name.
  It is a Popup, not a Screen, because a TextInput inside a Screen doesn't get keyboard focus on some Android devices.
  A new profile (`_complete_first_run`) starts on the mock; a picked one (`_on_pick_existing_user`) keeps its own headset and mode;
  both leave through `_finish_first_run`, and `Headset.auto_scan`, which scans only while the stream has no headset set, selects a single paired MindWave or opens Settings → Device to pick among several.
