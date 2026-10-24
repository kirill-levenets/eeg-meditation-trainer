# EEG Meditation Trainer - User Manual

> **Disclaimer:** This software is for educational and personal exploration purposes only.
> It is not a medical device and must not be used for medical diagnosis or treatment.
> EEG data from consumer-grade headsets is inherently noisy.
> Use at your own risk.

## Getting Started

### First Launch — Choose a Profile

When you open the app for the first time, it asks you to **create a profile or pick an existing one**: type your name and tap **Create**, or tap a profile that is already there (after restoring a backup, for example).
Your profile keeps your sessions and settings.

The app then looks for your headset among the phone's paired Bluetooth devices:

- **One MindWave paired**: it is selected for you.
- **Several**: Settings → Device opens so you can pick the one to use.
- **None**: the app runs on simulated EEG data (demo mode); pair your MindWave, then pick it in Settings → Device.

A profile that already has a headset saved uses it straight away.
You land on the Session screen, ready to meditate.
On later launches the app restores your last profile and headset.

### Navigation

The app has three tabs at the bottom:

- **Session**: the live session, with its graphs and controls
- **History**: past sessions on a calendar or bar chart, and their list
- **Settings**: profile, timer and programs, device, backup, threshold, audio, display, formulas, theme and help

---

## Session

### Starting a Session

The button next to **Start** shows what the next session runs: its length (e.g. `10m`, `1h`), `∞` with no timer, or a large **P** in Program mode.
Tap it to pick a length: 5, 10, 15, 20 or 30 min, 1 h, 1 h 30 min, 2 h, or **Free** (no timer).
The current choice is highlighted, and picking a length switches Program mode off.
A length set in Settings → Timer / Program (e.g. 25 min) shows on the button too.
The same list has **Programs…** (**Program: \<name\>** when one is loaded), described under Session Program.

Tap **Start** to begin; the app connects to your headset.
If none is selected yet, it first looks among the paired devices: one MindWave is used, several open Settings → Device to pick one, and none gets a message to pair it.

The **connection overlay** shows the progress:
- "Connecting to MindWave Mobile... Timeout in 25s", counting down from 30 s
- "Connected to MindWave Mobile", then "Waiting for EEG data..." or "Place sensor on forehead...", with the sensor's contact: no contact, poor, fair or good
- the session starts as soon as EEG data arrives

**Cancel** stops a connection attempt.
If it fails, the overlay says why, with **Retry** and **Close**.

### During the Session

**Metrics / Raw EEG** switches between two views without leaving the session:
- **Metrics**: the scores over time (Shamatha, Distraction, Sinking, etc.)
- **Raw EEG**: the raw waveform (512 Hz) and the frequency bands

The header shows the headset, the start and elapsed time, and the current state, colour-coded: green = Stable Focus, yellow = Subtle Distraction, red = Gross Distraction, orange = Sinking.
When your shamatha score holds at or above the threshold, the state turns into a bold **SHAMATHA** badge on a green pill; it reverts when you drop below (after a short delay, so it doesn't flicker).

**Scrolling and zooming:** drag sideways on a graph to scroll back through up to 3 hours.
Pinch (Android) or the mouse wheel (desktop) zooms the time axis.
A graph's buttons sit in its corners: the series list top-left (which lines it shows), full screen top-right (in full screen, the ✕ that closes it) and fit bottom-right.
A drag that starts on a button still scrolls the graph.
**|↔|** (fit) shows the whole session so far on all three Session graphs and keeps up as it grows; **→|←** goes back.
The zoom remembered for your next session is the one you had before fitting.

### Markers

Tap **Mark** to draw a vertical line on the graph and tag a moment ("heard a noise", "deep moment").
Markers are saved with the session.

### Pause / Resume / Stop

- **Pause** stops recording until **Resume**; paused time doesn't count toward the duration.
- **Stop** asks **"Stop session?"**: **Stop** saves the session, as the timer's end or a lost signal does; **Cancel** returns to it.

### Session End Summary

Every ending (Stop, the timer, a lost signal) shows the same **Session saved** card, titled with the session's name (date, start time and headset).
With the phone held sideways, the stats are on the left and the notes on the right:
- Duration, **Metric** (the one that drove the feedback sound, e.g. "Shamatha"; for a program, its name), **Average** (that metric's, over the session; none for a program) and **Threshold**, then Time Above Threshold and Longest Streak.
  **Threshold** is e.g. "50"; "50 › 65" when you moved it during the session, its first and last value with more than three ("50 › … › 70"); "Per segment" for a program.
- A quick notes field with **Save notes**, which saves them ("Notes saved") and keeps the card open.
- **OK** closes the card; notes you typed but didn't save are saved then, or when the app goes to the background or closes.
- **Delete session** deletes the session for good, after a confirmation ("This can't be undone"); **Cancel** keeps it.

### Session Limit

A session stops and is saved at **3 hours**, with a message, and with the disconnect warble when that alert is on in Settings → Audio.
Start a new session to continue.

### Bottom stats toggle

The stats row under the graph shows live values: Shamatha, Distraction, Sinking, NS Attn and NS Med.
Its **LIVE** / **AVG** button switches to the session's averages and times:
**Avg Sham**, **Avg Med**, **>Thresh** (time above the threshold), **≥90** (time with Shamatha at 90 or more) and **Streak** (the longest one above the threshold).
Your choice is remembered.

### Locked-screen sessions (Android)

You can start a session and lock the phone: the session runs on for hours, with a notification while it is active.
EEG processing, scoring and the feedback sound carry on with the screen off.
If the session ends unexpectedly (no EEG data for 10 seconds), a short warble plays so you notice; with **Audio alert on disconnect / signal loss** on, a dropped connection warbles too.

Some phones close background apps to save battery, notification or not: Huawei, Xiaomi, Samsung, OnePlus, Oppo, Vivo and others.
A locked session then ends early; what was saved up to the last minute is kept.
At the first start the app says what your phone needs and opens the screens:
- **Battery** asks Android to leave the app out of battery optimisation.
- On Huawei and Honor, **App launch** opens the phone's own setting, or its Battery screen where App launch is listed: set EEG Meditation to **Manage manually** with all three switches on.
- On other makers, **App info** opens the app's info, where its battery or background setting is.

Nothing changes unless you allow it there.
The same buttons are under Settings → Device → **Locked-screen sessions**.

### If the app crashes

A dialog shows the crash report, already copied to your clipboard.
Paste it into a new issue at `github.com/kirill-levenets/eeg-meditation-trainer/issues`, then tap **Dismiss & Exit**.

---

## History

The **Cal** and **14d** buttons beside the chart switch its view:

- **Cal**: a GitHub-style calendar, each day coloured by its average Shamatha; brighter green = better days.
- **14d**: 14 bars, one per day, as tall as that day's average Shamatha; a day without sessions is a thin stub, so streaks and gaps show.

Each profile remembers the view.

**Earlier periods.** The dates above the chart show the period it covers, between **‹** and **›**, which move it a whole window back or forward (14 days in the bars, 18 weeks in the calendar).
A sideways swipe on the chart does the same (swipe right for earlier days).
It goes back as far as your first session and forward up to today; an arrow that can go no further turns grey.
Tap the dates to come back to today.
Both views show the same period when you switch, and the day you tapped stays selected whichever period is shown.
A day is picked when your finger lifts, so a swipe that starts on a day doesn't pick it.

The chevron right after the **History** title folds the chart and the totals away, so the session list takes the whole screen (handy with the phone held sideways); tap it again to bring them back.
A tapped day stays selected while folded, and each profile remembers whether it was folded.

### Totals

Under the chart (beside it with the phone held sideways), a table sums your sessions for the **day**, its **week** (Monday to Sunday, as in the calendar) and its **month**, for today or the day you tapped, and for **All time**:
- **Total**: how long you meditated.
- **On target**: time at or above the threshold, each session against its own target (a program's segments, or a threshold you moved, included).
  Sessions recorded before the app saved their scored metric count it on Meditation.
- **Best streak**: the longest unbroken run above the threshold in any one session of the period.

A period without sessions shows "–".

### Day Filter

In either view, tap a day (cell or bar) to list only its sessions and see its totals.
Tap it again, or **Show All**, to list every session and go back to today's totals.

### Session List

Each row shows:
- a colour mark for its score
- **date, start time and name**, e.g. "2026-09-26 14:30 - MindWave Mobile", or "2026-09-26 14:30 - Morning sit" once renamed (the date and time always show, in a day's list too)
- **score line**: the metric the session was scored on (the one that drove the feedback sound) with its average, the duration and the longest streak above the threshold, e.g. "Shamatha 72 · 25m 00s · Streak 4m 30s".
  A program session shows the program's name instead of an average, and a streak of 0 is left out.
  Sessions recorded before the app saved their scored metric show the average Shamatha and the duration ("Shamatha 50 · 15m 00s").
- **notes**: the first line of the session's notes, if any
- **pencil**: rename the session in place (you edit the name; the date and time stay)
- **trash**: delete it, after a confirmation

Long names and notes are cut with "…" to fit.
Tap a row to open the session.

**Export several sessions:** tap **Select** (right of the list's heading) to enter selection mode, tap rows to tick them (or **Select all**), then **Export N**.
It saves them as one **ZIP** with a CSV per session in `Documents/EEGMeditation/` (on desktop, the Documents folder in your home folder).
**Cancel** leaves selection mode.

**Delete several sessions:** in selection mode, **Delete N** deletes the chosen sessions after one confirmation that says how many and over which days.
It can't be undone.
The list keeps your place, and selection mode ends once they are deleted.

A session still running isn't listed in History; it appears there once it ends.
Deleting the session the Session screen still shows clears it from there too.

### Session Detail

Tapping a session opens it at once: its stats and notes are there straight away, and the band power and graphs show "Loading…" until their data is in.
Titled like its row, it shows Duration, **Metric**, **Average** and **Threshold** as the Session saved card does, then Time Above Threshold, Longest Streak and Mood Rating.
Sessions recorded before the app saved their scored metric show **Avg Shamatha** and **Threshold Used** in place of Metric, Average and Threshold.
Under the stats come **Try another threshold**, **Band Power (whole session)**, the notes, tags and mood, and three graph tabs (the Metrics legend marks the scored series with **»**):
- **Metrics**: all computed metrics; the dashed threshold line steps where the threshold changed (a moved slider, a program's segments)
- **Raw EEG**: a waveform synthesized from the stored band powers
- **Frequencies**: the band powers over time

The **|↔|** button in a graph's bottom-right corner shows the whole session on all three of its graphs (Raw EEG keeps only the session's last minute, so it shows that; a session over 3 hours shows its last 3);
tap it again (**→|←**) to go back to the window you had.
It stays on as you open other sessions, and pinching or the mouse wheel zooms on from there.
Zooming a session's graphs doesn't change the Session screen's, and the reverse.
Past an hour the time axis reads hours (1:15:00).

**Try another threshold** (under the stats) shows what Time Above Threshold and Longest Streak would have been at another threshold.
Move the slider (or −/+ by 5): both are recalculated from the session's own recorded data, and the Metrics graph's dashed line moves with it.
**Reset** goes back to the session as recorded; the line under the title says what that was ("Recorded at 70", or "70 › 85" when the threshold was moved during it).
One threshold applies to the whole session.
A **program** session gets one slider per segment instead, each titled with its number, metric and recorded target and followed by that segment's own time above threshold and streak.
The **Whole session** totals come after them; a streak running from one segment into the next counts there as one, as it did live.
Moving a segment's slider changes only that segment (and the totals) and only its part of the graph's line.
It's only a view: nothing about the session changes, and reopening it starts as recorded again.
The chevron right after its title folds it away (Reset stays beside it); each profile remembers that.

**Save Notes** saves the notes, tags and mood as the screen shows them ("Notes saved").
Leaving the session (**Back**, another tab, the app going to the background) saves what you changed, and only that, with the same "Notes saved": leaving without a change writes nothing, and it never rates a session you haven't rated.

**Band Power (whole session)** is a sortable table of each band's total power over the session: coloured bars scaled by each band's share of the total, plus Power and % columns, a quick read of where your brainwave energy was concentrated.
**Detailed / Grouped** switches between the 8 bands and 5 grouped ones (Alpha = Alpha 1 + Alpha 2, Beta = Beta 1 + Beta 2, Gamma = Gamma 1 + Gamma 2).
Each band's frequency range, as the headset measures it, is in a small line under its name:
Delta 0.5–2.75 Hz, Theta 3.5–6.75, Alpha 1 7.5–9.25, Alpha 2 10–11.75, Beta 1 13–16.75, Beta 2 18–29.75, Gamma 1 31–39.75, Gamma 2 41–49.75 Hz.
A grouped band shows the span of its two (Alpha 7.5–11.75, Beta 13–29.75, Gamma 31–49.75 Hz), though the headset leaves small gaps between them (9.25–10, 16.75–18 and 39.75–41 Hz).
Tap a column header to sort by it (tap again to reverse).
Each profile remembers the view and the sort.
The chevron right after the **Band Power** title folds the table away (tap it again to bring it back); each profile remembers whether it was folded.

**Export CSV** saves the session's data under a file name you can change (`session_<id>.csv`): on Android into `Documents/EEGMeditation/`, on desktop into a folder you pick.
Each row also says what it was scored on: `score_key` (the metric), `score_value` (its value) and `score_target` (the threshold in force); these are empty for sessions recorded before the app saved them.

---

## Settings

Settings is a list of sections: tap a section's header to open or close it.

### User Profile

- The current profile shows at the top.
- **Existing profiles** are listed above the name field: tap one to switch to it.
- Type a new name and tap **Create** to add a profile.
- If the name already exists, two buttons offer **Use existing 'X'** (switch to that profile) or **Change name** (back to the field).
  Names are unique and case-sensitive.
- Each profile has its own sessions, settings, programs and formulas.
  The **X** on a row deletes that profile, with all its sessions and settings, after a confirmation that says how many sessions go.
- Switching profiles is refused while a session runs or connects ("Session in progress"): the session keeps the settings it started with.
  Stop it first.
- Switching to another profile clears the last session from the Session screen (it stays in History); if its Session saved card is still open, it closes and keeps the notes you typed.

### Data Backup

Settings → **Data Backup** saves a copy of your sessions to a file and restores it later.

- **Backup database** saves your current settings, then writes a transaction-safe copy of the whole database (all profiles).
  The suggested file name carries the profile name and the date and time, e.g. `eeg_backup_Anna_2026-09-29_17-49.db`.
  You choose where: on Android in the system's save dialog (Downloads, Documents, a cloud drive...), on desktop in a file dialog.
  A **Backup saved** dialog confirms it.
- **Restore database**: pick a backup file.
  The app checks it (a SQLite file with `users` and `sessions` tables), asks you to confirm, then replaces the database and exits; relaunch it to see the restored history.

Before restoring, know that:
- Restore replaces the **entire database, all profiles** on this device, not just the current one, and can't be undone: use Backup first if you want to keep the current state.
- A backup holds only the database.
  **Custom sound files** (feedback, reward, timer) are referenced by their path and are **not** included, so on another device those paths may not resolve.

### Timer

The **Simple | Program** toggle at the top of Settings → Timer / Program picks the mode.
**Simple** mode is a single timer:
- **Enable Timer** turns it on or off.
- **Duration**: a slider from 1 to 120 minutes, with presets 5m, 10m, 15m, 20m, 30m, 1h, 1h30 and 2h.
- With the timer on, the session stops and is saved at the end, and the timer end sound plays.

**Timer End Sound** (both modes): its button picks **Default bell** or **Custom file...** (a file of your own, picked the same way as a custom feedback sound); the button then shows the file.
**Test** plays it.
While it rings, other apps' audio is lowered (a session with a feedback sound has already paused it).
If the app can't play the file, the timer ends with the default bell, and **Test** says so.

#### Session Program

In **Program** mode, Enable Timer and the duration give way to an editor of timed segments, run from top to bottom (a program always runs its own timer).
Each segment row has:

- **Min**: its length in minutes
- **Metric**: what drives the feedback sound and is scored in this segment: Shamatha, Meditation, NS Attention, NS Meditation or any formula saved in your custom-formula library
- **Target**: the segment's threshold (its part of the dashed line and of the time above target)
- **End cue**: the sound when the segment ends, **Chime** (default) or **Warble**
- **Feedback**: the segment's continuous sound: **Default** (the one set in Settings → Audio), **Rain**, **Tone** or **Custom file...**
- **X**: removes the row

**+ Add Segment** adds a row; **Total** under the rows sums their minutes.

**Saving and loading programs:**
Type a name and tap **Save** to store the segments in your library.
Names are unique: saving under a name that exists asks you to confirm the **overwrite**.
Saved programs are listed below the editor: tap one to **load** it (the app asks first when the current program has unsaved changes), or its **X** to **delete** it (after a confirmation).
**Loaded: \<name\>** at the top of the editor names the loaded program, and the name field holds that name, so **Save** overwrites it without retyping.
Each profile has its own library.

**Quick-loading from the Session screen:**
In Program mode the button next to **Start** shows a large **P**: the program's total length runs the timer.
Tap it, then **Program: \<name\>** (or **Programs…**), to pick a saved program without going to Settings; the loaded one is highlighted.
Loading a program switches to Program mode.

**During a session:**

- The timer runs for the program's total length; at its end the session stops with the timer end sound.
- The metrics graph shows the program's lines: each segment's metric or formula.
  Other lines are hidden while it runs (switch any back on in the series list; that isn't saved) and come back as they were when it stops.
  In Program mode the Session screen shows the program's lines before Start too.
- A formula with an error (one saved before Save checked it) can't run: its segments use Shamatha, and a message at the start names it.
- At each boundary the ending segment's end cue plays, and the target, the scored metric and the feedback sound switch to the next segment's.
  Time above target counts against each segment's own target.
- The legend marks the active segment's metric in bold with **»**.
- A stepped dashed target line follows each segment's target, on the live graph and in the session's detail.

### Device

- The connection status and mode.
- **Use Mock Data**: simulated EEG (demo mode); untick it for a real headset.
- **Scan Paired Devices** lists the paired Bluetooth devices, each with its name and address: every MindWave has the same Bluetooth name.
- Tap a device to use it; this also turns Mock Data off.
  The row of the headset in use is filled, and the connected one shows a Bluetooth sign (with Mock Data on, none is marked).
  You can't switch headsets while a session runs or connects.
- **Name a headset**: tap the pencil on its row, type a name and tap **Save** (or Enter).
  The name is the same for every profile on the phone and shows in the device status, on the Session screen and in the names of new sessions.
  Leave it blank to go back to the Bluetooth name.
- **Locked-screen sessions** (Android): whether battery optimisation applies to the app, with the buttons that open the phone's settings (see Locked-screen sessions above).

### Threshold

- A slider from 20 to 180 (−/+ by 5), with presets 50, 80, 100, 130 and 160.
- It sets the dashed line on the graphs, the time above threshold and the feedback sound's target.
- Moving it during a session changes the threshold once the slider stays put for half a second (a drag is one change, at the value it stops on).
  The feedback sound, Time Above Threshold, Longest Streak and the **SHAMATHA** badge follow it, and the graph's dashed line steps at the change, live and later in History.
  The session keeps each threshold it ran with.
- With no session running, a new threshold clears the last session from the Session screen (its graphs, numbers, timer and state; it stays in History) and shows the new line.
- During a program session the segments set the targets, so the threshold is locked until it stops: the slider, −/+ and presets are dimmed and don't move, and touching them shows **Session in progress** with the reason.
- **Time above threshold** and **Longest streak** are measured on the **Audio control metric** below, the one that drives the feedback sound; the live graph's legend marks it with **»** when its line is shown.
  Each session records the metric it was scored on; sessions recorded before the app did that were measured on Meditation.
- **Audio control metric**: Shamatha Score, NS Meditation, NS Attention or Custom Formula, its slot picked with the **1**, **2**, **3** buttons.
  If that slot has no valid formula, Shamatha drives the sound.
  While a session runs or connects, this choice and the formula in the selected slot are locked: a session is scored on one metric from start to stop.
  The other formula slots and the threshold stay editable.
  A program session, scored on its segments' metrics, leaves the metric and the slots free (its threshold is locked, see above).

### Audio

- **Feedback sound** (below the threshold): its button opens a picker:
  - **Off**: no sound below the threshold
  - **Rain** (default): rain / white noise
  - **Tone**: a built-in harmonic drone (a note and its fifth); no file needed
  - **Custom file...**: an audio file of your own (wav, mp3, ogg, flac, m4a), picked in a file browser (on Android, the system's file picker); the button then shows it.
    On Android the app keeps its own copy, so moving or deleting the original doesn't affect it.
    The file loops, its volume following the metric as Rain's does.

  This sound is loudest when you are far below the threshold and fades to silence as you reach it.
- **Reward sound (above threshold)**: a second sound, **silent until you cross the threshold**, that then fades in and grows the further above it you go (full at +30 points).
  Default **Off**.
  It offers Off, Rain, Tone and Custom file... as above, plus **Crickets**:
  a soft chirp about once every 10 seconds instead of a continuous sound, a "still here, doing well" cue while you hold above the threshold; like the other reward sounds, it grows louder the higher you go.

  Use it for a positive cue that builds as you deepen.
  The two sounds cross-fade at the threshold; set either to **Off** for silence on that side.
- **Test Audio** plays the reward sound (Crickets included), then a feedback sweep, the bell, the chime and the warble.
  It is refused during a session (stop it first), and starting a session ends a test still playing.
- **Enable Sinking Alert Bell**, **Enable Distraction Chime** and **Audio alert on disconnect / signal loss** turn those alerts on (all off by default).
- The volume rises on a log curve: quickly at first, then flattening (max 0.3).

### Display

- **Text size**: **Normal**, **Large** (125 %) or **Larger** (150 %), for every text in the app; it applies at once.
- **Scored line colours**: how the line of the metric you train on is coloured on the graphs (the Session screen's, and a session's in History).
  **Mono** gives it its own colour; a gradient colours it by its value from 0 to 200: **Blue › Red** (the default), **Viridis**, **Plasma**, **Turbo** or **Red › Green**.
  A gradient keeps every part of the line readable on the current theme.
  It applies at once.
- **Line Width**: a slider from 0.5 to 4.0, with presets.
- **Rotate Screen**: each tap turns the screen 90° (0, 90, 180, 270).
- **Marker Hotkey** (desktop): the key that places a marker.

### Custom Formula

Three slots (**Formula 1**, **2** and **3**), each with:

- **name**: the label of its series on the graphs and in a session's detail
- **formula**: a Python-style expression of band powers, normalized bands, computed metrics and math functions, with `avg(expr, N)` for a moving average
- **Apply**: evaluates it; a status line shows the current value or the error, and a formula with an error leaves the slot as it was
- **Save**: stores it in your formula library under the slot's name; a formula with an error isn't saved, and the status line shows the error;
  a name already in the library asks before overwriting that formula, as saving a program does

**Saved Formulas** below the slots is your library: tap one to put it into the first empty slot (Formula 1 when all three are in use), or its **X** to delete it (after a confirmation).
**Export to .txt** writes the library's formulas, one per line, to `Documents/EEGMeditation/formulas_user_<n>.txt` (on a computer, `~/Documents/EEGMeditation/`), and a message says where.

To put a saved formula into a slot without opening Settings, tap **Choose…** on that slot's row in the live metrics graph's series list.
A saved formula with an error (one saved before Save checked it) can't go into a slot: the slot stays as it was, and a message says why.
Settings → Threshold picks which slot drives the feedback sound.

All three formula series share one Y-axis (0–200, reference line at 100), so keep their values in a range comparable to the other metrics.

A session's detail **replays the formulas that were active during it**: it recomputes them from the stored band powers, so you see the names and values you saw live.

### Theme

Four colour themes: **Dark Blue** (default), **Dark Green**, **Light Cream** and **Light Green**.
A change applies at once.

### Help & Troubleshooting

The in-app help: quick start, connection troubleshooting, supported devices, sensor tips and more.
On Android it shows in the phone's language: Ukrainian on a phone set to Ukrainian, English otherwise.
On a computer it follows the `LANGUAGE` or `LANG` setting (Linux); the Windows and macOS builds show English.

---

## Connection Troubleshooting

If your headset won't connect:

1. **Check the battery**: the most common cause of connection problems.
   Replace the AAA battery if the headset connects but no EEG data comes (see 7).
   NiMH rechargeables (1.2 V) are recommended; ignore the red LED, which is calibrated for 1.5 V alkaline.
   Avoid 1.5 V Li-ion rechargeables: their voltage regulator masks a low charge and causes silent failures.
2. **Check Bluetooth**: on, on your phone or computer, with the headset paired in the system's Bluetooth settings.
3. **Clean the sensors**: wipe the forehead sensor and ear clip with an alcohol pad.
4. **Reset the pairing**: remove the headset from the Bluetooth settings, then pair it again (this fixes most issues).
5. **Close other Bluetooth apps**: only one app at a time can hold the RFCOMM connection.
6. **Restart the headset**: turn it off, wait 5 seconds, turn it on.
7. **Connected but not streaming** ("No EEG data received"): the headset connects but no EEG data comes.
   This almost always means a weak battery: the Bluetooth radio needs less power than the EEG chip, so the headset can connect while its EEG processor can't start.
   Replace the battery.
8. **Test with the manufacturer's app**: if it can't connect either, the headset may be faulty.

### Supported Devices

Any headset with a NeuroSky TGAM module and Bluetooth Classic:
- NeuroSky MindWave Mobile / Mobile 2
- BrainLink SE / Lite / Pro
- MindLink Brainwave
- Sichiray headsets

**Note:** Bluetooth Classic (RFCOMM) only; BLE headsets are not supported.

### Sensor Contact Tips

For good EEG signal quality:
- Clean your forehead (remove oil and sweat).
- Wipe the sensor pads with alcohol.
- Press the sensor firmly against the skin.
- Keep hair from under the sensor.
- While connecting, the overlay shows the sensor's contact; its quality number runs from 0 (perfect) to 200 (no contact).

---

## Tips

- **Try demo mode first** to learn the app before connecting a real headset.
- **Set your threshold** by experience: beginners 40–60, experienced 80–130.
- **Use markers** to note significant moments during practice.
- **Write quick notes** on the Session saved card right after a session.
- **Review the calendar** to track your consistency over weeks.
- **Try custom formulas** to experiment with other metrics.
- On Android the screen stays on during a session.
- All settings are saved per profile and restored on the next launch.
