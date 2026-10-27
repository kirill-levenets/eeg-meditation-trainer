# EEG sources and Bluetooth

How EEG data reaches the app: the mock and NeuroSky streams, the Bluetooth link and its reader lifecycle, the BT wait at session start, and the diagnostic tools.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Sources

- **EEG sources** (`app/eeg/`): `mock_stream_v2.py` (mock with frequency-based synthesis, NeuroSky-compatible format) and `neurosky_stream.py` (real Bluetooth RFCOMM / pyserial, ThinkGear protocol).
  Both produce 8 band powers, a raw waveform (512 Hz from the headset; the mock synthesizes 64 samples per 0.5 s tick) and eSense attention/meditation.
  The real stream tracks `_last_packet_time` for stale-data detection and parses battery level (code 0x01, though TGAM hardware doesn't send it); `reset_sample_state()` clears its cached values for a new session.
- **The bands** (`app/eeg/band_spec.py`):
  the 8 bands in their `ASIC_EEG_POWER` (0x83) order, each with the app's name (Alpha 1 for NeuroSky's "low-alpha", matching the custom-formula variables) and its ThinkGear protocol range (delta 0.5–2.75 Hz … gamma2 41–49.75 Hz).
  It also holds the 5 grouped bands, each spanning its sub-bands (the hardware's bands leave gaps: 9.25–10, 16.75–18 and 39.75–41 Hz).
  `neurosky_stream.BAND_NAMES` takes its order from it; the band table and the live and diary band graphs take their names and their 5-band sums (`group_powers`) from it.
  So do the metrics engine (`derive_bands`, `total_power`), the formula replay (`formula_vars_from_row`) and the live band record, so a replayed formula sees exactly the live inputs.
  The band graphs share one scale table and one colour table with the band table's bars (`band_totals.BAND_SCALES` / `BAND_COLORS`).
  The mock's `BAND_FREQ_RANGES` (`mock_stream_v2.py`) are its own invented synthesis bands, not these.

## Connection

- NeuroSky Bluetooth uses pyjnius on Android, a Python `BTPROTO_RFCOMM` socket on Linux, and pyserial over a virtual COM port on Windows.
  Desktop Linux falls back to PyBluez when `socket.AF_BLUETOOTH` is missing (common in PyInstaller bundles).
  The link is kept open between sessions (a session stop doesn't close it) to avoid RFCOMM EBUSY and ThinkGear reinit failures.
  On app exit the socket is not closed explicitly (`on_stop`): the kernel closes it while BlueZ may keep the ACL link, for a faster reconnect at the next launch.
  A session whose headset sends no packets for `_STALE_DATA_THRESHOLD` (10 s) is stopped and saved (`_check_stale_data`).
- Auto-connect selects the single paired device matching the `mindwave`/`neurosky` name filter (`headset.filter_mindwave`).
  When more than one matches, the startup auto-scan and Start route the user to Settings → Device:
  `DeviceSection.focus_device_section(message)` expands the section, scrolls it into view and shows a "pick one" banner over a list of only the matching devices.
  `update_device_status(connected=True)` clears the banner.
- **The link is always to the selected headset.**
  It stays open between sessions, so `NeuroSkyStream.set_device` to another address stops the reader first; otherwise the next Start would reuse the old headset's socket and record its session under the new headset's name.
  Every target change goes through it: a pick in Settings, a profile's saved headset on load or first-run pick, and the start-time auto-select.
  A pick of another headset is refused while a session runs or connects (`Headset.on_select` → `_refused_while_session_runs`), as a profile switch is.
  Settings' row marks rely on this: the connected headset is the selected one while `is_connected` (`Headset.state()`).

## Reader lifecycle and the BT wait

- **The MindWave serves one RFCOMM channel; a connected socket nobody drains stalls its transmitter until the headset is power-cycled.**
  So `NeuroSkyStream`'s reader lifecycle must never orphan one, and **at most one reader thread may exist**.
  That single-reader invariant is the real guarantee:
  readers share `_bt_socket`/`_running`/`_connected`, so with two alive a late reader's `_adopt_socket` overwrites the live one's socket reference and its failure path kills the live session, which the epoch check cannot prevent.
  `start()` bumps `_connect_epoch`, passes it to `_read_loop(epoch)` and **returns a bool**: False (with `_last_connect_error` set) when refused, for no device or a previous reader still alive ("Previous connection is still closing").
  `stop()` sets `_stop_event`, bumps the epoch and closes the socket **before** `join(_STOP_JOIN_TIMEOUT=5s)`; the close interrupts **every** blocking point:
  Android `connect()` (`_run_connect_attempts` publishes each socket as `_pending_socket` before `connect()` and re-checks `_running` after, so `stop()` either closes it or the reader sees the stop;
  a `BluetoothSocket.close()` from another thread aborts `connect()`);
  Android read (socket close);
  desktop `connect()`/`recv()` (`_shutdown_before_close` → `shutdown(SHUT_RDWR)` on native and PyBluez sockets: on Linux a cross-thread `close()` alone doesn't wake them);
  serial read (a `select` 0.5 s poll: a cross-thread `os.close()` doesn't wake `os.read()`);
  and the back-off sleeps (`_stop_event.wait`).
  An aborted connect raises instead of falling through to the next method, and the superseded reader returns quietly without writing `_last_connect_error`.
  A headset-off connect chain takes ~3×7.7 s on the phone; without the abort `stop()` would block the main thread for the full join.
  If the join still times out, `stop()` **keeps** `_thread` so `start()` refuses (nulling it would let a second reader start); it joins a local copy because the tick thread and the main thread can both be in `stop()`.
  `_close_socket` runs under `_close_lock` (`stop()` and the exiting reader both call it).
  A late reader (epoch superseded after its connect returned) closes its socket instead of adopting it, and `_last_connect_error` is cleared only after that check.
  The reader clears `_connected` on exit, so a `stop()` landing just after `_connected = True` can't leave `is_connected` stuck True with no reader (the next Start would "reuse" a dead connection).
  Every failed Android connect attempt (secure → insecure → `createRfcommSocket(1)`) closes its socket; the ch=1 fallback is called directly on the device, since through `Class.getMethod` pyjnius can't resolve its varargs overload.
  In `app_manager`, `_begin_bt_wait()` checks `start()`'s result **before** entering the wait:
  a refusal undoes the start's setup (`_undo_session_setup`) and shows a retry overlay with `_last_connect_error`, with no `bt_connect_failed` soft error (its 60 s cooldown would hide the next real failure).
  **Every BT-wait exit** (Cancel, Stop, no data, keeps closing, failed connect, timeout) goes through `_abort_bt_wait()`:
  it stops the tick watcher (clearing `_waiting_for_bt`/`_bt_signal_start`) **before** `_real_stream.stop()`, then releases the wake lock and keep-alive service.
  The watcher reads `not stream._running` as a failed connect, so stopping the stream first shows a false "Connection failed".
  **A session start is one attempt** (#52):
  `_start_attempt` advances on every Start (`_on_start`) and on every ending (`_undo_session_setup()`, which every ending goes through), and a callback queued for an attempt does nothing once it has moved on.
  That covers the device scan's result in `_on_start` and every main-thread callback the BT wait queues through `_on_main_for_wait`: `_on_session_connected` (the "connected" UI and audio), the exits' retry screens, the overlay text.
  Without it, a Cancel during "Scanning for MindWave…" still starts the session;
  a Cancel or active-profile delete in the frame the first data arrives leaves a zombie (noise playing, idle controls, no tick);
  and a wait exit's queued retry screen undoes the next Start.
  The wait's attempt is `_wait_attempt`, taken on the main thread in `_begin_bt_wait`, not read by the tick thread when it queues:
  a Cancel can land mid-tick and its 1 s tick join can time out (`read_sample` waits for the reader's lock), so the tick may queue after the Cancel has finished.
  If that join times out, the late tick can still start `SessionManager` after the Cancel's reset; only its UI and audio are gated.
  `_on_stop` decides by `SessionManager.state`, not `_waiting_for_bt`, because a wait exit clears the flag before its idle UI shows and a Stop in that window must not offer to save a session that never started:
  RUNNING/PAUSED asks to stop and save;
  FINISHED (the timer ended it on the tick thread and its teardown is queued) is ignored, since cancelling there would stop the kept-alive headset link;
  anything else cancels the start (`_cancel_session_start`).
  Every ending (`_finalize_stop_ui`, a cancelled start, a refused connect and the tick-thread wait exits' queued callbacks) undoes the start's setup through the one `_undo_session_setup()`:
  program series and state via `ProgramRun.end`, the training marker, the shamatha pill, timer and session manager reset, wake lock and keep-alive service (the releases are idempotent).
  A program left behind would have a later simple session persist the program's series over the user's series selection.
  A kept-alive connection's start shows the same `_on_session_connected` as the wait's.
  The header's start time and the graph's wall-clock axis come from `SessionManager.started_at`, not from when the queued UI ran (after a screen lock, the unlock time).
  `_waiting_for_bt`/`_bt_signal_start` are initialized in `__init__`, so a Cancel before any Start finds them.
  **Each connection gets its own windows**:
  when `_handle_bt_wait` sees the link drop while the reader reconnects, `_bt_link_dropped` restarts the no-data window (`_bt_signal_start`, `_BT_SIGNAL_TIMEOUT` 8 s) and the connect window (`_bt_connect_start`, `_BT_CONNECT_TIMEOUT` 30 s).
  It also records `_bt_dropped_at` (monotonic): only packets after the drop count as streaming, since a streaming headset's wait has no no-data timeout and an older packet would keep a silent socket's wait open.
  The session starts only on band data with a packet on this connection (`total > 0 and has_packets`), since the reader keeps the last band values across a reconnect.
  Restarting the windows unbounds a headset that keeps connecting and closing, so a wait ends at its third drop (`_BT_MAX_DROPS` = 2, `_bt_drops` reset per wait) with "keeps closing the connection";
  every wait exit that gives up (keeps closing, no data, a failed connect, the connect timeout) goes through `_give_up_bt_wait(name, message)`, which leaves the headset's name on the Session screen under its retry screen.
  `tests/test_bt_wait_reconnect.py` replays drops and reconnects on a fake clock.
  Android reads drain what is available in one `InputStream.read(buf, 0, n)` per chunk, the buffer sized to the read (pyjnius copies the whole array both ways, so an oversized buffer is slower);
  byte-at-a-time reads would be ~4000 JNI calls/s at the 512 Hz raw rate.
  The reader thread runs at Android priority −8 (the NeuroSky SDK reader's MAX_PRIORITY), so Kivy's renderer can't starve it.
  `_log_throughput` logs `BT throughput: N B/s, N B/read, backlog high-water N B` every 30 s.
  Healthy is ≈4132 B/s (512 raw packets × 8 B + one 36 B eSense packet per second); a high-water that keeps rising means the reader is losing.
  A flat high-water tracks main-thread rendering, not the reader: the main thread holds the GIL during graph redraws, and the backlog vanishes for a screen lock while the tick thread and DB keep running.
  `app/ui/render_stats.py` measures it:
  every `ScrollableGraphWidget._redraw` is timed per `graph_id` (the drawing itself is `_draw`), and a per-frame `Clock` callback (started in `on_start`) tracks the longest gap between frames, ignoring gaps over 5 s (a suspended loop).
  Every 30 s, the cadence of `BT throughput`, a window that had redraws logs `Render: frame gap max N ms | <graph_id> Nx avg N max N ms | …`.
  High-water ≈ longest frame gap × throughput (2 KB ≈ a 0.5 s frame):
  no data is lost while throughput holds, but each long redraw is a visible UI hitch, and a cheaper `ScrollableGraphWidget._draw` is the lever (see **Graph drawing cost** in [graphs.md](graphs.md)).
  `tests/test_neurosky_lifecycle.py` covers stop-during-connect, refuse-while-alive through the real `stop()`, `start()`'s status, concurrent `stop()` and the stale-`_connected` race;
  stop waking a blocked desktop `recv` and a silent serial read;
  connect abort, the successful adopt handover and failed-attempt cleanup.
  `tests/test_bt_wait_abort.py` covers the watcher-before-stream order on Cancel, Stop and a failed connect, the failed-connect wake-lock release, the refused-start path, and `__init__` defining the wait state.

## Diagnostic tools (`tools/`)

- `bt_test.py` — minimal raw RFCOMM + ThinkGear parser for connection debugging, with no Kivy and no threads.
  Usage: `python tools/bt_test.py [MAC] [seconds]` (default 30 s).
  It prints only the ~1 Hz packets (printing all 512 raw-wave packets/s stalls the reader and fakes dropouts) and ends with the single-byte codes the device actually sent (e.g. whether battery 0x01 ever appears).
- `ble_battery_scan.py` — BLE GATT service enumerator (requires `bleak`).
  MindWave Mobile 2 doesn't expose BLE on Linux/Android (iOS only).
