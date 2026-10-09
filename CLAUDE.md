# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EEG Meditation Trainer — a Python/Kivy application for Shamatha meditation training using EEG neurofeedback from NeuroSky MindWave Mobile 2. Targets Android (via Buildozer), Linux, macOS and Windows (via PyInstaller) desktops.

## Commands

```bash
# Run application
python main.py

# Run with serial device (e.g. from mindwave-splitter)
python main.py --serial /tmp/mindwave_b

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_engine.py -v

# Run a single test
python -m pytest tests/test_engine.py::TestMetricsEngine::test_compute_metrics -v

# Build Linux executable
./build_linux.sh              # output: dist/EEG_Meditation_Trainer/

# Build Android APK
./build_android.sh            # debug build
./build_android.sh release    # release build

# Build Windows executable (run on Windows)
build_windows.bat

# CI: build a single platform via workflow dispatch
gh workflow run release.yml -f platform=windows   # or linux, macos, android, all
```

Dropping an Android `requirements` entry does not remove it from local builds: p4a keeps reusing the installed package and the dist. Clean both as [app-platform.md](docs/architecture/app-platform.md#build-and-ci) describes. CI builds start clean.

## Architecture

**Entry point:** `main.py` → instantiates `EEGMeditationApp` (Kivy app with ScreenManager).

**Data flow:** EEG stream → MetricsEngine → SessionManager → UI screens + Database

How each subsystem works and why lives in [`docs/architecture/`](docs/architecture/README.md), one file per subsystem. Read it before changing that subsystem.

### Module map

- `app/eeg/` — `neurosky_stream.py` (real headset: Bluetooth RFCOMM / pyserial, ThinkGear protocol), `mock_stream_v2.py` (active mock), `mock_stream.py` (legacy), `buffer.py` (rolling buffers). → [eeg-bluetooth](docs/architecture/eeg-bluetooth.md)
- `app/metrics/` — `engine.py` `MetricsEngine` (meditation, shamatha, distraction/sinking ported from the original Vernihor app, subtle distraction; `ENGINE_VERSION` stamped on sessions), `custom_formula.py` (AST-parsed user formulas, `avg(expr, N)`), `noise_detector.py`. → [metrics-scoring](docs/architecture/metrics-scoring.md)
- `app/session/` — `manager.py` `SessionManager` (Start/Pause/Resume/Stop, accrual), `scoring.py` `GoalAccrual`, `session_program.py` (timed segments), `timer_state.py`, `what_if.py` (threshold recompute). → [session](docs/architecture/session.md), [programs](docs/architecture/programs.md), [metrics-scoring](docs/architecture/metrics-scoring.md)
- `app/audio_feedback/noise.py` — `AudioEngine`: below and reward feedback channels, bell/chime/warble, timer gong; `MediaPlayer` on Android. → [audio](docs/architecture/audio.md)
- `app/storage/` — `database.py` (SQLite, migrations, write lock), `backup.py`, `fileops.py`, `android_saf.py`, `android_share.py`, `csv_export.py`. `app/settings/registry.py` — per-user scalar settings. → [storage](docs/architecture/storage.md)
- `app/ui/app_manager.py` — `EEGMeditationApp`: wiring, session start/stop, BT wait, user gate, settings load/save.
- `app/ui/theme.py`, `app/ui/widgets/` — palette `C`/`F`/`S`, themed widgets, modals, legends, overlays. → [ui-theme](docs/architecture/ui-theme.md)
- `app/ui/raw_eeg_screen.py` — `ScrollableGraphWidget`, the one time-series graph class; `touch_utils.py`, `render_stats.py`. → [graphs](docs/architecture/graphs.md)
- `app/ui/live_session.py`, `settings_screen.py`, `wizard_screen.py` → [live-session-and-settings](docs/architecture/live-session-and-settings.md); `history_screen.py`, `period_totals.py` → [history](docs/architecture/history.md); `diary_screen.py` (session detail) → [session-detail](docs/architecture/session-detail.md); `session_labels.py` → [session](docs/architecture/session.md)
- `app/crash_handler.py`, `app/logger.py`, `app/android_jni.py` → [app-platform](docs/architecture/app-platform.md)
- `service/session_keep_alive.py` — Android foreground service for locked-screen sessions. `tools/` — BT diagnostics (`bt_test.py`, `ble_battery_scan.py`).

**Configuration:** All tunable parameters (sigmoid curves, thresholds, update frequency, audio settings) are in `app/config.py` as dataclass-style config objects (`SIGMOID`, `METRICS`, `APP`). The tick runs at 2 Hz (`UPDATE_FREQUENCY = 0.5`); a graph holds up to `GRAPH_POINTS_MAX` points (3 h).

## Invariants

Each rule exists because breaking it caused a real defect. The linked file explains the mechanism.

### Threads and concurrency

- **At most one Bluetooth reader thread.** The MindWave serves one RFCOMM channel and a connected socket nobody drains stalls it until the headset is power-cycled. `NeuroSkyStream.start()` returns a bool and refuses while a previous reader is alive; `stop()` closes the socket before joining. → [eeg-bluetooth](docs/architecture/eeg-bluetooth.md)
- **A session start is one attempt** (`_start_attempt`): a callback queued for an earlier attempt does nothing. Every BT-wait exit goes through `_abort_bt_wait()` (tick watcher stopped before the stream); every ending undoes the start's setup through `_undo_session_setup()`. → [eeg-bluetooth](docs/architecture/eeg-bluetooth.md)
- **At most one tick thread.** `_start_tick_thread` is a no-op while one is alive; each thread gets its own stop event. → [session](docs/architecture/session.md)
- **No Kivy from the tick thread**: UI goes through `_on_main`. **No `AudioEngine.stop()`, `MediaPlayer.release()`/`stop()` on the tick thread**: they deadlock against the main Looper paused during screen lock. On the tick thread, silence with `AudioEngine.mute()` (setVolume only) and defer teardown to the main thread; on timer expiry, persist first and ring the gong last. → [audio](docs/architecture/audio.md)
- **Every runtime DB write goes through `DatabaseManager._write()`** (one transaction under `_write_lock`): the connection is shared with the tick thread (`check_same_thread=False`). The connection is the `_conn` property; after `mark_shutting_down()` it is a null connection that swallows writes, so late access is a no-op, never a crash or a reopen. → [storage](docs/architecture/storage.md)
- Long work runs off the main thread (DB reads are safe there: WAL + shared connection); the loading overlay animates via `Clock` and can't paint otherwise.

### Sessions

- **A session reaches the DB only through `_checkpoint_session`**: the row and the buffered ticks in one transaction, at the 60 s flush, on leaving the app, at backup and at the final save. → [session](docs/architecture/session.md#persistence)
- **Every ending saves through one path**: `_stop_and_save` → `_persist_session_data` (tick-thread-safe, no Kivy) + `_finalize_stop_ui` (main thread). There is no discard path; a confirm that arrives after the session ended writes nothing. → [session](docs/architecture/session.md#persistence)
- While a session runs or connects (`_session_pipeline_live()`), anything that would break it is refused through `_refused_while_session_runs(doing)`: profile switch, Restore, the scored metric (`_scoring_locked`), a running program's threshold. → [metrics-scoring](docs/architecture/metrics-scoring.md#scoring)
- **A session is scored on the metric that drives the feedback sound** (`_audio_drive_key()`). The Settings threshold takes effect only through `_put_threshold_in_force` (the slider and profile load go through `_apply_threshold`). → [metrics-scoring](docs/architecture/metrics-scoring.md#scoring)
- `_program_audio_key` is transient and never written to `_audio_metric_key`; `PROGRAM_FORMULA_KEYS` are never persisted to `graph_series_*` or the baseline audio metric. A leaked program key reads as 0 → constant max noise. → [programs](docs/architecture/programs.md)

### Audio

- Pause/Resume use `AudioEngine.pause()`/`resume()`, never `stop()`/`start()`: `stop()` tears down the prepared player set and Resume came back silent. `set_reward` must be called after `prepare_feedback`. → [audio](docs/architecture/audio.md)

### Kivy UI

- **Never hide interactive content with `height=0`/`opacity=0`/`disabled=True`**: a disabled widget consumes taps on whatever it overlaps. Detach it (`RevealBox`, or `clear_widgets()`/`add_widget()`). Enforced by `tests/test_touch_regression.py`. → [ui-theme](docs/architecture/ui-theme.md)
- A disabled `Label` draws `disabled_color`, not `color` — set both.
- **Colours carry their theme role.** Read them from `C.X` (a `list()` copy freezes the colour); canvas code uses `ThemedColor` / `C.resolve()` and registers palette-dependent redraws with `C.add_listener`. Labels, text inputs, popups and file choosers come from `theme.py` (`ThemedLabel`, `ThemedTextInput`, `ThemedPopup`, `ThemedFileChooser`); `tests/test_theme_switch.py` and `tests/test_modal_style.py` fail on direct Kivy imports. → [ui-theme](docs/architecture/ui-theme.md#navigation-and-theme)
- Decorative strokes (press ring, graph glyphs, borders) contrast with the surface they are drawn on (`C.TEXT`), not the element's fill; text on a fill uses `readable_fg(fill)`. Check all four themes.
- Roboto in this build has no arrows or geometric triangles (`→`, `↑↓`, `▶` render as tofu): use `›`, `»`, or MDI `Icons` font markup.
- A ScrollView whose content changes while the user may be scrolling needs `_StableScrollView`'s bounds override; scroll programmatically with `effect_y.reset(...)`, never by assigning `scroll_y`. → [history](docs/architecture/history.md#session-list)
- Graph touch hit-tests are in window coordinates (`to_window`); `GraphAwareScrollView` delivers touches in the graph's parent frame. A Kivy `Mesh` is capped at 65535 indices — split at `_MESH_MAX_QUADS`. `size_hint`/`size` are live `ReferenceListProperty`s — `list()` copy before overriding. → [graphs](docs/architecture/graphs.md)

### Android and platform

- **Every app file copy goes through `fileops.copy_file_atomic`**, never `shutil.copy2`: copying the SELinux label raises EACCES on the phone's Python 3.11 after the bytes are written. → [storage](docs/architecture/storage.md#backup-and-restore)
- SQLite never opens a file on `/sdcard` or a `content://` URI: back up into an internal temp file (`online_backup_to_tempfile`) and stream it through the Storage Access Framework. → [storage](docs/architecture/storage.md#backup-and-restore)
- A Python `str` passed to an overloaded Java method crosses pyjnius as `android_jni.java_string(text)`. → [app-platform](docs/architecture/app-platform.md#android-back-button)
- `on_pause()` always returns `True` (returning `False` stops the app).
- Never `except (PermissionError, OSError): pass`: surface it through `report_soft_error` (or `crash_handler.queue_pre_app_error` before the app exists).

### Users and settings

- **The app is never usable without an active user**: `build()` gates on `resolve_startup_user(db)`; per-user handlers use `_require_user(action)`; every profile pick goes through `_activate_user(uid)`. A silent user-gate return or an ignored bool DB write fails `tests/test_silent_failure_guardrail.py` unless marked `# silent-ok: <reason>`. → [app-platform](docs/architecture/app-platform.md#user-gate-and-profiles)
- Scalar per-user settings are `Setting` descriptors in `app/settings/registry.py`; `SettingsStore.load` always applies a value (stored or default), so no profile inherits another's. Add a new scalar setting as a descriptor, not a hand-written save/load. → [storage](docs/architecture/storage.md#per-user-settings)

### Shared paths — reuse, don't add a second

Session delete `_delete_sessions(ids)` · notes `_save_session_notes` · confirm `theme.confirm_popup` (via `_confirm_action`) · message `make_message_popup` / `_info_popup` · list picker `make_scroll_popup` · Cancel/Close `cancel_button()` · toast `_toast` · modal surface `paint_panel` · screen background `fill_background` · fold button `theme.FoldChevron` · debounced change `_after_settle` · session titles and stats lines `app/ui/session_labels.py` · scoring `scoring.GoalAccrual` · graph glyphs `_wire_graph_affordances` · legends `LegendBar` · file copy `copy_file_atomic` · temp removal `discard_file`.

## Documentation Rules

**All documentation files must stay in sync with code changes.** When modifying features, UI, commands, architecture, or build process, update the relevant docs in the same commit or PR:

- `CLAUDE.md` — Commands, module map, invariants, shared paths. Loaded into every Claude Code session together with `~/.claude/CLAUDE.md` (150k-character combined cap), so keep it under ~30k characters: a new rule gets one line here and its explanation in the subsystem's architecture file.
- `docs/architecture/*.md` — How each subsystem works and why ([index](docs/architecture/README.md)). Update the subsystem's file when its design changes. Describe the current design; what it used to do and dated measurements belong in the commit message or `CHANGELOG.md`, unless they explain a constraint that still holds.
- `readme.md` — English README: features, project structure, build instructions, setup. Update when adding user-visible features or changing platforms/dependencies.
- `readme_ua.md` — Ukrainian README: mirror all `readme.md` changes in Ukrainian.
- `docs/USER_MANUAL.md` — English user manual. Update when UI flow, screens, or settings change.
- `docs/USER_MANUAL_UA.md` — Ukrainian user manual: mirror English manual changes.
- `app/assets/help/help_en.txt` — In-app help content (English). Update when features, connection flow, or settings change.
- `app/assets/help/help_ua.txt` — In-app help content (Ukrainian): mirror English help changes.
- `CHANGELOG.md` — Release history in Keep a Changelog format. Add entries under `[Unreleased]` as you commit; promote to a new version section when tagging.
- `IMPROVEMENTS.md` — Roadmap. Mark items as completed when implemented; add new ideas as they emerge.
- `pyproject.toml` — Ruff config. Run `ruff check app/ tests/ main.py` before every commit; all checks must pass.
