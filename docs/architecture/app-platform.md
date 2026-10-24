# App lifecycle, platform and build

The user gate and profiles, the Android back button, error reporting, the Linux clipboard, test guardrails, and build/CI specifics.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## User gate and profiles

- **Hard user gate:** the app is never usable with no active user.
  `build()` gates on `resolve_startup_user(db)` (the resolved uid, or `None`; through `_restore_last_user`), not on whether users exist:
  after a reinstall, a restored DB, a deleted active profile or a corrupt `last_user_id`, users exist but none is current.
  `_open_user_gate(delay)` is its one entry (build, `on_resume`, a profile delete, a failed gate pick):
  it disables the bottom nav synchronously (no cold-start tap window) and opens the blocking `_show_first_run_popup` (`self._gate_popup`, made un-escapable in `_on_keyboard`).
  `on_resume` re-enters the gate if the process resumed unset; deleting the active profile, or the last one, re-enters it too.
  Per-user handlers use `_require_user(action)` (surfaces a message, returns the uid or `None`) instead of a bare silent `return`:
  `ProgramSettings.on_save`/`on_load`/`on_delete`, `FormulaSettings.on_load`/`on_delete`, the series picker's saved-formula Choose;
  in `ProgramSettings` an empty name and a full library (`_save`) surface a message too.
  History/Diary go through `sessions_for_view(db, uid)`: the active profile's sessions, and `[]` for an **unset** user, so `_current_user_id=None` never leaks every profile's sessions (`get_all_sessions(None)` lists them all).
  **Every path that picks a profile goes through `_activate_user(uid)`** (sets the id, stores `last_user_id`, loads the settings):
  startup restore, the first-run popup's create (`_complete_first_run`) or pick (`_on_pick_existing_user`), and `_on_user_switch`.
  An activation that skipped the load would leave the previous profile's (or the default) values in memory under the new one, for the next flush (e.g. the pre-backup save) to write over its stored settings.
  `_on_user_switch` to another profile is refused through `_refused_while_session_runs` while `_session_pipeline_live()` ("Session in progress", the picker snapped back via `_refresh_profile`):
  the running session owns its loaded timer/threshold/sound settings and saves under the profile it started with.
- `DatabaseManager.create_user` raises `UserExistsError(user_id, name)` on a duplicate.
  The first-run popup and Settings → User Profile use the shared `UserPickerForm` widget (`app/ui/widgets/user_picker.py`);
  its "Use existing 'X'" button goes through `_on_pick_existing_user(user_id)` at the gate, and in Settings switches profile through `_on_user_switch`.
  The picked profile is activated by id as it is (`_activate_user`: its own headset and mock/real mode); typing an existing name at the gate picks it the same way, so first run never overwrites a profile's settings.

## Android back button

- Android hardware back button (`AppManager._on_keyboard`, bound to `Window.on_keyboard`): it consumes key 27 (returns `True`) so Kivy's default exit-on-escape never fires, then routes by precedence.
  While the user gate is active (`_gate_active`, incl. the pre-popup schedule window), `_handle_gate_back` applies double-press-to-exit: never into the app, but a fresh-install user who declines to create a profile can still leave.
  Else an open `Popup`/`ModalView` is left to dismiss itself (the handler returns `False`);
  else an open fullscreen graph overlay closes (`GraphFullscreen.close()`, which runs its stored `_restore` closure);
  else the Diary detail goes back (`_on_diary_back`);
  else any screen but the Session screen switches to it (`_switch_screen("live_session")`, which syncs the bottom-nav highlight);
  else, on the Session screen, **a second press within 2 s exits** (`_exit_on_second_back`, `_last_back_time`), the first showing the in-app `_toast`.
  While the app is leaving (`_leaving`), `_toast` shows the native `_android_toast` (`run_on_ui_thread` + pyjnius `Toast`) instead.
  Esc on desktop follows the same chain.
  **A Python `str` must cross pyjnius as `android_jni.java_string(text)`** whenever the Java method is overloaded:
  pyjnius scores a `str` 10 for both `String` and `char[]` and breaks the tie by sorting signatures (`[C` > `L`), so `Intent.putExtra(EXTRA_TITLE, str)` stores a `char[]` and the SAF save dialog's name comes up blank;
  a `CharSequence` parameter never matches a `str` at all, so `Toast.makeText` raises.

## Errors and diagnostics

- Global crash handler (`app/crash_handler.py`) installs `sys.excepthook`, `threading.excepthook`, and a Kivy `ExceptionManager` handler;
  all three funnel into a modal dialog that auto-copies a markdown report to the clipboard;
  on Linux that copy lasts only while the app runs ([Linux clipboard](#linux-clipboard)), so the fatal banner says to paste it before closing.
  Dismiss exits via `app.stop()`.
  `report_soft_error(label, detail, *, app=None, force=False)` reports handled-but-significant errors in the same dialog with a non-fatal banner and a "Close" button (no `app.stop`), gated by a 60 s per-label cooldown against spam.
  It reports BT connect failures and other handled failures (e.g. failed saves, backup/restore), and Settings → Device's **Copy Diagnostics** passes `force=True` to bypass the cooldown.
- Perf instrumentation: `app/logger.py` `timed(label)` context manager logs `[PERF] label: N.Nms` when `EEG_PERF=1` (off by default).
  Wrap a block to benchmark it.
  On the device it needs a temporary `os.environ["EEG_PERF"] = "1"` at the top of `main.py`, since p4a passes no host environment to the app (`p4a_env_vars.txt` holds only p4a's own vars); then grep logcat for `[PERF]`.
  Timing that must always be on stays aggregated instead (see `render_stats` in [eeg-bluetooth.md](eeg-bluetooth.md)).

## Linux clipboard

- `theme` calls `kivy_providers.clipboard_without_commands()` on import, before any text input asks Kivy for a clipboard:
  on Linux it limits Kivy's providers to SDL2 (`kivy_options["clipboard"] = ("sdl2", "dummy")`, `kivy_options["cutbuffer"] = ()`), and logs an error if Kivy had already picked one.
  `dummy` is Kivy's in-app clipboard, the last resort if SDL2's can't load: copy and paste would then work only inside the app, and the crash dialog's copy would not reach other apps.
  Kivy otherwise picks xclip or xsel by running them when the first text input is built, waiting with no timeout:
  bare `xsel` reads its stdin when that isn't a terminal and asks the X selection's owner, so an open stdin or an owner that never answers hung the app (#118), and a stdin that isn't a terminal cleared the user's selection.
  `KIVY_CLIPBOARD=sdl2` alone isn't enough: the cut buffer is picked from xclip and xsel whatever it says.
  SDL2 reads the clipboard itself, with a 1 s timeout (SDL 2.28.5, bundled with the Kivy 2.3.0 wheel); Kivy builds a text input's clipboard at construction only on Linux, so Android and the other desktops are untouched.
  The cost: no cut buffer, so no middle-click paste or select-to-copy in text inputs, and Kivy logs one CRITICAL "Unable to find any valuable Cutbuffer provider" line per start;
  SDL2 holds a copy only while the app runs, so without a clipboard manager it is gone at exit.
  `tests/test_linux_clipboard.py` builds the first text input through the app's import chain with stand-in commands that never answer,
  and unit-tests `clipboard_without_commands()` on Linux, after Kivy has already picked a clipboard, and on the other platforms.

## Tests

- `tests/test_silent_failure_guardrail.py` is an AST guardrail run on every `pytest` (issue #29 invariant): it scans `app/` and fails on
  a **silent user-gate return** (`if not self._current_user_id: return/pass`, or through a local alias of it, with no user-feedback call)
  or a **discarded bool-returning DB write** (the result of a public `DatabaseManager` method annotated to return a bool, e.g. `add_saved_program`, ignored).
  A legitimately-silent site is grandfathered with a standalone `# silent-ok: <reason>` marker (not a ruff noqa code) that must carry a reason.
- `conftest.py` sets `KCFG_GRAPHICS_MAXFPS=0` before Kivy loads: tests pump frames themselves, and the 60 fps cap only slept between them.
  It adds `--run-slow` (tests marked `slow` are skipped without it; the pre-push run passes it) and `_restore_config`, so a test's change to `APP`/`METRICS`/`SIGMOID` doesn't reach the next file.
  `_temp_files_in_basetemp` points `tempfile` at pytest's basetemp, which pytest rotates: an `AudioEngine` removes its sound folder only in `cleanup()`, which many tests never call.
  At import, conftest wraps `noise`'s `_generate_*_wav` synthesizers in `functools.cache` (and fails if the pattern matches none): the app builds one `AudioEngine`, the tests many, and each would synthesize the same sounds again.
  It has to run at import, before the test modules bind the synthesizers by name (`from app.audio_feedback.noise import _generate_bell_wav`).
  It also removes Kivy's Python-2-only `ObservableList`/`ObservableReferenceList.__setslice__`.
  Kivy 2.3.0's Python 3.12 wheel is built with Cython ≤ 3.0.0, which leaks the traceback of every exception caught inside compiled code (fixed in Cython 3.0.3, cython#5724).
  Those methods always raise AttributeError and Kivy calls them on every `pos`/`size` read and change, so over a run the leaked tracebacks grew to millions of objects that every full collection rescanned;
  without them Kivy takes its `__setitem__` fallback directly.
  The rest of the leak, `WeakProxy.__ref__` raising on dead proxies while Kivy unbinds a dropped widget, stays: removing it would mean copying Kivy's code.
  The app keeps Kivy as it is: it builds its screens once, so its leak stays small.
- `tests/test_docs_format.py` keeps tracked Markdown one sentence per line, so an edit diffs as the sentences it changed:
  it fails on a prose line over 400 characters (tables and fenced code are exempt, and a code fence must close) and on `CLAUDE.md` over `CLAUDE_MD_MAX` (30,000), since every Claude Code session loads it.
  It lists the files with `git ls-files`, so untracked local notes (`IMPROVEMENTS.md`) aren't judged, and it skips outside a git checkout.
  A failure is fixed by breaking the line at a sentence or clause boundary: a single newline inside a paragraph renders as a space.

## Build and CI

**Removing an Android requirement doesn't remove it from local builds.**
p4a keeps it installed in `.buildozer/android/platform/build-arm64-v8a/build/python-installs/eegmeditation/arm64-v8a/`
and keeps reusing the dist `.buildozer/android/platform/build-arm64-v8a/dists/eegmeditation/` (its `dist_info.json` lists the recipes it was built with; a superset of the current ones still counts as a match),
so every later APK keeps bundling it.
After dropping a requirement, delete that package from `python-installs/` and the `dists/eegmeditation` folder (the next build recreates the dist in about a minute), then check the bundle:
site-packages live inside `lib/arm64-v8a/libpybundle.so`, a tar inside the APK.
CI builds start clean and are unaffected.

- The Windows dependencies are one list, `requirements_windows.txt`, which `build_windows.bat` and the CI job both install:
  it pins `kivy[base]` and lets Kivy choose its `kivy_deps` (Kivy 2.3.0 requires `kivy-deps.sdl2 ~=0.7.0`, so an explicit 0.8 pin can't resolve), and adds `pywin32` for the spec's `win32timezone`.
- Windows CI build sets `KIVY_DOC=1` in the PyInstaller spec (`eeg_meditation.spec`) to prevent GL init on the headless runner;
  Kivy data paths (`kivy_install/data/`, `kivy_install/modules/`) are constructed manually instead of importing `kivy.tools.packaging.pyinstaller_hooks`.
- Linux CI uses system Python (ubuntu-24.04) instead of `actions/setup-python` to get `socket.AF_BLUETOOTH` support.
- The MDI icon font's path (`_ICON_FONT_CANDIDATES` in `app/ui/theme.py`) tries several candidates for cross-platform compat (standard, Android, fallback).

- **Java sources** live in `android_src/` (a Gradle source root, `android.add_src`); a service there is declared with `--native-service=<class>` in `p4a.extra_args`, which p4a's manifest template writes without `android:process`.
  That template line has no `foregroundServiceType`, which targeting API 34+ requires (#23): that needs a newer p4a or a template override.

## Background running (Android)

- **A maker's power manager can close the app at foreground-service priority.**
  Huawei's PowerGenie (EMUI 9+) force-stops the whole package during a locked session with the process at adj 200, the foreground-service level:
  `am_kill … 200, stop org.eeg.eegmeditation from pid … iAwareF[PowerGenie]` in the events buffer.
  Neither the in-process foreground service ([session](session.md#screen-lock-and-android)) nor a separate-process keep-alive prevents it, and it doesn't happen in every locked session.
  PowerGenie's rules aren't published: it kills apps outside a built-in whitelist, and no API adds one (dontkillmyapp.com).
  The user-side lever is Battery › App launch › Manage manually.
- **`PowerExemption`** (`app/ui/power_exemption.py`, the app's `_power`) does what the app can: it reads Android's battery optimisation (`PowerManager.isIgnoringBatteryOptimizations`) and the maker (`Build.MANUFACTURER`).
  A maker's own setting has no API, so for `AGGRESSIVE_MAKERS` (dontkillmyapp's 3-of-5 or worse) it can only explain and open a screen.
  `offer_once` shows the alert at the first start with something to allow, after the profile gate (from `on_start`, or from `_finish_first_run` on a first run), and records `power_alert_shown` app-wide: it is the phone's setting.
  A phone with nothing to allow isn't marked, so a lost exemption still gets the alert.
  `refresh` keeps Settings → Device's row (`DeviceSection.show_power_state`, attached only when Android answers) current at every start and resume, since the user may change it in the phone's settings.
- **Screens it opens**: the first that opens (`android_jni.open_first`), on Android's UI thread; none (or a JNI failure building them) → a toast.
  There is no `resolveActivity` check: from Android 11, at target 33, it can't see other apps' screens without a `<queries>` entry and would skip one that is there.
  Battery: `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, Android's own dialog, which needs the `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` permission;
  Google Play allows it only for some kinds of app;
  without the permission the dialog closes at once with no error, so the list after it (`ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS`, the fallback where the dialog isn't on the phone) is never reached:
  a Play build (#23) must open the list instead of the dialog.
  Huawei and Honor: App launch, `com.huawei.systemmanager/…startupmgr.ui.StartupNormalAppListActivity`, then the older `…appcontrol.activity.StartupAppControlActivity`;
  EMUI 12 refuses both to other apps (they need `com.huawei.permission.external_app_settings.USE_COMPONENT`, `signature|privileged`),
  so then the Battery screen (`POWER_USAGE_SUMMARY`, Huawei's `HwPowerManagerActivity`), where App launch is one tap away, and the advice names that path.
  App info (`ACTION_APPLICATION_DETAILS_SETTINGS`) comes last, and it is the only screen for the other makers: on EMUI 12 it has no battery or launch setting at all.
  On EMUI 12 `isIgnoringBatteryOptimizations` can answer true while `dumpsys deviceidle` lists no user app, so on Huawei the Battery line can be missing though nothing was allowed.
  Honor phones on MagicOS moved it to `com.hihonor.systemmanager`, with no confirmed screen name: they get the Battery screen, or App info.
