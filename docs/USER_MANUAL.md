# EEG Meditation Trainer - User Manual

> **Disclaimer:** This software is for educational and personal exploration purposes only. It is not a medical device and must not be used for medical diagnosis or treatment. EEG data from consumer-grade headsets is inherently noisy. Use at your own risk.

## Getting Started

### First Launch — Setup Wizard

When you open the app for the first time, a **2-step wizard** guides you through setup:

1. **Step 1: Create Profile** — Enter your name. This creates your user profile for tracking sessions and settings.
2. **Step 2: Connect Device** — Tap "Scan for Devices" to find your paired MindWave, or tap "Skip (use demo mode)" to try the app with simulated EEG data.

After the wizard, you land on the Session screen ready to meditate.

On subsequent launches, the app restores your last profile and device automatically.

### Navigation

The app has **3 tabs** at the bottom:

**Session** | **History** | **Settings**

- **Session** — Live meditation with real-time graph and controls
- **History** — Calendar heatmap of past sessions, session list
- **Settings** — All configuration: profile, timer, device, threshold, audio, display, graph, formulas, themes, help

---

## Session

### Starting a Session

Next to the **Start** button there is a small **duration picker** that shows the current session length — for example `▼ 10 min` or `▼ Free` when the timer is off. Tapping the duration button opens a popup with five choices: **5**, **10**, **15**, or **20 minutes**, or **Free** to disable the timer. The currently active choice is highlighted. Tap a preset to apply it and dismiss the popup; the duration button label updates to match. Tap outside the popup to dismiss without changes. If you set a custom duration via Settings → Timer (e.g. 25 min), the duration button still shows the current value.

Tap **Start** to begin the session — the app auto-detects and connects to your MindWave headset.

**Connection overlay** shows progress:
- "Connecting to MindWave... Timeout in 17s"
- "Connected — Waiting for EEG data... Sensor: no contact"
- "Sensor: good" → session starts

If no device is selected, the app auto-scans for paired MindWave devices. If none found, you can scan manually in Settings > Device.

### During the Session

**Metrics / Raw EEG toggle** — switch between two views without leaving the session:
- **Metrics view** — real-time scoring graph (Shamatha, Distraction, Sinking, etc.)
- **Raw EEG view** — oscilloscope waveform (512Hz) + frequency band chart

The header shows device status, elapsed time, and current state (color-coded: green=Stable Focus, yellow=Subtle Distraction, red=Gross Distraction, orange=Sinking). When your shamatha score holds at or above your meditation threshold, the state turns into a bold **SHAMATHA** badge on a green pill, and reverts when you drop back below (with a brief debounce so it doesn't flicker).

**Stats row** below the graph: Shamatha, Distraction, Sinking, NS Attn, NS Med.

**Scrolling and zooming:** Press and drag left/right on the graph to scroll through up to 3 hours of history (works on both desktop and Android). Mouse wheel (desktop) or pinch (Android) to zoom in/out on the time axis.

### Markers

Tap **Mark** to place a vertical line on the graph. Use this to tag events ("heard a noise", "deep moment"). Markers are saved with the session.

### Pause / Resume / Stop

- **Pause** — temporarily stops recording (paused time excluded from duration)
- **Stop** — ends the session, shows a summary card

### Session End Summary

After stopping, an overlay shows:
- Duration, Avg Shamatha, Avg Meditation, Time Above Threshold
- Quick notes text field for immediate reflection
- **Save** — saves notes and closes
- **View in History** — navigates to History tab
- **Close** — dismisses without saving notes

### Session Limit

Sessions auto-stop after **3 hours** with an alert sound. Start a new session to continue.

### Bottom stats toggle

Tap the swap icon on the right of the stats row to switch between **live** instant values (Shamatha, Distraction, Sinking, NS Attn, NS Med) and **session aggregates** (Avg Shamatha, Avg Meditation, Time above Threshold, Time ≥90, Longest Streak). Your choice persists.

### Locked-screen sessions (Android)

You can start a session, lock the phone, and the session will continue for hours. A persistent notification indicates the session is active. EEG processing, metrics computation, and audio volume adjustments all continue uninterrupted on a background thread — audio keeps playing even while the screen is off. The connection-attempt countdown in the overlay also runs to completion cleanly (no freezing on slow Bluetooth connects). If the connection drops or the session ends unexpectedly, a short warble sound plays so you notice.

### If the app crashes

If an unexpected error occurs, a dialog appears with a pre-filled crash report — already copied to your clipboard. Paste it into a new issue at `github.com/kirill-levenets/eeg-meditation-trainer/issues` and tap **Dismiss & Exit**.

---

## History

The History tab has a segmented toggle at the top: **Calendar** / **14-Day**.

- **Calendar** — GitHub-style heatmap colored by daily average Shamatha score. Brighter green = better days.
- **14-Day** — Bar chart of the last 14 days, one bar per day, height proportional to that day's average Shamatha. Empty days show as a thin baseline so streaks/gaps are visible.

The selected mode is persisted per user.

### Day Filter

In either view, tap a day (cell or bar) to filter the session list below to that date. Tap the same day again (or **Show All**) to reset.

### Session List

Each session row shows:
- Color indicator (score)
- Session name (e.g. "14:30 - MindWave Mobile")
- Stats (Shamatha score, duration)
- **Pencil icon** — tap to rename inline
- **Trash icon** — tap to delete (with confirmation)

Tap a session row to view full details (graphs, notes, tags, mood).

### Session Detail

Shows full statistics, a **Band Power (whole session)** breakdown, notes/tags/mood editor, and three graph tabs:
- **Metrics** — all computed metrics
- **Raw EEG** — synthesized waveform from stored band powers
- **Frequencies** — band power chart

**Band Power (whole session)** is a sortable table of total power per frequency band — colored bars scaled by each band's share of the session total, plus Power and % columns — a quick read of where your brainwave energy was concentrated. A **Detailed / Grouped** toggle switches between the 8 sub-bands (delta / theta / alpha1 / alpha2 / beta1 / beta2 / gamma1 / gamma2) and 5 collapsed bands (alpha = alpha1+alpha2, beta = beta1+beta2, gamma = gamma1+gamma2). Tap a column header to sort (tap again to reverse). Your chosen view and sort are remembered per profile.

Tap **Export CSV** to save session data. On Android, saves to `/sdcard/EEGMeditation/exports/`. On desktop, a file chooser opens.

---

## Settings

Settings uses collapsible accordion sections. Tap a section header to expand/collapse.

### User Profile

- Current user shown at top.
- **Existing profiles** appear in a list at the top of the form. Tap one to switch to it.
- Type a new name into the input and tap **Create** to add a profile.
- If the name you typed already exists, an inline message offers two buttons: **Use existing 'X'** (switch to that profile) or **Change name** (back to the input). Names are unique and case-sensitive.
- Each user has separate sessions, settings, and formulas. The **X** button on a row deletes that profile after a confirmation.

### Data Backup

Settings → **Data Backup** lets you save a copy of your sessions to a file and restore it later.

- **Backup database** — writes a transaction-safe copy of the live database. On Android the backup goes to `Documents/EEGMeditation/meditation_backup_YYYYMMDD_HHMMSS.db` (visible to file managers and Telegram's "attach file" picker). On desktop, a save dialog opens.
- **Restore database** — pick a backup file. The app validates it (must be a real SQLite file with `users` and `sessions` tables), shows a confirmation dialog with the current session count, then replaces the live database. The app will exit after restoring — relaunch it to see your imported history.

The Restore replaces your current database and cannot be undone. Use Backup first if you want to keep the current state.

### Timer

- Enable/disable toggle
- Duration slider with presets: 5, 10, 15, 20, 30 minutes
- When enabled, auto-stops session at the end and plays bell sound

#### Session Program

The **Timer** section has a **Simple | Program** toggle at the top. In **Simple** mode the Enable-Timer checkbox and duration slider are available — this is the single-duration timer. In **Program** mode that checkbox is hidden (the program always runs its own timer) and a multi-segment editor appears instead.

**Program mode** lets you define an ordered list of timed segments. Each segment row has:

- **Duration** — length in minutes
- **Formula** — the metric that drives audio feedback for this segment: Shamatha, Meditation, NS Attention, NS Meditation, or any formula saved in your custom-formula library
- **Target** — the threshold level for this segment (sets the dashed line and "time above target" stat)
- **End cue** — sound played when this segment ends: **Chime** (default) or **Warble**
- **Feedback** — the continuous feedback sound for this segment: **Default** (inherits the global Audio setting), **Rain**, **Tone** (built-in harmonic pad), or a **Custom** file set in Settings → Audio. The source switches at each segment boundary.

Use **+ Add Segment** to append a row; tap the delete icon on a row to remove it. The **total duration** readout at the bottom updates automatically.

**Saving and loading programs:**

Type a name and tap **Save** to store the current segment list in your library. Names are unique — if you save with a name that already exists, the app asks you to confirm the **overwrite** before replacing it.

Saved programs appear in a list below the editor. Tap a program to **load** it; tap the delete icon to **delete** it. Both actions ask for confirmation first.

When a program is loaded into the editor, the header shows **"Loaded: \<name\>"** so you always know which program is active. The name field is pre-filled with that name, so tapping **Save** again will re-save (overwrite) it without retyping.

The library is per-user.

**Quick-loading from the Session screen:**

When Program mode is active, the small button next to **Start** shows a large **P** (indicating the program's total duration will run the timer). Tap that button to open a **Programs…** picker directly from the Session screen — without going to Settings. The picker shows the name of the currently loaded program and highlights it in the list.

**During a session:**

- The session timer is set to the program's total duration and auto-stops at the end (the timer-end gong plays).
- The metrics graph automatically shows each segment's target metric or custom-formula line. The **legend marks the currently active metric in bold with a "»" indicator**, switching at each segment boundary.
- At each segment boundary a **chime** plays and the active target and audio-driver formula switch to the next segment's settings. "Time above target" accrues against each segment's own target while that segment is active.
- A **stepped dashed target line** tracks each segment's target over its time range on both the live session graph and the diary graph.
- The **gong** plays at the end of the program.

**Text fields** in the program editor (and elsewhere in the app) show their text centered.

The **Feedback** picker on each segment row lets you use a different sound per segment (see the Feedback row in the segment fields list above).

When Program mode is off, the Simple timer behaves exactly as before.

### Device

- Device status and connection info
- **Use Mock Data** checkbox — uncheck for real device
- **Scan Paired Devices** — finds paired Bluetooth headsets
- Tap a device to select it

### Threshold

- Slider (20-180) with presets: 50, 80, 100, 130, 160
- Sets the dashed line on graphs, "time above threshold" stats, and audio feedback target
- **Audio control metric** — choose which metric drives the audio: Shamatha, NS Meditation, NS Attention, or Custom Formula (slot 1, 2, or 3 selected via the `[1][2][3]` buttons). If the selected custom slot has no valid formula the audio falls back to shamatha.

### Audio

- **Feedback sound** — `[Rain] [Tone] [Custom]` selector chooses the continuous feedback channel:
  - **Rain** — the original rain/white-noise sound
  - **Tone** — a built-in harmonic pad drone (fundamental + a fifth); no file needed
  - **Custom** — plays a user-supplied audio file (wav, mp3, ogg, flac, m4a). A path row and **Browse** button appear to select the file. The sound loops continuously; its volume is still modulated by the active metric exactly as Rain is.
- **Test Audio** — plays feedback sweep + bell + chime + warble
- Toggle sinking alert bell, distraction chime, disconnect warble
- Volume uses log scaling — rises quickly at first, then flattens (max 0.3)

### Display

- **Line Width** slider (0.5-4.0) with presets
- **Rotate Screen** — 0/90/180/270 degrees
- **Marker Hotkey** — keyboard key for placing markers (desktop)

### Graph Metrics

Toggle which metrics are visible on the session graph.

### Custom Formula

Three independent named slots (Slot 1, 2, 3), each with:

- **Name** — label shown on the graph series and in the diary
- **Expression** — Python-style formula using band powers, normalized bands, computed metrics, math functions, and `avg(expr, N)` windowed averages; AST-parsed with whitelist validation
- **Apply** — evaluates the expression; a status line shows the current value or error
- **Save** — saves the formula to the per-user library under the slot's current name

To assign a saved formula to a slot without opening Settings, use the **Choose…** button on the matching custom-formula row in the on-graph series picker (live metrics graph).

The slot that drives the audio noise channel is selected via the `[1][2][3]` buttons under the "Custom Formula" audio-metric radio in Settings → Threshold. If the selected slot's formula is invalid, the audio falls back to shamatha.

All three custom series share one Y-axis (scale 0–200, reference line at 100). For best results keep formula outputs in a comparable range to the other metrics.

The diary **replays the formulas that were active during each session** — opening a session in History recomputes those series from the stored band powers, so you see the same names and values that were live at the time.

### Theme

4 color themes: **Dark Blue** (default), **Dark Green**, **Light Cream**, **Light Green**. Changes apply immediately.

### Help & Troubleshooting

In-app help with quick start guide, connection troubleshooting, supported devices, sensor tips, and more.

---

## Connection Troubleshooting

If your device won't connect:

1. **Check battery** — the most common cause of connection problems. Replace the AAA battery if the headset connects but shows "not streaming". NiMH rechargeable (1.2V) is recommended — ignore the red LED indicator (it's calibrated for 1.5V alkaline). Avoid Li-ion 1.5V rechargeable batteries — their voltage regulator masks low charge and causes silent failures.
2. **Check Bluetooth** — enabled on your phone/computer, headset is paired in system BT settings
3. **Clean sensors** — wipe the forehead sensor and ear clip with an alcohol pad
4. **Reset pairing** — remove the device from BT settings, then re-pair it (fixes most issues)
5. **Close other BT apps** — only one app can hold the RFCOMM connection at a time
6. **Restart headset** — turn off, wait 5 seconds, turn on
7. **"Connected but not streaming"** — the headset connects but no EEG data appears. This almost always means a weak battery. The Bluetooth radio needs less power than the EEG chip, so the headset can connect but the EEG processor can't start. Replace the battery.
8. **Test with manufacturer's app** — if it also can't connect, the headset may be faulty

### Supported Devices

Any headset with NeuroSky TGAM module and Bluetooth Classic:
- NeuroSky MindWave Mobile / Mobile 2
- BrainLink SE / Lite / Pro
- MindLink Brainwave
- Sichiray headsets

**Note:** Bluetooth Classic (RFCOMM) only — BLE headsets are not supported.

### Sensor Contact Tips

For good EEG signal quality:
- Clean your forehead (remove oil/sweat)
- Wipe sensor pads with alcohol
- Press the sensor firmly against skin
- Minimize hair under the sensor
- Signal quality during connection: 0 = perfect, 200 = no contact

---

## Tips

- **Try demo mode first** to learn the interface before connecting a real headset
- **Set your threshold** based on experience level — beginners: 40-60, experienced: 80-130
- **Use markers** to note significant moments during practice
- **Write quick notes** in the session summary right after stopping
- **Review the heatmap** to track your consistency over weeks
- **Try custom formulas** to experiment with different metrics
- On Android, the screen stays on during sessions (wake lock)
- All settings are saved per-user and restored on next launch