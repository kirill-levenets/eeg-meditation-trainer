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

## Architecture

**Entry point:** `main.py` → instantiates `EEGMeditationApp` (Kivy app with ScreenManager).

**Data flow:** EEG stream → MetricsEngine → SessionManager → UI screens + Database

### Core modules

- **EEG sources** (`app/eeg/`): `mock_stream_v2.py` (active mock with frequency-based synthesis, NeuroSky-compatible format), `mock_stream.py` (legacy mock), and `neurosky_stream.py` (real Bluetooth RFCOMM / pyserial, ThinkGear protocol). Both active sources produce 8 band powers + raw 512Hz waveform + eSense attention/meditation. Desktop BT falls back to PyBluez if `socket.AF_BLUETOOTH` is missing (common in PyInstaller bundles). Real stream tracks `_last_packet_time` for stale data detection and parses battery level (code 0x01, though TGAM hardware doesn't send it). BT connection kept alive between sessions to avoid RFCOMM/EBUSY issues; `reset_sample_state()` clears cached values for new sessions.
- **Metrics pipeline** (`app/metrics/engine.py`): Consumes raw band powers, computes meditation score, shamatha score, distraction, sinking, subtle distraction via sigmoid normalization. Uses rolling buffers from `app/eeg/buffer.py`. Power-line noise detection in `app/metrics/noise_detector.py`.
- **Custom formula engine** (`app/metrics/custom_formula.py`): AST-parsed user-defined expressions with whitelisted functions and `avg(expr, N)` windowed averages.
- **Session lifecycle** (`app/session/manager.py`): Start/Pause/Resume/Stop state machine. Coordinates EEG stream, metrics engine, audio feedback, and database flush. Tracks `time_shamatha_90` (time shamatha score >= 90, independent of user threshold).
- **Audio feedback** (`app/audio_feedback/noise.py`): 4-channel engine — white noise (log-scaled volume, MAX_VOLUME=0.3), tingsha bell (sinking), chime (subtle distraction), warble (disconnect alert). Uses Kivy SoundLoader with crossfaded WAV generation. On Android, the noise channel and the **timer-end gong** use `MediaPlayer` (with `USAGE_MEDIA` audio attributes) instead of SDL_mixer so they keep playing through screen lock; SoundLoader/SDL is silenced while locked. The other one-shot channels (sinking bell, chime, warble) still use Kivy's `SoundLoader`. `AudioEngine.mute()` is a non-blocking volume→0 (setVolume only) safe to call from the tick thread during lock.
- **Storage** (`app/storage/database.py`): SQLite with automatic schema migration. Stores sessions (with `session_name`, `time_shamatha_90` columns), per-tick metrics timeseries, user profiles, per-user settings. CSV export support. `create_user` raises `UserExistsError` on duplicate name; `find_user_by_name` looks up by exact (case-sensitive) name. Per-user settings are a flat KV store (`set_user_setting`/`get_user_setting`, key = `user_{id}_{key}`); `set_user_json_setting`/`get_user_json_setting` wrap a value as JSON in one key (the pattern used by `saved_formulas`, and by per-graph series / active-formula lists).
- **DB backup/restore** (`app/storage/backup.py`): `make_backup` (SQLite online `Connection.backup()` API), `validate_backup` (checks for required tables), `restore_backup` (validates then `shutil.copy2`). Used by Settings → Data Backup section.

### UI layer (`app/ui/`)

**Navigation:** 3-tab bottom bar (Session / History / Settings) via `BottomNav` in `theme.py`. First-run wizard shown when no users exist.

- **Theme system** (`theme.py`): Centralized `C` color accessor (4 palettes: Dark Blue, Dark Green, Light Cream, Light Green), `F` font sizes, `S` spacing. `format_duration(seconds)` — smart time display (seconds if <1m, minutes if <1h, hours otherwise). Custom widgets: `StyledButton` (rounded, press feedback, MDI icons, outline mode; `vertical=True` for 2-row icon-top/text-bottom layout), `Card`, `Divider`, `ThemedAccordion`, `PresetRow`, `BottomNav`. Theme changes notify listeners for live refresh.
- **Icons** (`app/assets/fonts/materialdesignicons-webfont.ttf`): Material Design Icons font, registered as `'Icons'`. `ICONS_AVAILABLE` flag for graceful fallback if font missing.
- **App icons** (`app/assets/icons/`): Generated EEG brainwave icon (512/192/128/48 PNG + ICO + ICNS), presplash for Android.
- **Session screen** (`live_session.py`): Metrics/Raw EEG toggle (inline, no separate screen), connection overlay with status + countdown, session end summary card with quick notes. Bottom-bar action buttons (Start/Pause/Stop/Mark) use a 2-row vertical layout (icon on top, text on bottom) via `StyledButton(vertical=True)`. Adaptive landscape layout: `_compute_graph_height_adaptive` uses a fixed graph height when viewport is tall, or switches to scroll mode when the graph would fall below `dp(400)`. Bottom bar lives inside the body ScrollView.
- **History screen** (`history_screen.py`): Calendar/14-Day segmented toggle at top — `CalendarHeatmap` (GitHub-style, by avg shamatha) or `Last14DaysBars` (per-day bar chart). Both share `set_data(day_values)` + `set_day_tap_callback` so tap-to-filter works in both modes. Selected mode persisted as per-user setting `history_view_mode`. Day filter, session list with inline rename/delete unchanged.
- **Settings screen** (`settings_screen.py`): `ThemedAccordion` sections — User Profile, Timer, Device, Data Backup, Threshold (max 180), Audio, Display, Custom Formula, Theme selector. User Profile section uses the shared `UserPickerForm`; Data Backup has Backup/Restore buttons. (Graph series selection moved to the on-graph picker; `_graph_toggles` remains only as the first-run default set.)
- **Shared widgets** (`widgets/`): `UserPickerForm` (used by wizard step 1, first-run popup, and Settings → User Profile) — existing-profiles list + name input + duplicate-name "Use existing 'X'" / "Change name" inline UI. `LoadingOverlay` (`widgets/loading_overlay.py`) — app-global dimmed modal spinner (status + animated dots, theme-aware) mounted by wrapping the app root in a `FloatLayout`; shown via `EEGMeditationApp.show_loading(text)`/`hide_loading()`. Because it animates via `Clock`, the caller must move the long work off the main thread or the overlay can't paint.
- **Wizard** (`wizard_screen.py`): 2-step first-run (name → device scan/skip). Step 1 uses `UserPickerForm` so the user can pick an existing profile (e.g. after reinstall) without retyping the name. Hidden bottom nav during wizard. On Android, the form's TextInput hijacks focus to a Popup TextInput because Kivy TextInput doesn't get keyboard focus inside a Screen on some Android devices.
- **Diary detail** (`diary_screen.py`): Session stats, notes/tags/mood, graph tabs (metrics/raw/freq). Navigated from History, with back button.

**Configuration:** All tunable parameters (sigmoid curves, thresholds, update frequency, audio settings) are in `app/config.py` as dataclass-style config objects (`SIGMOID`, `METRICS`, `APP`).

### Diagnostic tools (`tools/`)

- `bt_test.py` — Minimal raw RFCOMM + ThinkGear parser for connection debugging. No Kivy, no threads. Usage: `python tools/bt_test.py [MAC]`
- `ble_battery_scan.py` — BLE GATT service enumerator (requires `bleak`). MindWave Mobile 2 doesn't expose BLE on Linux/Android (iOS only).

## Key Design Decisions

- Update loop runs at 2Hz (`AppConfig.UPDATE_FREQUENCY = 0.5s`), graph holds 600 points (5 min).
- Band powers are sqrt-normalized to relative units before metric formulas.
- NeuroSky Bluetooth uses pyjnius on Android, Python socket BTPROTO_RFCOMM on Linux (with PyBluez fallback), pyserial over virtual COM port on Windows. BT connection is kept alive between sessions (not closed on session stop) to avoid RFCOMM EBUSY and ThinkGear reinit failures. On app exit, the socket is NOT explicitly closed — the kernel handles cleanup while BlueZ may keep the ACL link for faster next-launch reconnect. Connection timeout is 30s, signal wait is 8s. Stale data (no new packets for 10s) auto-stops the session.
- Android DB path always uses `app_storage_path()` (not `/sdcard`) for stable path across launches. Old DB auto-migrated on first run. `KIVY_KEYBOARD_MODE=systemanddock` + `softinput_mode=below_target` set for Android TextInput stability.
- Desktop DB path resolves to platform user-data folder: Linux `${XDG_DATA_HOME:-~/.local/share}/EEGMeditation/`, Windows `%APPDATA%\EEGMeditation\`, macOS `~/Library/Application Support/EEGMeditation/`. One-time migration copies any pre-existing DB from next-to-binary or project root; the old file is left in place for manual rollback.
- DB migrations (Android `/sdcard → app_storage_path` and desktop legacy → user-folder) surface failures via `crash_handler.queue_pre_app_error(label, detail)`, replayed by `EEGMeditationApp.on_start()` through `report_soft_error`. **Project policy:** never `except (PermissionError, OSError): pass` — surface a diagnostic instead.
- `DatabaseManager.create_user` raises `UserExistsError(user_id, name)` on duplicate. Wizard, first-run popup, and Settings → User Profile use the shared `UserPickerForm` widget (`app/ui/widgets/user_picker.py`); the form's "Use existing 'X'" button branch goes through `_on_pick_existing_user(user_id, source)` in `app_manager`. For `source="wizard"`, if the picked user has a saved `bt_device_address` per-user setting, step 2 (device picker) is skipped and the wizard completes with that device.
- Backup/Restore lives in `app/storage/backup.py`. Backup uses SQLite's online `Connection.backup()` API (transaction-safe). Restore validates the file (must contain `users` and `sessions` tables), closes the live DB, copies the file over `APP.DB_PATH`, then force-restarts the app via a "Please relaunch" popup → `App.stop()` (in-memory caches reference the old DB, simpler to restart). Android writes backups to `/sdcard/Documents/EEGMeditation/` (relies on the existing `MANAGE_EXTERNAL_STORAGE` permission); desktop uses Kivy `FileChooserPopup`.
- `history_view_mode` per-user setting (`"calendar"` | `"bars"`, default `"calendar"`) selects the History layout via `HistoryScreen.set_view_mode(mode)`. Both `CalendarHeatmap` and `Last14DaysBars` consume the same `day_avg` dict and share the tap-to-filter callback.
- Removed dead code in this iteration: `app/ui/analytics_screen.py`, `app/ui/home_screen.py`, `app/analytics/aggregator.py` — all unreachable from the bottom nav (only Session/History/Settings).
- Database opens with `check_same_thread=False` so the daemon tick thread can safely write metric batches.
- `conftest.py` only sets `sys.path` — no shared fixtures.
- Volume curve uses log scaling (`k=9`): rises fast initially, flattens near max (0.3). Prevents harsh noise at low scores.
- Theme colors accessed via `C.PRIMARY` etc. — `C` is a `_ColorAccessor` instance that reads from a mutable dict. `C.set_theme(name)` swaps palette and notifies listeners.
- Settings saved in `on_pause()` (Android) and `on_stop()` (desktop) so they persist when OS kills backgrounded app. `on_pause()` always returns `True` — per Kivy docs, returning `False` stops the app rather than "refusing to pause" (counter-intuitive but documented).
- Session tick runs in a Python daemon thread (`SessionTick`) instead of Kivy `Clock` so EEG compute, audio volume updates, and DB flushes continue while the Android screen is locked. UI updates are dispatched via `_on_main` (`Clock.schedule_once`); they queue during pause and drain on resume.
- Session names auto-generated as `"HH:MM - DeviceName"` to distinguish mock vs real.
- Windows CI build sets `KIVY_DOC=1` in the PyInstaller spec to prevent GL init on headless runner; Kivy data paths (`kivy_install/data/`, `kivy_install/modules/`) are constructed manually instead of importing `kivy.tools.packaging.pyinstaller_hooks`.
- Linux CI uses system Python (ubuntu-24.04) instead of `actions/setup-python` to get `socket.AF_BLUETOOTH` support.
- MDI icon font path resolution tries multiple candidates for cross-platform compat (standard, Android, fallback).
- Live Session layout uses `_compute_graph_height_adaptive`: fixed graph height when viewport is tall, scroll mode when the graph would fall below `dp(400)` (landscape). The bottom bar lives inside the body ScrollView.
- `ScrollableGraphWidget` (`app/ui/raw_eeg_screen.py`) is the single time-series graph class — every per-session/diary graph is an instance of it. Cross-graph affordances live here once, not per screen: `set_expand_callback(cb)` reveals a top-right fullscreen-expand glyph (drawn into `_gfx` by `_draw_expand_icon`, hit-tested at the top of `on_touch_down` *before* `touch.grab`). The glyph uses a fixed light-on-dark color (theme-independent, like `POPUP_TEXT`). The **series picker** (F2) is a second canvas glyph (top-left list icon) via `set_series_picker_callback` — both are drawn into `_gfx` and share the window-coordinate hit-test (`_touch_in_window_rect`), so neither can be starved by the ScrollView the way an overlaid Kivy widget is. Per-graph series selection persists as `graph_series_live_metrics` (JSON, per-user) with legacy `toggle_<key>` migration.
- **Glyph hit-testing is done in WINDOW coordinates** (`_touch_on_expand_icon`). The graph sits inside a `GraphAwareScrollView` that forwards touches in a mid-chain frame matching **neither** the canvas-drawn rect (`touch.x/y`) **nor** a `to_widget`/`to_local` conversion — verified by on-device click logging, each was off by a different amount. The only unambiguous frame is the window: compare the touch's canonical window position (`touch.sx*Window.width, touch.sy*Window.height`) against the glyph's rendered window rect (`self.to_window(...)` of `_expand_icon_rect`). The draw (`_draw_expand_icon`) and the hit-test use the **same** rect, so the visible box is exactly the tap target (no padding mismatch). `app/ui/touch_utils.point_in_rect` is the shared rect test. The History/user-picker manual routers happen to work with raw `collide_point` because their handlers are bound where the touch is already in the right frame — they're not under `GraphAwareScrollView`.
- **`GraphAwareScrollView.on_touch_down`/`on_scroll_start` only intercept touches inside the ScrollView's own viewport** (`self.collide_point` guard). A graph's *logical* bounds extend past the visible viewport when the body overflows (scroll mode), so `_graph_under_touch` would otherwise match — and steal — touches aimed at widgets sitting outside the scroll (e.g. the Metrics/Raw toggle above it). Regression-tested in `tests/test_ui_widgets.py::TestGraphAwareScrollViewGuard`.
- Fullscreen expand (`EEGMeditationApp._present_graph_fullscreen`, wired by `_wire_graph_expand`): **reparents** the graph (not a clone) into a full-window `FloatLayout` overlay on `self._float_root` with `size_hint=(1,1)` + `pos_hint={"x":0,"y":0}` so it reaches every edge — a `Popup` insets its content with chrome. Reparenting keeps the single `Window.on_mouse_down` bind and the live `add_point` feed, so a running session graph updates live in fullscreen. The expand glyph is hidden (`set_expand_callback(None)`) while fullscreen; Close restores the graph to its original parent/index. **Capture `list(size_hint)`/`list(size)` copies before overriding** — they are live `ReferenceListProperty`s; a bare reference tracks the `(1,1)` you set and breaks restore.
- Global crash handler (`app/crash_handler.py`) installs `sys.excepthook`, `threading.excepthook`, and a Kivy `ExceptionManager` handler; all three funnel into a modal dialog that auto-copies a markdown report to the clipboard. Dismiss exits via `app.stop()`. Same module exposes `report_soft_error(label, detail, *, force=False)` for handled-but-significant errors — reuses the dialog with a non-fatal banner and "Close" button (no `app.stop`), and is gated by a 60 s per-label cooldown to prevent spam. Wired to BT connect failures and to the **Copy Diagnostics** button in Settings → Device (which passes `force=True` to bypass the cooldown).
- BT auto-connect picks the single matching MindWave automatically. When more than one paired device matches the `mindwave`/`neurosky` name filter, the auto-scan and start-session paths route the user to Settings → Device, expand the section, scroll it into view, and surface a "pick one" banner with only the matching devices listed. The banner is cleared by `update_device_status(connected=True)`. Helper: `EEGMeditationApp._filter_mindwave`; UI hook: `SettingsScreen.focus_device_section(message)`.
- `_AccordionSection` (`app/ui/theme.py`) binds `_content.minimum_height` to `_update_height` so its inner `_scroll.height` tracks growth from grandchildren added after the section was opened — without it, lists populated post-open (e.g. `populate_bt_devices` after the user expanded Device) get clipped to the original empty-content height.
- Android sessions hold a `PARTIAL_WAKE_LOCK` and run a foreground service (`service/session_keep_alive.py`, declared via `services =` in buildozer.spec) for multi-hour locked-screen operation. `SessionManager.stop(reason)` plays a short warble alert only for **failure** terminations (`stale_data`, `bt_lost`, `error`); `user` and `timer` are planned stops and stay silent (`timer` plays its own gong).
- **Android MediaPlayer teardown must never run on the tick thread.** `MediaPlayer`'s event handler lives on the main Looper, which is paused while the screen is locked, so `release()`/`stop()` from the daemon tick thread deadlocks against it (hung tick thread → session never saved, noise never stops). `setVolume()` has no Looper sync and is safe from the tick thread. Rule: silence on the tick thread with `AudioEngine.mute()`; defer the real `AudioEngine.stop()` / gong `release()` to the main thread. The timer-end path persists the session on the tick thread *before* any audio call so a hang can never cost the session.
- Session persistence is split: `_persist_session_data(reason)` (tick-thread-safe DB write, no Kivy) + `_finalize_stop_ui(stats, id)` (main-thread UI teardown). `_stop_and_save` runs both on the main thread; the timer-expiry path runs `_persist_session_data` on the tick thread and defers `_finalize_stop_ui` via `_on_main`.
- After a session that ended during a screen lock, the live graph is reloaded from the session-lifetime mirror buffers via `_reload_live_graphs_from_mirror()` (used on both Android resume and finish) — the locked portion never reached the live graph through the per-tick `add_point`, so without this the graph would show only the pre-lock seconds while History shows the real duration.
- Kivy `Popup` chrome is always dark and is never themed, so popup body text uses the theme-independent `theme.POPUP_TEXT` (light) — `C.TEXT` is dark in the light palettes and renders invisible dark-on-dark.
- Stats card toggle: tapping the swap icon flips all 5 slots between live instant values and session aggregates (`avg_shamatha`, `avg_meditation`, `time_above_threshold`, `time_shamatha_90`, `longest_streak`). Mode persists per user via the existing JSON user-settings column.
- Meditation timer is split: a headless `TimerState` (`app/session/timer_state.py`) drives the tick-loop countdown; all user-visible controls — enable, duration, custom-sound path, browse and test — live in the Settings → Timer accordion (`SettingsScreen`). When the timer expires (on the daemon tick thread), the order is: persist the session via `_persist_session_data(reason="timer")`, `AudioEngine.mute()` the noise (non-blocking), `_on_main(_finish_on_main)` to defer `_audio.stop()` + `_finalize_stop_ui` to the main thread, then `play_timer_sound()` **last** (one-shot `MediaPlayer` gong, rings through lock). Persisting first and ringing last means a hung audio call can never cost the session or the summary. The gong plays until the file ends or the user taps Save / View in History / Close, each of which calls `AudioEngine.stop_timer_bell()` (releases the gong `MediaPlayer` on the main thread); `_start_session_common` also calls it pre-emptively to kill any long custom gong still ringing from a previous session.

## Documentation Rules

**All documentation files must stay in sync with code changes.** When modifying features, UI, commands, architecture, or build process, update the relevant docs in the same commit or PR:

- `CLAUDE.md` — Architecture, commands, design decisions. Update when adding/removing modules, changing build process, or altering key patterns.
- `readme.md` — English README: features, project structure, build instructions, setup. Update when adding user-visible features or changing platforms/dependencies.
- `readme_ua.md` — Ukrainian README: mirror all `readme.md` changes in Ukrainian.
- `docs/USER_MANUAL.md` — English user manual. Update when UI flow, screens, or settings change.
- `docs/USER_MANUAL_UA.md` — Ukrainian user manual: mirror English manual changes.
- `app/assets/help/help_en.txt` — In-app help content (English). Update when features, connection flow, or settings change.
- `app/assets/help/help_ua.txt` — In-app help content (Ukrainian): mirror English help changes.
- `CHANGELOG.md` — Release history in Keep a Changelog format. Add entries under `[Unreleased]` as you commit; promote to a new version section when tagging.
- `IMPROVEMENTS.md` — Roadmap. Mark items as completed when implemented; add new ideas as they emerge.
- `pyproject.toml` — Ruff config. Run `ruff check app/ tests/ main.py` before every commit; all checks must pass.
