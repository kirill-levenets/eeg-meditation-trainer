# EEG Meditation Trainer - User Manual

> **Disclaimer:** This software is for educational and personal exploration purposes only. It is not a medical device and must not be used for medical diagnosis or treatment. EEG data from consumer-grade headsets is inherently noisy. Use at your own risk.

## Getting Started

### First Launch

When you open the app, you'll see the **Profile** screen (the first tab).
Before you can start a session, you need to create a user profile.

### Create a User

1. Type your name in the text field
2. Tap **Create User**
3. Your name appears in the user list - tap it to make it active
4. The current active user is shown at the top: "Current: YourName"

You can create multiple profiles (e.g. for family members). Each user has their own sessions, settings, and saved formulas. Tap any user name in the list to switch. Tap **Show All Users** to view sessions from everyone.

### Navigation

The tab bar at the top has 7 tabs:

**Profile** | **Session** | **Raw EEG** | **Settings** | **Timer** | **Diary** | **Analytics**

Tap the hamburger button (**&#9776;**) on the left to hide/show the tab bar (useful on small screens).

The **Diary** tab is disabled until you select a user.

---

## Settings

Go to the **Settings** tab to configure the app before your first session.

### Device

By default the app uses **Mock Data** (simulated EEG for testing). To use a real NeuroSky MindWave Mobile 2:

1. Make sure the headset is paired with your device via Bluetooth
2. Uncheck **Use Mock Data**
3. Tap **Scan Paired Devices**
4. Tap your MindWave in the device list
5. The status will show "Selected: MindWave Mobile"

On Linux you can also use the `--serial` command line flag to read from a serial port.

### Meditation Threshold

The threshold slider (20-100) sets the meditation score level used for:
- The dashed line on the session graph
- "Time above threshold" statistics
- Audio feedback target

### Audio Control Metric

Choose which metric drives the white noise volume:
- **Meditation Score** (default) - the main shamatha formula
- **Shamatha Score** - same as meditation in current version
- **NS Meditation** - NeuroSky's built-in meditation value
- **NS Attention** - NeuroSky's built-in attention value
- **Custom Formula** - your own formula (if defined)

### Audio Feedback

The app provides real-time audio feedback during sessions:

- **White noise** - volume decreases as your selected metric increases (quieter = deeper meditation). At threshold level, noise goes silent.
- **Sinking alert bell** - a tingsha bell sound when drowsiness (theta+delta) gets too high. Enable/disable with the checkbox.
- **Subtle distraction chime** - a gentle chime when short-term meditation score variance is high (mind wavering). Enable/disable with the checkbox.
- **Disconnect alert** - warble sound when the headset loses connection. Enable/disable with the checkbox.

Tap **Test Audio** to hear a sample.

### Display

- **Line Width** (0.5-4.0) - adjust graph line thickness for your screen size
- **Rotate Screen** - cycle through 0/90/180/270 degree rotation

### Graph Metrics

Toggle which metrics are shown on the session graph:
- Meditation Score, Shamatha Score, Distraction, Sinking, Subtle Distraction, NS Attention, NS Meditation
- **Show Custom Formula** - display your custom formula as an extra line on the graph

### Custom Formula

Enter a Python-style math expression to track as an extra metric. Examples:

```
(alpha1 + alpha2) / (beta1 + beta2 + 1)
sqrt(alpha_norm) * 100
avg(meditation_score, 20) - avg(distraction, 20)
```

Available variables:
- **Raw bands:** `alpha1 alpha2 beta1 beta2 gamma1 gamma2 theta delta`
- **Combined:** `alpha beta gamma`
- **Sqrt-relative:** `s_alpha1 s_alpha2 s_beta1 s_beta2 s_theta s_delta`
- **Normalized:** `alpha_norm beta_norm gamma_norm theta_norm delta_norm`
- **Metrics:** `meditation_score shamatha_score distraction sinking subtle_distraction stability calmness native_attention native_meditation`
- **Functions:** `sqrt abs log log10 exp pow min max sin cos tanh`
- **Windowed average:** `avg(expr, N)` - mean of last N ticks (N=1..600; at 2Hz: 10=5s, 60=30s)

Tap **Apply** to activate, **Save** to store for later. Saved formulas appear in a list below - tap to load, X to delete.

---

## Timer

Go to the **Timer** tab to set a session duration.

1. Check **Enable Timer**
2. Set duration with the slider or tap a preset (5, 10, 15, 20, 30, 45, 60 min)
3. Optionally set a custom end sound: tap **Browse** to pick an audio file, or leave empty for the default bell
4. Tap **Test Sound** to preview

When enabled, the timer starts automatically when you begin a session. The large countdown display shows remaining time. When it reaches 00:00, the session stops automatically and plays the end sound.

---

## Running a Session

Go to the **Session** tab.

### Start

Tap **Start**. If using a real device, the app will show "Connecting..." until the headset sends data. With mock data, the session starts immediately.

The header shows:
- Device status (left) - connected/disconnected indicator
- Session start time and elapsed duration (center)
- Current state (right) - color-coded: green=Stable Focus, yellow=Subtle Distraction, red=Gross Distraction, orange=Sinking

### During the Session

The graph shows real-time metrics scrolling left-to-right:
- **Blue** - Meditation Score
- **Green** - Shamatha Score
- **Red** - Distraction
- **Orange** - Sinking
- **Yellow** - Subtle Distraction
- **Purple** - NS Attention
- **Cyan** - NS Meditation
- **Pink** - Custom Formula (if enabled)

The X-axis shows relative time (minutes:seconds) and wall-clock time below it. Horizontal grid lines are at every 20 units. The dashed horizontal line marks your threshold.

Below the graph, six stat boxes show current values.

**Scrolling and zooming the graph:**
- Drag left/right to scroll through history
- Mouse wheel (desktop) or pinch gesture (Android) to zoom in/out

### Markers

Tap **Mark** during a session to place a vertical magenta line on the graph at the current moment. Use this to mark events (e.g. "heard a noise", "felt distracted", "deep moment"). Markers are saved with the session and visible in the diary.

### Pause / Resume

Tap **Pause** to temporarily stop recording. The button changes to **Resume** - tap it to continue. Paused time is not counted in session duration.

### Stop

Tap **Stop** to end the session. A dialog appears with three options:
- **Save** - save all session data to the database
- **Discard** - delete the session (including any data already flushed to DB)
- **Cancel** - dismiss the dialog and resume the session

---

## Raw EEG

Go to the **Raw EEG** tab during a session to see detailed signal data.

Two synchronized graphs:
- **Top: Raw EEG Signal** - the actual electrical waveform at 512Hz. This is what the headset measures - a composite of all brain wave frequencies.
- **Bottom: Frequency Bands** - five bands extracted by the headset: Alpha (green), Beta (yellow), Gamma (red), Theta (blue), Delta (purple)

Drag either graph to scroll - both stay synced. Zoom with mouse wheel or pinch.

---

## Diary

Go to the **Diary** tab to review past sessions (requires a selected user).

### Session List

The top half shows all sessions for the current user, newest first. Each entry shows:
session number, date/time, duration, and average Shamatha score. Tap to select.

### Session Details

The bottom half shows details of the selected session:

- **Statistics** - duration, averages, time above threshold, longest streak, mood
- **Notes** - free text field for session reflections
- **Tags** - comma-separated labels (e.g. "morning, calm, focused")
- **Mood** - slider from 1 to 5
- **Save Notes** - persist your notes, tags, and mood rating

### Session Graphs

Three tabs below the notes section:
- **Metrics** - all computed metrics (same as session graph but for the saved data)
- **Raw EEG** - synthesized waveform from stored band powers
- **Frequencies** - band power chart (Alpha, Beta, Gamma, Theta, Delta)

All three graphs show markers (magenta vertical lines) if any were placed during the session. Drag to scroll, scroll wheel/pinch to zoom.

### Export

Tap **Export CSV** to save session data as a CSV file. A file dialog opens where you can choose the folder and filename. The CSV includes all raw band powers, computed metrics, timestamps, and a marker column (1 = marker present).

### Rename / Delete

- Type a new name and tap **Rename** to change the session title
- Tap **Delete Session** and confirm to permanently remove a session

---

## Analytics

Go to the **Analytics** tab for long-term trends.

### Summary Cards

Four cards at the top show overall statistics:
- **Sessions** - total number of sessions
- **Total Min** - total meditation time in minutes
- **Avg Shamatha** - average shamatha score across all sessions
- **Streak** - current daily practice streak

### Trend Chart

Tap **Daily**, **Weekly**, or **Monthly** to view a bar chart of average Shamatha scores over time. Below the chart, each period shows: date range, session count, average Shamatha, and total duration.

### Storage Info

At the bottom: database file size, number of sessions, total data points, and number of users.

---

## Tips

- **Start with mock data** to learn the interface before connecting a real headset
- **Set your threshold** based on your experience level - beginners may want 40-50, experienced meditators 70-80
- **Use markers** to note significant moments during practice for later review
- **Review the diary** after each session - write notes while the experience is fresh
- **Track trends** in analytics to see your progress over weeks and months
- **Try custom formulas** to experiment with different metrics (e.g. pure alpha/beta ratio)
- **Enable the timer** for consistent session lengths
- On Android, the screen stays on during sessions (wake lock)
- All settings are saved per-user and restored on next launch