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

**Scrolling and zooming:** Press and drag left/right on the graph to scroll through up to 3 hours of history (works on both desktop and Android). Mouse wheel (desktop) or pinch (Android) to zoom in/out on the time axis. The **|↔|** button in a graph's bottom-right corner shows the whole session so far on all three Session graphs and keeps up as it grows; tap **→|←** to go back. The zoom remembered for your next session is the one you had before fitting. A graph's buttons sit inside it, in its corners: the series list top-left, full screen top-right (in full screen, the ✕ that closes it), fit bottom-right. A drag that starts on a button still scrolls the graph.

### Markers

Tap **Mark** to place a vertical line on the graph. Use this to tag events ("heard a noise", "deep moment"). Markers are saved with the session.

### Pause / Resume / Stop

- **Pause** — temporarily stops recording (paused time excluded from duration)
- **Stop** — asks **"Stop session?"** (Stop / Cancel). The session is always saved — the same as when the timer ends or the headset signal is lost; Cancel returns to the session.

### Session End Summary

Every ending (Stop, timer, lost signal) shows the same **Session saved** card, its title naming the session (date, start time and device). With the phone held sideways the stats are on the left and the notes on the right:
- Duration, **Metric** (the metric that drove the feedback sound, e.g. "Shamatha"; for a program, its name), **Average** (that metric's average over the session; none for a program) and **Threshold** (e.g. "50"; "50 › 65" when you moved the threshold during the session, and with more than three values the first and the last, "50 › … › 70"; for a program, "Per segment"), Time Above Threshold and Longest Streak
- Quick notes field with **Save notes** next to it — saves them ("Notes saved") and keeps the card open
- **OK** — closes the card; notes you typed but didn't save are saved automatically (also if the app goes to the background or is closed)
- **Delete session** — permanently deletes the session after a confirmation ("This can't be undone"); Cancel keeps it

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

**Earlier periods.** The dates above the chart show the period it covers, between **‹** and **›**: they move it a whole window back or forward (14 days in the bars, 18 weeks in the calendar), and a sideways swipe on the chart does the same (swipe right for earlier days). It goes back as far as your first session and forward up to today; an arrow that can go no further turns grey. Tap the dates to come back to today. Calendar and 14-Day show the same period when you switch between them, and the day you tapped stays selected whichever period is shown. A day is picked when your finger lifts, so a swipe that starts on a day doesn't pick it.

The chevron right after the **History** title folds the chart and the totals away, so the session list takes the whole screen (useful with the phone held sideways); tap it again to bring them back. A tapped day stays selected while folded, and each profile remembers whether it was folded.

### Totals

Under the chart (beside it with the phone held sideways), a small table sums your sessions for the **day**, its **week** (Monday to Sunday, as in the calendar) and its **month**, for today or for the day you tapped, and for **All time** (every session, whichever day is shown):
- **Total**: how long you meditated.
- **On target**: time at or above the threshold, each session against its own target (a program's segments, or a threshold you moved, included). Sessions recorded before the app saved which metric they were scored on measured it on Meditation.
- **Best streak**: the longest unbroken run above the threshold in any one session of the period.

A period without sessions shows "–". Tap another day to see its periods; tap it again or **Show All** to go back to today.

### Day Filter

In either view, tap a day (cell or bar) to filter the session list below to that date. Tap the same day again (or **Show All**) to reset.

### Session List

Each session row shows:
- Color indicator (score)
- **Date, start time and name**, e.g. "2026-09-26 14:30 - MindWave Mobile" (a renamed session: "2026-09-26 14:30 - Morning sit"; the date and time are always shown, also in a day's list)
- **Score line**: the metric the session was scored on (the one that drove the feedback sound) and its average, the duration, and the longest streak above the threshold, e.g. "Shamatha 72 · 25m 00s · Streak 4m 30s". A program session shows the program's name instead of an average; a streak of 0 is left out. Sessions recorded before the app saved which metric they were scored on show the average Shamatha and the duration, as before ("Shamatha 50 · 15m 00s").
- **Notes**: the first line of the session's notes, when it has any
- **Pencil icon** — tap to rename inline (you edit the name; the date and time stay)
- **Trash icon** — tap to delete (with confirmation)

Long names and notes are cut with "…" to fit the row. The session detail is titled the same way as its row.

Tap a session row to view full details (graphs, notes, tags, mood).

**Export multiple sessions:** tap **Select** (top right of the list) to enter selection mode — checkboxes appear, tap rows to select them (or **Select all**), then **Export N** bundles the chosen sessions into one **ZIP** containing one CSV per session. On Android the ZIP is saved to `Documents/EEGMeditation/`; on desktop to a Documents folder. **Cancel** leaves selection mode.

**Delete multiple sessions:** in selection mode, **Delete N** deletes the chosen sessions after one confirmation, which states how many and over which days (and how many profiles, in the All Users view). It can't be undone. The list keeps your place, and selection mode ends once they are deleted. A session that is still running isn't listed in History; it appears there once it ends.

### Session Detail

Opens as soon as you tap the session: its stats and notes are there at once, and the band power and graphs show "Loading…" until their data is in. Titled like its row. Shows Duration, **Metric**, **Average** and **Threshold** (what the session was scored on, that metric's average, and what Time Above Threshold and Longest Streak were measured against — "50 › 65" when the threshold was moved during the session, as on the Session saved card; for a program, its name and "Per segment", with no average; sessions from before this was saved show **Avg Shamatha** and **Threshold Used** instead), Time Above Threshold, Longest Streak and Mood Rating, a **Band Power (whole session)** breakdown, notes/tags/mood editor, and three graph tabs (the Metrics legend marks the scored series with **»**):
- **Metrics** — all computed metrics; the dashed threshold line steps where the threshold changed (a moved slider, a program's segments)
- **Raw EEG** — synthesized waveform from stored band powers
- **Frequencies** — band power chart

The **|↔|** button in a graph's bottom-right corner shows the whole session at once, on all three of its graphs (Raw EEG keeps only the session's last minute, so it shows that; a session over 3 hours shows its last 3); tap it again (**→|←**) to go back to the window you had. It stays on as you open other sessions, and pinching or the mouse wheel zooms on from there. Zooming a session's graphs no longer changes the Session screen's graph, and the reverse. Past an hour the time axis reads hours (1:15:00).

**Try another threshold** (under the stats): what Time Above Threshold and Longest Streak would have been at another threshold. Move the slider (or −/+ by 5) and both are recalculated from the session's own recorded data, and the Metrics graph's dashed line moves with it; **Reset** goes back to the session as recorded — the line under the title says what that was ("Recorded at 70", or "70 › 85" when the threshold was moved during it). One threshold applies to the whole session. A **program** session gets one slider per segment instead, each titled with its number, metric and recorded target and followed by that segment's own time above threshold and streak; the **Whole session** totals come after them, and a streak running from one segment into the next counts there as one, as it did live. Moving a segment's slider changes only that segment (and the totals) and only its part of the graph's line. It's only a view: nothing about the session changes, and reopening it starts as recorded again. The chevron right after its title folds it away (Reset stays beside it); the app remembers that for each profile.

**Notes, tags and mood** save with **Save Notes** ("Notes saved"). An edit you don't save is saved for you when you leave the session — **Back**, another tab, or the app going to the background — with the same "Notes saved". Opening a session and leaving without a change writes nothing, and leaving saves only what you changed, so it never rates a session you haven't rated — **Save Notes** saves what the screen shows, mood included.

**Band Power (whole session)** is a sortable table of total power per frequency band — colored bars scaled by each band's share of the session total, plus Power and % columns — a quick read of where your brainwave energy was concentrated. A **Detailed / Grouped** toggle switches between the 8 sub-bands (delta / theta / alpha1 / alpha2 / beta1 / beta2 / gamma1 / gamma2) and 5 collapsed bands (alpha = alpha1+alpha2, beta = beta1+beta2, gamma = gamma1+gamma2). Each band's frequency range, as the headset measures it, is in a small line under its name: Delta 0.5–2.75 Hz, Theta 3.5–6.75, Alpha 1 7.5–9.25, Alpha 2 10–11.75, Beta 1 13–16.75, Beta 2 18–29.75, Gamma 1 31–39.75, Gamma 2 41–49.75 Hz; a grouped band shows the span of its two (Alpha 7.5–11.75, Beta 13–29.75, Gamma 31–49.75 Hz), though the headset leaves small gaps between them (9.25–10 Hz, 16.75–18 Hz, 39.75–41 Hz). Tap a column header to sort (tap again to reverse). Your chosen view and sort are remembered per profile. The chevron right after the **Band Power** title folds the table away (tap it again to bring it back); each profile remembers whether it was folded.

Tap **Export CSV** to save session data. On Android, saves to `/sdcard/EEGMeditation/exports/`. On desktop, a file chooser opens. Each row also says what it was scored on: `score_key` (the metric), `score_value` (its value) and `score_target` (the threshold in force); these are empty for sessions recorded before the app saved them.

---

## Settings

Settings uses collapsible accordion sections. Tap a section header to expand/collapse.

### User Profile

- Current user shown at top.
- **Existing profiles** appear in a list at the top of the form. Tap one to switch to it.
- Type a new name into the input and tap **Create** to add a profile.
- If the name you typed already exists, an inline message offers two buttons: **Use existing 'X'** (switch to that profile) or **Change name** (back to the input). Names are unique and case-sensitive.
- Each user has separate sessions, settings, and formulas. The **X** button on a row deletes that profile after a confirmation — together with all its sessions and settings; the dialog shows how many sessions will go.
- Switching profiles is refused while a session is running or connecting ("Session in progress") — a running session keeps the settings it started with. Stop the session first.

### Data Backup

Settings → **Data Backup** lets you save a copy of your sessions to a file and restore it later.

- **Backup database** — saves your current settings, then writes a transaction-safe copy of the live database (all profiles) The suggested file name carries the profile name and the date and time, e.g. `eeg_backup_Anna_2026-09-29_17-49.db`. You choose where: on Android a system save dialog opens (e.g. Downloads, Documents, a cloud drive); on desktop, a file dialog. A **Backup saved** dialog confirms it and reminds you that custom sound files are not included.
- **Restore database** — pick a backup file. The app validates it (must be a real SQLite file with `users` and `sessions` tables), shows a confirmation dialog, then replaces the live database. The app will exit after restoring — relaunch it to see your imported history.

Two things to know before restoring:
- Restore replaces the **entire database — all profiles** on this device, not just the current one.
- A backup contains only the database. **Custom sound files** (feedback / reward / timer) are referenced by path and are **not** included, so those paths may not resolve on another device.

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
- **Scan Paired Devices** — finds paired Bluetooth headsets. Each row shows the headset's name and its address: every MindWave has the same Bluetooth name
- Tap a device to select it. The row of the headset in use is filled; the connected one shows a Bluetooth sign (with Mock Data on, none is marked). You can't switch headsets while a session runs or connects
- **Name a headset** — tap the pencil on its row, type a name and tap **Save** (or Enter). The name is the same for every profile on the phone and shows in the device status, on the Session screen and in the names of new sessions. Leave it blank to go back to the Bluetooth name

### Threshold

- Slider (20-180) with presets: 50, 80, 100, 130, 160
- Sets the dashed line on graphs, "time above threshold" stats, and audio feedback target
- Moving it during a session changes the threshold once the slider stays put for half a second (a drag is one change, at the value it stops on): the feedback sound, Time Above Threshold, Longest Streak and the **SHAMATHA** badge all follow it, and the graph's dashed line steps at the change (live and later in History). The session keeps each threshold it ran with. With no session running, a new threshold clears the last session's graphs from the Session screen (it stays in History) and shows the new line. During a program session the segments set the targets, so the threshold can't be changed until it stops: the slider, the −/+ buttons and the presets are dimmed and don't move, and each touch on them shows **Session in progress** saying why.
- **Time above threshold** and **Longest streak** are measured on the **audio control metric** below — the same metric that drives the feedback sound — and the live graph legend marks it with **»** when that line is shown. Each session records which metric it was scored on. (Sessions recorded before this change were measured on Meditation.)
- **Audio control metric** — choose which metric drives the audio: Shamatha, NS Meditation, NS Attention, or Custom Formula (slot 1, 2, or 3 selected via the `[1][2][3]` buttons). If the selected custom slot has no valid formula the audio falls back to shamatha. While a session runs (or connects) this choice is locked, and so is the formula in the selected slot: a session is scored on one metric from start to stop. The other formula slots and the threshold stay editable, and a program session, scored on its segments' metrics, leaves the metric and the formula slots free (its threshold is locked, see above).

### Audio

- **Feedback sound (below threshold)** — the button opens a picker to choose the below-threshold channel:
  - **Off** — no sound below the threshold
  - **Rain** — the original rain/white-noise sound
  - **Tone** — a built-in harmonic pad drone (fundamental + a fifth); no file needed
  - **Custom file…** — opens a file browser to pick a user-supplied audio file (wav, mp3, ogg, flac, m4a); the button then shows the chosen file. The sound loops continuously; its volume is still modulated by the active metric exactly as Rain is.

  This sound is loudest when you are far below your threshold and fades to silence as you reach it.
- **Reward sound (above threshold)** — the button opens a picker to choose a second channel that is **silent until you cross the threshold**, then fades in and grows the further above it you go (full at +30 points). Default **Off**. Options are Off / Rain / Tone / **Crickets** / Custom file…:
  - **Crickets** — a soft cricket chirp about once every 10 seconds (rather than a continuous sound), as a "you're doing well / still here" cue while you hold above the threshold; like the other reward sources it grows louder the deeper above threshold you go.

  Use the reward channel for a positive "you've reached shamatha" cue that builds as you deepen. The two channels cross-fade cleanly at the threshold; set either to **Off** for silence on that side.
- **Test Audio** — previews the selected reward sound (incl. Crickets), then a feedback sweep + bell + chime + warble
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