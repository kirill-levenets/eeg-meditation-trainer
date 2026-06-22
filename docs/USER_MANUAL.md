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

The header shows device status, elapsed time, and current state (color-coded: green=Stable Focus, yellow=Subtle Distraction, red=Gross Distraction, orange=Sinking).

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

Shows full statistics, notes/tags/mood editor, and three graph tabs:
- **Metrics** — all computed metrics
- **Raw EEG** — synthesized waveform from stored band powers
- **Frequencies** — band power chart

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

### Device

- Device status and connection info
- **Use Mock Data** checkbox — uncheck for real device
- **Scan Paired Devices** — finds paired Bluetooth headsets
- Tap a device to select it

### Threshold

- Slider (20-180) with presets: 50, 80, 100, 130, 160
- Sets the dashed line on graphs, "time above threshold" stats, and audio feedback target
- **Audio control metric** — choose which metric drives the audio: Shamatha, NS Meditation, NS Attention, or Custom Formula

### Audio

- **Test Audio** — plays noise sweep + bell + chime + warble
- Toggle sinking alert bell, distraction chime, disconnect warble
- Volume uses log scaling — rises quickly at first, then flattens (max 0.3)

### Display

- **Line Width** slider (0.5-4.0) with presets
- **Rotate Screen** — 0/90/180/270 degrees
- **Marker Hotkey** — keyboard key for placing markers (desktop)

### Graph Metrics

Toggle which metrics are visible on the session graph.

### Custom Formula

Enter a Python-style expression to track as an extra metric. See the reference section in-app for available variables and functions. Save/load formula library.

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