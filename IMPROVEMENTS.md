# EEG Meditation Trainer — Improvement Roadmap

Organized by priority tier. Each section is a standalone GitHub issue candidate.

---

## Recently Completed (v1.1.0)

The following items from this roadmap were implemented in the UI redesign:

- **2.1 Logarithmic Audio Volume Curve** — DONE. Log curve (k=9), MAX_VOLUME=0.3, flattens near max.
- **2.5 Session Warm-up and Cool-down (partial)** — Session end summary card with stats + quick notes implemented. Warm-up phase not yet.
- **4.1 Simplified Navigation** — DONE. 3-tab bottom nav (Session / History / Settings). Raw EEG merged into Session as toggle. Timer and Profile moved into Settings.
- **4.2 Onboarding Flow** — DONE. 2-step first-run wizard (create profile → connect device or skip).
- **4.5 Dark/Light Theme and Visual Identity** — DONE. 4 themes (Dark Blue, Dark Green, Light Cream, Light Green), theme system with live refresh, app icon + presplash, Material Design Icons font, custom styled widgets.
- **4.6 Settings Organization** — DONE. ThemedAccordion with collapsible sections, preset buttons under sliders.
- **Calendar Heatmap** — New feature (not in original roadmap). GitHub-style history view colored by daily avg shamatha.
- **Auto-connect** — Device auto-detection on Start, connection overlay with progress + timeout.
- **macOS support** — New CI build target.

---

## Tier 1: Data Collection & Formula Research (Core Mission)

### 1.1 Labeled Marker System

**Current state:** Markers are binary (0/1) with no metadata.

**Problem:** When collecting datasets for formula development, users need to label *what* they experienced — "distraction spike", "deep calm onset", "external noise", "posture shift". Without labels, marker data requires separate note-taking and manual correlation.

**Proposal:**
- Add marker categories: predefined labels (e.g., "Distraction", "Sinking", "Deep Focus", "Artifact", "External") + custom text
- Quick-access: long-press Mark button opens label picker, short-press uses last-used label
- Store in DB: add `marker_label TEXT` and `marker_intensity INTEGER` (1-3) columns to metrics table
- Display labeled markers with color-coded vertical lines on graphs (different color per label)
- Filter sessions by marker labels in Diary

**Why it matters:** Labeled markers transform raw timeseries into supervised training data. Users can mark subjective states in real-time, then build formulas that predict those states from band powers.

---

### 1.2 Formula Backtesting on Historical Sessions

**Current state:** Formulas can only be evaluated live during a session, or partially recomputed during CSV export (without windowed history).

**Problem:** Formula development requires fast iteration — write formula, test against known data, observe results, adjust. Currently users must run a new session every time they want to test a formula change.

**Proposal:**
- Add "Test Formula" button in Diary session detail view
- Replays stored metrics through CustomFormulaEvaluator with full `avg()` history support
- Overlays formula result on the session graph alongside original metrics
- Shows correlation stats: how well the formula tracks markers, shamatha_score, or native values
- Support testing multiple formulas simultaneously (compare up to 3 overlaid)

**Why it matters:** This is the single biggest accelerator for formula research. Reduces the feedback loop from "meditate 20 min → check result" to "click test → see result in 2 seconds".

---

### 1.3 Expose Temporal Derivatives and Context Variables

**Current state:** Formulas can reference current-tick values and `avg(expr, N)` windowed averages. No access to rates of change, session position, or marker context.

**Problem:** Many useful meditation patterns are temporal — "alpha is rising", "beta dropped suddenly", "10 minutes into session fatigue increases theta". These can't be expressed with current variables.

**Proposal — new formula variables:**
- `elapsed` — seconds since session start
- `tick` — current tick number (0-based)
- `d_meditation_score` (and `d_` prefix for all metrics) — delta from previous tick
- `marker_age` — ticks since last marker (-1 if none placed yet)
- `signal_quality` — device signal quality (0=good, 200=poor for NeuroSky)
- `powerline_noise` — 1.0 if 50/60Hz noise detected, 0.0 otherwise

**Proposal — new windowed functions:**
- `wmin(expr, N)` — minimum over last N ticks
- `wmax(expr, N)` — maximum over last N ticks
- `wstd(expr, N)` — standard deviation over last N ticks
- `slope(expr, N)` — linear regression slope over last N ticks (trend direction)

**Why it matters:** Temporal features are critical for distinguishing meditation states. A formula like `slope(alpha_norm, 20) > 0.01 and elapsed > 300` detects "alpha increasing after 5-minute warm-up" — impossible to express today.

---

### 1.4 Session Comparison & Overlay

**Current state:** Diary shows one session at a time. No way to compare sessions side-by-side.

**Problem:** Formula calibration requires comparing how a formula behaves across different sessions — "does my formula score high in good sessions and low in bad ones?" Currently requires CSV export and external tooling.

**Proposal:**
- Add multi-select in Diary session list (checkboxes, max 3-4 sessions)
- "Compare" button opens overlay view: all selected sessions' metrics plotted on the same time axis
- Time-align by session start (or by first marker)
- Show per-session stats table below the graph
- Optionally overlay custom formula results from backtesting

**Why it matters:** Visual comparison across sessions is how researchers spot patterns. "My shamatha is always low in evening sessions" or "this formula tracks well in sessions with many markers but not calm ones."

---

### 1.5 Formula Correlation Report

**Current state:** No automated way to evaluate how well a formula predicts subjective experience.

**Problem:** After placing labeled markers during sessions, users need to manually inspect whether their formula values align with marked states. This is tedious and imprecise.

**Proposal:**
- After backtesting a formula on a session (see 1.2), generate a correlation report:
  - Mean formula value at marker points vs. non-marker points
  - Mean formula value per marker label (if labeled markers exist)
  - Pearson correlation with shamatha_score, native_meditation, native_attention
  - Time-to-detect: average delay between marker placement and formula threshold crossing
- Show as a summary card below the backtest graph
- Allow running across multiple sessions at once for aggregate stats

**Why it matters:** Quantitative formula evaluation replaces guesswork. Users can objectively compare "formula A detects distraction 2 seconds faster than formula B."

---

### 1.6 Programmable Markers (Auto-Marker from Formula)

**Current state:** Markers can only be placed manually (button, hotkey, or screen tap).

**Problem:** Some patterns are too fast or subtle for manual marking. Users want to auto-mark when a condition is met — e.g., "mark every time beta spikes above 2x its 30-second average."

**Proposal:**
- Add "Auto-Marker Formula" field in Settings (separate from display formula)
- When the expression evaluates to > 0, a marker is placed (with configurable cooldown to prevent flooding)
- Auto-markers stored with a distinct label (e.g., "auto: beta_spike") to differentiate from manual
- Visible in diary review alongside manual markers

**Why it matters:** Enables automated event detection for dataset annotation. Researchers can run a session and have both their manual subjective markers AND formula-detected events recorded simultaneously.

---

### 1.7 Export Enhancements for External Analysis

**Current state:** CSV export includes all columns but loses windowed function state. Export path is buried in Diary detail view. No batch export.

**Problem:** Researchers using Python/R/MATLAB for analysis need easy access to clean data. Current export requires clicking through each session individually.

**Proposal:**
- **Batch export:** Select multiple sessions in Diary, export all as separate CSVs in one zip, or as a single merged CSV with session_id column
- **Export with markers metadata:** Include marker_label column (when labeled markers are implemented)
- **Export session metadata header:** First lines of CSV include session date, duration, threshold, user, tags as comments
- **Quick export path:** Add export button to session list (not just detail view)
- **EDF+ export option:** Standard EEG format readable by MNE-Python, EEGLAB, BrainVision Analyzer
- **Clipboard copy:** Small sessions can be copied as tab-separated values for quick paste into spreadsheets

**Why it matters:** The faster data gets into analysis tools, the faster formulas get developed. Every extra click in the export flow is friction that slows research.

---

### 1.8 Dataset Tagging and Filtering

**Current state:** Sessions have free-text tags and notes. No structured filtering or grouping.

**Problem:** With 50+ sessions, finding "all sessions where I was drowsy" or "morning sessions from last month" requires scrolling through the entire list.

**Proposal:**
- Structured tag system with autocomplete from previously used tags
- Filter bar at top of Diary: filter by tag, date range, duration range, min/max shamatha score
- Sort by any stat column (duration, avg_shamatha, time_above_threshold)
- "Dataset" concept: save a filter as a named dataset (e.g., "Good Focus Sessions", "Drowsy Afternoons") for repeated analysis
- Show dataset aggregate stats (mean shamatha across all sessions in dataset)

**Why it matters:** Formula development requires curated datasets. "Test this formula against all my 'deep focus' sessions" is a fundamental research operation that currently requires manual session-by-session selection.

---

## Tier 1B: State Detection & Auto-Tagging System

This section extends the core data collection mission into automatic state recognition — turning raw EEG + user markers into personalized state detectors.

### Hardware Reality Check (NeuroSky MindWave Mobile 2)

Single dry electrode at FP1 (forehead midline), 8 frequency bands at 1Hz, consumer-grade.

**Scientifically validated at single frontal electrode:**
| State | Biomarker | Confidence |
|-------|-----------|------------|
| Arousal level | beta/alpha ratio | High |
| Drowsiness onset | (theta+delta)/(alpha+beta) rising | High |
| Cognitive load | frontal theta increase | Medium-High |
| Stress/rumination | elevated beta2+gamma relative to alpha | Medium |
| Mind-wandering | alpha power variance spikes | Medium |
| Relaxation depth | alpha dominance, low beta | High |
| Focus quality trend | theta/beta ratio (TBR) | Medium |

**NOT possible with single midline electrode:**
| State | Why Not |
|-------|---------|
| Depression screening | Requires Frontal Alpha Asymmetry (FAA) = two electrodes at F3/F4, not midline FP1 |
| Specific emotion classification | Requires spatial patterns across 4+ channels |
| Clinical ADHD diagnosis | TBR needs normative database + Cz electrode + clinical protocol |
| Any clinical diagnosis | Consumer hardware, no medical certification |

**The key insight:** Generic biomarkers from literature are population averages. EEG patterns are highly individual. The app's real power is helping users discover **personalized** state signatures through labeled data collection + formula iteration. A user's personal "stress detector" calibrated against 50 self-labeled "stressed" markers will outperform any generic formula.

---

### 1B.1 State Profile System (Predefined + Custom States)

**Current state:** The app classifies into 5 hardcoded states (Stable Focus, Gross Distraction, Sinking, Subtle Distraction, Neutral) based on fixed sigmoid thresholds.

**Problem:** These states only describe meditation quality. Users also want to track arousal, stress, drowsiness, cognitive load — states relevant to formula research and personal well-being.

**Proposal:**
- Introduce "State Profiles" — named collections of detection rules, each with:
  - Name and description (e.g., "Drowsy", "Anxious", "Flow State")
  - Detection formula (uses the existing custom formula syntax)
  - Threshold (above which the state is considered active)
  - Color for graph display
  - Optional audio/haptic alert configuration

- **Built-in profiles** based on established EEG biomarkers:
  ```
  Drowsiness:    (theta_norm + delta_norm) / (alpha_norm + beta_norm + 0.01) > 1.5
  High Arousal:  (beta_norm + gamma_norm) / (alpha_norm + 0.01) > 2.0
  Deep Relaxation: alpha_norm / (beta_norm + gamma_norm + 0.01) > 3.0
  Cognitive Load: theta_norm > 0.35 and beta_norm > 0.2
  Mind Wandering: wstd(alpha_norm, 20) > 0.08
  Stress:        (beta2 + gamma1) / (alpha1 + alpha2 + 1) > 1.8
  ```

- **Custom profiles** — users create their own using the formula builder
- Profiles stored per-user in DB, multiple can be active simultaneously
- Active state profiles shown as colored bands/regions on the session graph (not just lines)
- State transitions logged in metrics table for analysis

**Why it matters:** This transforms the app from "meditation scorer" into "personal brain state monitor." The built-in profiles give immediate value; custom profiles enable open-ended research.

---

### 1B.2 Personalized State Calibration Workflow

**Problem:** Generic biomarker thresholds (e.g., "drowsy when theta/alpha > 1.5") don't account for individual EEG baseline differences. One person's resting theta might be another's active theta.

**Proposal — Calibration Session mode:**
1. User starts a "Calibration Session" (new session type)
2. App prompts a sequence of brief states (60-90 seconds each):
   - "Relax with eyes closed" → records baseline alpha/theta
   - "Count backwards from 100 by 7s" → records cognitive load pattern
   - "Recall a stressful situation" → records stress/arousal pattern
   - "Let your mind wander freely" → records mind-wandering pattern
   - "Focus on your breath" → records focused attention pattern
3. After calibration, compute **personal baselines** per state:
   - Mean and std of each band ratio during each prompted state
   - Store as calibration profile in DB
4. Auto-adjust state detection thresholds to personal baselines:
   - "Drowsy" triggers when theta/alpha is >1.5 std above YOUR relaxed baseline
   - Not a hardcoded population average
5. Calibration can be re-run periodically (brain patterns shift over months)

**Technical implementation:**
- New `calibration` session type flag in sessions table
- Calibration data stored as JSON blob: `{state_name: {band_means: {}, band_stds: {}}}`
- State profiles reference calibration: `threshold = calibration.stress.mean + 1.5 * calibration.stress.std`
- Falls back to generic thresholds if no calibration exists

**Why it matters:** This is the difference between "your theta/beta ratio is 2.1" (meaningless to most users) and "your brain looks like it does when you told us you were stressed" (immediately actionable).

---

### 1B.3 Auto-State Tagger (Real-Time + Retrospective)

**Current state:** Auto-markers (proposed in 1.6) trigger from a single formula. No concept of multi-state simultaneous detection.

**Problem:** Users want the app to continuously tag what state it thinks they're in — not just "meditation good/bad" but a richer picture: "focused for 3 min, then drowsy for 30s, then stressed for 1 min, then back to focus."

**Proposal:**
- Run all active State Profiles (see 1B.1) in parallel during a session
- Each tick, evaluate all profile formulas and record which states are active
- Store as a **state timeline** in the metrics table: new column `detected_states TEXT` (comma-separated active state names per tick)
- Display as a **colored state bar** below the main graph:
  ```
  |████ Focus ████|██ Drowsy ██|████████ Focus ████████|█ Stress █|
  0:00           3:15        4:00                     8:30      9:15
  ```
- State transitions generate auto-markers with the state name as label
- Post-session: show state distribution pie chart (% time in each state)
- In Diary: state timeline visible alongside metrics graph for retrospective analysis

**Retrospective mode:**
- Apply state profiles to historical sessions (like formula backtesting)
- Re-analyze old sessions with new/improved state detectors
- Compare: "How does my new stress detector perform vs the old one on the same data?"

**Why it matters:** This is the core "emotion/state detector" the user is asking about. It won't diagnose clinical conditions, but it creates a continuous personal state diary backed by EEG data, which is genuinely useful for self-awareness and research.

---

### 1B.4 State-Marker Correlation Discovery

**Problem:** Users place manual markers ("I feel drowsy", "distracted by noise") but don't know which EEG bands actually shifted at that moment. The connection between subjective experience and brain data is opaque.

**Proposal — "What happened at this marker?" analysis:**
- For each labeled marker, compute a **marker signature**:
  - Average band values in 10-second window around the marker
  - Compare to session baseline (mean of non-marked periods)
  - Show: "At your 'drowsy' markers: theta +45%, alpha -20%, delta +60% vs baseline"
  - Visualize as a radar chart (8 bands, marker vs baseline)

- **Cross-marker pattern discovery:**
  - Aggregate all markers of the same label across multiple sessions
  - Show: "Across 23 'stressed' markers in 8 sessions, beta2 is consistently 2.1x baseline"
  - Suggest formula: "Based on your data, a stress detector could be: `beta2 / (alpha1 + 1) > 1.8`"
  - One-click to create a State Profile from the discovered pattern

- **Marker prediction accuracy:**
  - After creating a state profile from marker data, test it:
  - "This formula would have detected 18 of your 23 stress markers (78%), with 4 false positives"
  - Precision/recall metrics for the state detector

**Why it matters:** This closes the loop from "I marked something subjective" to "here's the objective EEG signature" to "here's a formula that detects it automatically." This is the research workflow that makes formula development tractable for non-DSP-experts.

---

### 1B.5 Attention/Focus Quality Index (ADHD Self-Monitoring)

**Disclaimer:** This is NOT a diagnostic tool. It tracks personal trends over time for self-awareness.

**Rationale:** Theta/Beta Ratio (TBR) is the most studied single-channel EEG biomarker for attentional performance. While clinical ADHD diagnosis requires normative databases and clinical protocols, **self-monitoring TBR trends** is well within consumer EEG capability. Users with ADHD who are on medication or trying behavioral interventions want to track: "Is my focus improving this week vs last week?"

**Proposal:**
- Add a built-in "Focus Quality Index" state profile:
  ```
  focus_quality = 100 - min(100, (theta_norm / (beta_norm + 0.01)) * 25)
  ```
  (Inverse TBR, scaled to 0-100 where 100 = best focus)
- Show as an optional metric line on the session graph
- Track in Analytics: daily/weekly trend of average Focus Quality Index
- Compare across sessions: "Your focus quality is 15% better on morning sessions"
- Allow users to correlate with external factors (medication, sleep, caffeine) via session tags

**What this is NOT:**
- Not a diagnosis
- Not compared to any normative database
- Not a substitute for clinical EEG
- Clearly labeled: "Personal Focus Trend — not a medical assessment"

**Why it matters:** Many users interested in EEG meditation training also have attention challenges. Giving them a meaningful, trackable focus metric (with clear disclaimers) adds significant value without overstepping medical boundaries.

---

### 1B.6 Drowsiness/Alertness Monitor

**Rationale:** Theta+delta rising relative to alpha+beta is one of the most reliable single-channel EEG findings across all of sleep research. A meditator falling into torpor (sinking) vs maintaining alert awareness is exactly this distinction.

**Proposal:**
- Built-in "Alertness Index":
  ```
  alertness = 100 * (alpha_norm + beta_norm) / (theta_norm + delta_norm + alpha_norm + beta_norm + 0.01)
  ```
- Real-time alertness bar (green when alert, orange when drifting, red when drowsy)
- Configurable alert: gentle audio cue when alertness drops below personal threshold
- This refines the existing "sinking" metric with a continuous index rather than binary sigmoid
- Track alertness curve shape: "You typically get drowsy at minute 12 of your sessions"

**Why it matters:** For Shamatha meditation specifically, the distinction between genuine meditative absorption and dullness/torpor is the central training challenge. A robust alertness monitor directly addresses this.

---

### 1B.7 Stress/Relaxation Tracker with Session Context

**Rationale:** High-frequency beta activity (beta2, gamma) at frontal sites correlates with anxiety and rumination in numerous studies. Alpha dominance correlates with relaxation. While this doesn't diagnose anxiety disorders, tracking the ratio over time provides self-awareness.

**Proposal:**
- Built-in "Calm/Stress Index":
  ```
  calm_stress = 50 + 50 * tanh(2 * (alpha_norm - (beta2 + gamma_norm)) / (alpha_norm + beta2 + gamma_norm + 0.01))
  ```
  (Centered at 50: >50 = calm side, <50 = stress side)
- Pre-session prompt (optional): "How are you feeling? [1-5 calm to stressed]"
- Post-session: compare subjective rating vs EEG-measured calm/stress index
- Over time: "Your self-reported stress correlates 0.72 with your EEG stress index"
- Track: does meditation reduce your stress index from session start to end?

**Why it matters:** Connects subjective experience to objective measurement. Users learn to recognize their own stress patterns. The pre/post comparison creates a feedback loop that sharpens both self-awareness and formula accuracy.

---

## Tier 2: Neurofeedback Quality & Session Experience

### 2.1 Logarithmic Audio Volume Curve

> **STATUS: COMPLETED in v1.1.0** — Log curve (k=9), MAX_VOLUME=0.3

**Current state:** Linear mapping — `volume = (threshold - score) / threshold`.

**Problem:** Human loudness perception is logarithmic. The last 20% of improvement toward threshold is barely audible — the most important range for training provides the weakest feedback signal.

**Proposal:**
- Replace linear with power curve: `volume = ((threshold - score) / threshold) ^ 0.4`
- This makes small improvements near the threshold clearly audible
- Add a "Volume Curve" setting: Linear / Logarithmic / Custom exponent
- Optional: visualize the curve in Settings so users understand the mapping

---

### 2.2 Gentler Alert Sound Design

**Current state:** Bell is 800Hz decaying sine + harmonics (0.6s). Chime is 1200Hz with 6Hz tremolo (0.8s). Both are synthetic and abrupt.

**Problem:** Sudden pure-tone alerts are startling during meditation — the opposite of a gentle mindful reminder. They trigger fight-or-flight rather than gentle redirection.

**Proposal:**
- Replace bell with **singing bowl synthesis**: inharmonic partials (fundamental + 2.41x + 3.15x), slow beating between close frequencies, 2-3 second decay, lower fundamental (~300Hz)
- Replace chime with **soft wind chime**: randomized cluster of 3-4 high tones (800-1400Hz) with staggered onset (50-150ms apart), longer individual decays
- Add 200ms fade-in to all alert sounds (eliminate the hard attack)
- Keep current sounds as "Classic" option for users who prefer them

---

### 2.3 Zen Mode (Minimal Session View)

**Current state:** Live session shows 7 metric lines, stats grid, buttons, nav bar, and state labels — all while the user is supposed to have eyes closed.

**Problem:** The information-dense display is useful for research but counterproductive during actual meditation practice. Users who glance at the screen see a stock-trading dashboard.

**Proposal:**
- Add "Zen Mode" toggle (button or auto-activate on session start, configurable)
- Full-screen black background, no nav bar, no stats
- Single visual element: a soft pulsing circle whose size maps to shamatha score
- Elapsed time in small text (optional)
- Tap anywhere to place marker, double-tap to exit Zen Mode
- All data collection continues normally in background
- Audio feedback is the primary channel in this mode

---

### 2.4 Signal Quality Indicator

> **STATUS: PARTIALLY COMPLETED in v1.1.0** — Signal quality shown during BT connection overlay (quality value + text description). Full persistent indicator on session screen still pending.

**Current state:** NeuroSky signal_quality (0-200) is read but only shown as connected/disconnected binary. Power-line noise detection exists but only shows a text warning.

**Problem:** Users start sessions with poor electrode contact and get garbage data. They don't know until they see erratic graphs — wasting the session and polluting their dataset.

**Proposal:**
- Add a signal quality bar (4 bars, like Wi-Fi strength) visible on Live Session screen
- Map: signal_quality 0 = 4 bars (excellent), 26-50 = 3 bars, 51-100 = 2 bars, 101-150 = 1 bar, 151-200 = 0 bars
- Color: green → yellow → red
- Show power-line noise indicator as a small icon when detected
- Block session start (with override) when signal quality is consistently poor
- Expose `signal_quality` as a formula variable (see 1.3)

---

### 2.5 Session Warm-up and Cool-down

> **STATUS: PARTIALLY COMPLETED in v1.1.0** — Session end summary card implemented. Warm-up phase still pending.

**Current state:** Session starts immediately on "Start" button, ends with a save/discard popup.

**Problem:** No transition into or out of meditative state. Abrupt start means first 1-2 minutes of data are always noisy (settling in). Abrupt stop loses the reflective moment.

**Proposal:**
- **Warm-up:** Optional 30-60 second countdown with breathing pace guide (visual pulse) before metrics recording begins. EEG data is still collected but tagged as "warm-up" (excluded from session stats by default)
- **Cool-down:** After stop, show a "Session Complete" summary screen: duration, time in deep focus, avg shamatha, best streak — before the save/discard dialog
- Allow configuring warm-up duration (0 / 30 / 60 / 120 seconds)
- Warm-up data still stored (useful for studying settling patterns), just flagged

---

### 2.6 Faster Audio Response Loop

**Current state:** Audio volume updates at 2Hz (every 500ms), same rate as metrics. Volume ramp adds additional latency (25ms steps, 0.6 vol/sec max).

**Problem:** 500ms+ delay between mental state change and auditory feedback weakens the neurofeedback conditioning. Research shows <200ms feedback loops are significantly more effective for operant conditioning.

**Proposal:**
- Decouple audio update from metrics tick: interpolate volume between ticks at 10-20Hz
- Use exponential smoothing between last two metric values for continuous volume
- Reduce volume ramp constraint from 0.6 vol/sec to 1.2 vol/sec (faster response, may need smoothing to avoid clicks)
- Keep graph and DB updates at 2Hz (no need to increase those)

---

### 2.7 Haptic Feedback Channel (Android)

**Current state:** No vibration feedback. All feedback is audio or visual.

**Problem:** Audio feedback requires unmuted device and may disturb others. Visual feedback requires open eyes. Haptic is the only eyes-closed, silent feedback channel.

**Proposal:**
- Optional gentle vibration patterns on Android (via pyjnius Vibrator API)
- Patterns: slow pulse when entering deep focus, double-tap when distraction detected, triple for sinking
- Intensity proportional to metric magnitude
- Configurable: enable/disable, select which events trigger haptic
- Complement audio, not replace — users can use both or either

---

### 2.8 Binaural Beat Layer

**Current state:** Audio is rain noise only (brown + white noise mix).

**Problem:** Many meditation practitioners use binaural beats for brainwave entrainment (e.g., 10Hz alpha binaural = 200Hz left ear, 210Hz right ear). This is a frequently requested feature in meditation apps.

**Proposal:**
- Optional binaural beat carrier underneath rain noise
- Presets: Alpha (10Hz), Theta (6Hz), Deep Meditation (4Hz), Custom frequency
- Synthesize as two sine waves with configurable base frequency and beat frequency
- Volume independent of meditation feedback (constant ambient layer)
- Only works with stereo headphones — show reminder
- Adaptive mode: beat frequency follows dominant EEG band (alpha-dominant → alpha binaural)

---

## Tier 3: User Personas & Adaptive Interface

The app serves three distinct user types with fundamentally different needs. Rather than finding a lowest-common-denominator UI, give each persona a tailored experience.

### 3.0 User Persona System

> **NOTE:** The v1.1.0 UI redesign laid groundwork for this feature: 3-tab bottom nav (Session / History / Settings), 4 themes with live refresh, and a 2-step onboarding wizard. The persona system could build on this foundation by adding feature-flag visibility per persona, persona selection in the wizard's first step, and persona-specific defaults for the existing theme/nav/settings infrastructure.

**Current state:** All users see the same interface — 7 tabs, all metrics, all settings, custom formula editor, raw EEG view. A first-time meditator sees the same screen as a neuroscience researcher.

**Problem:** Beginners are overwhelmed and don't know where to start. Experienced meditators want a clean, distraction-free practice tool. Researchers want maximum data access and formula tools. One interface cannot serve all three well.

**Proposal — Persona selection on first launch (changeable in Settings):**

#### Persona: Meditator (Beginner)

**Goal:** Learn meditation with EEG feedback. Needs guidance, simplicity, encouragement.

**What they see:**
- **3 tabs only:** Meditate, History, Settings
- **Meditate screen:** Large session timer, single "Shamatha Score" gauge (circular, 0-100), simple state label ("Settled" / "Gently Refocus" / "Brighten Awareness"), Start/Pause/Stop buttons. No multi-line graph by default.
- **History screen:** Session list with date + duration + score. Simple trend sparkline ("Your focus is improving"). No raw data, no frequency graphs.
- **Settings:** Threshold slider with guidance text ("Start at 30-40 and increase as you improve"), audio on/off, timer, device selection. No formula editor, no graph toggles, no line width.
- **Language:** Meditation-friendly labels (see 4.3 Reframe Labels). "Gently Refocus" not "Gross Distraction".
- **Onboarding:** Guided first session with breathing exercise warm-up, explanation of what the score means, what to expect.
- **Feedback:** Post-session screen: "You spent 8 of 20 minutes in deep focus. That's 3 minutes more than last time!" Milestones and streaks prominent.

**Hidden:** Raw EEG, custom formulas, frequency bands, normalized values, CSV export, analytics aggregation, state profiles, marker labels.

#### Persona: Practitioner (Experienced Meditator / Guru)

**Goal:** Deepen practice with data insights. Wants clean meditation UX with optional depth when reviewing.

**What they see:**
- **4 tabs:** Meditate, Diary, Analytics, Settings
- **Meditate screen:** Zen Mode by default (dark, minimal, pulsing circle). Option to switch to detailed graph view. Timer integrated. Quick-start duration presets (5/10/20/30/Free).
- **Diary screen:** Full session review with metrics graph, notes, tags, mood. Frequency tab available but secondary. Markers visible.
- **Analytics:** Trend graphs, streaks, session comparison. Focus on practice consistency and deepening over time.
- **Settings:** Threshold, audio configuration (including alert sound selection), timer, state profile selection from built-ins (Drowsiness, Stress, Focus). Device settings.
- **Language:** Mix of meditation terms and gentle technical — "Alpha Dominance" is fine, "sqrt-normalized relative band power" is not.
- **Audio:** Full access to alert configuration, binaural beats (if implemented), custom timer sounds.

**Hidden:** Raw EEG screen, custom formula editor, CSV export (available via long-press or "More" menu), formula backtesting, dataset tagging, EDF+ export. All accessible via "Show Advanced" in Settings.

#### Persona: Researcher (Data Scientist / Formula Developer)

**Goal:** Collect labeled datasets, develop formulas, analyze EEG patterns, export data.

**What they see:**
- **All tabs:** Meditate, Raw EEG, Research, Diary, Analytics, Settings
- **Meditate screen:** Full detailed graph view by default. All 7+ metric lines visible. Stats grid with live values. Marker button prominent with label picker.
- **Research screen (new):** Custom formula editor with live preview, formula backtesting panel, state profile builder, marker correlation analysis, auto-marker configuration. This consolidates formula-related features from Settings into a dedicated workspace.
- **Raw EEG screen:** Full access to waveform and frequency band visualization.
- **Diary screen:** Full features + dataset tagging, batch export, session comparison overlay, EDF+ export option.
- **Analytics:** All aggregation views + storage statistics + data quality metrics.
- **Settings:** All parameters exposed. Sigmoid tuning, rolling window size, flush interval, graph decimation, signal quality thresholds — everything configurable.
- **Language:** Technical labels throughout. "Gross Distraction (β+γ/α > 2.0)" — show the math.
- **Markers:** Full labeled marker system with auto-markers, marker correlation discovery, state timeline.

**Hidden:** Nothing. All features visible.

---

### 3.0.1 Implementation Strategy

**Phase 1 — Feature flags, not separate UIs:**
- Each feature/section gets a `visibility` flag: `beginner`, `practitioner`, `researcher`, or `all`
- Persona selection sets which flags are active
- Store in `app_settings` as `user_{id}_persona`
- All data collection happens identically regardless of persona — only the UI surface changes
- A beginner's sessions contain the same 25 columns as a researcher's

**Phase 2 — Progressive disclosure within each persona:**
- "Show more details" expandable sections
- Long-press on metrics to see underlying values
- Contextual help tooltips on first encounter with each feature

**Phase 3 — Smart persona suggestion:**
- Track feature usage: if a "beginner" starts using formula editor 3x, suggest "Would you like to switch to Researcher mode?"
- If a "researcher" never opens Raw EEG or formulas after 20 sessions, suggest Practitioner mode

**Key principle:** Persona only controls **visibility**, never **data**. A beginner who switches to researcher mode sees all their historical data with full detail — nothing is lost.

---

### 3.0.2 Persona-Specific Session Flow

| Stage | Beginner | Practitioner | Researcher |
|-------|----------|--------------|------------|
| **Pre-session** | "Ready to meditate?" + breathing guide | Duration picker + Zen Mode toggle | Full config + marker label setup |
| **During session** | Single score gauge + state word | Pulsing circle OR detailed graph | Multi-line graph + stats + markers |
| **Audio feedback** | Rain noise only, no config | Full audio + alerts | Full audio + configurable metric |
| **Markers** | Hidden (or simple tap) | Button with default label | Labeled + auto-markers active |
| **Post-session** | "Great job!" + key stats + streak | Summary + prompt for notes/mood | Full stats + state timeline + export prompt |
| **Review** | Simple list + score trend | Diary + analytics | Full diary + comparison + backtesting |

---

## Tier 4: UI/UX Polish & Navigation

### 4.1 Simplified Navigation (Complements Persona System)

> **STATUS: COMPLETED in v1.1.0** — 3-tab bottom nav, merged views.

**Current state:** 7 tabs always visible in ActionBar: Profile, Live, Raw EEG, Settings, Diary, Analytics, Timer.

**Problem:** Too many top-level destinations. Raw EEG and Timer are secondary screens that fragment attention. New users don't know where to start.

**Proposal:**
- Reduce to 4 primary tabs: **Meditate** (live session + timer), **Review** (diary + analytics), **Research** (raw EEG + formulas), **Settings**
- Timer controls integrated into session screen (duration picker before start)
- Analytics accessible as a tab within Review
- Raw EEG and Custom Formula screens grouped under Research
- Profile management moved into Settings

---

### 4.2 Onboarding Flow

> **STATUS: COMPLETED in v1.1.0** — 2-step wizard.

**Current state:** App launches to an empty Profile screen. No guidance.

**Problem:** First-time users don't know what the app does, how to connect a device, or what to expect. Drop-off before first session is likely high.

**Proposal:**
- 3-step first-launch wizard:
  1. "Welcome" — brief explanation of EEG meditation training and data collection
  2. "Connect" — device setup (mock demo mode or Bluetooth scan) with visual guide for headset placement
  3. "Create Profile" — name entry, optional goal setting
- Wizard only shows once (flag in app_settings)
- "Quick Start" option to skip with defaults
- After wizard, auto-navigate to Live Session screen ready to start

---

### 4.3 Reframe State Labels

**Current state:** States are "Stable Focus", "Gross Distraction", "Sinking", "Subtle Distraction", "Neutral".

**Problem:** "Gross Distraction" and "Sinking" feel like failure judgments. In meditation practice, noticing distraction is itself a success — the moment of recognition is the training.

**Proposal:**
- Rename states to meditation-friendly language:
  - "Stable Focus" → "Settled" (or keep as is)
  - "Gross Distraction" → "Gently Refocus"
  - "Sinking" → "Brighten Awareness"
  - "Subtle Distraction" → "Subtle Wandering"
  - "Neutral" → "Transitioning"
- Add optional "Research Mode" toggle in Settings that shows original technical labels for formula developers
- This is cosmetic — no logic changes, just label strings

---

### 4.4 Session Duration Presets on Start Screen

> **STATUS: COMPLETED in [Unreleased]** — Preset row [5/10/15/20/Free] added above Start on the Live Session screen. Selected preset highlighted. Settings → Timer preset row aligned to [5/10/15/20].

**Current state:** Timer is a separate screen. Users must navigate there before starting a session.

**Problem:** Extra navigation step for the most common pre-session action.

**Proposal:**
- Add quick-select duration buttons directly on Live Session screen (above Start button): [5] [10] [20] [30] [Free]
- "Free" = no timer (current default behavior)
- Selecting a preset auto-enables the timer with that duration
- Full timer customization still available in dedicated Timer screen/section

---

### 4.5 Dark/Light Theme and Visual Identity

> **STATUS: COMPLETED in v1.1.0** — 4 themes, icon, presplash, MDI icons.

**Current state:** Hard-coded dark theme with no branding. Colors defined inline across all screen files. No app icon, splash screen, or logo.

**Problem:** Looks like a developer prototype rather than a polished product. Some users prefer light themes for readability in daylight. No visual identity for recognition.

**Proposal:**
- Extract all colors into a theme config (single source of truth)
- Add light theme variant (cream/warm white backgrounds, dark text, muted metric colors)
- Toggle in Settings: Dark / Light / System
- Design a simple app icon (brain wave + lotus/circle motif) and splash screen
- Apply consistent padding, border radius, and typography scale

---

### 4.6 Settings Organization

> **STATUS: COMPLETED in v1.1.0** — ThemedAccordion, presets, profile/timer inline.

**Current state:** Single scrollable screen with 6+ sections, mixing basic controls (threshold) with advanced features (custom formulas, graph line width).

**Problem:** Overwhelming for regular users. Power users can't quickly find advanced options.

**Proposal:**
- Split into two levels:
  - **Basic:** Threshold slider, timer, audio on/off, device selection
  - **Advanced:** Custom formulas, graph toggles, line width, rotation, hotkeys, audio metric selection
- Default view shows Basic; "Show Advanced" expands the rest
- Move Custom Formula to its own screen (accessible from Advanced or from Research tab)

---

## Tier 5: Engagement, Retention & Sharing

### 5.1 Progress Milestones

**Current state:** No achievement system. Analytics shows raw numbers only.

**Problem:** Users lack motivation signals between sessions. No celebration of consistency or improvement.

**Proposal:**
- Track milestones: streak days (3, 7, 14, 30, 60, 100), total sessions (10, 25, 50, 100), total minutes (60, 300, 600, 1800), personal best shamatha, longest focus streak
- Show milestone notification after session end when a new one is reached
- Display earned milestones on Profile screen
- Store in DB (milestone name + date achieved)
- Keep it minimal — no gamification, just acknowledgment

---

### 5.2 Session Summary Share Card

**Current state:** No sharing mechanism. Session data stays on-device only.

**Problem:** Users can't easily share progress with meditation communities, teachers, or research collaborators.

**Proposal:**
- After session (or from Diary), generate a shareable image card:
  - Dark gradient background with app branding
  - Key stats: duration, avg shamatha, time in deep focus, streak
  - Mini sparkline of shamatha over session
  - Date and optional user name
- Render as PNG using Kivy canvas export
- Share via Android share intent or save to file on desktop
- Privacy: no raw EEG data in the card, just summary metrics

---

### 5.3 Guided Training Programs

**Current state:** No structured progression. Users set their own threshold and train freely.

**Problem:** New users don't know what threshold to start at or how to progress. Advanced users plateau without structured challenges.

**Proposal:**
- Built-in programs as JSON configs:
  - "Foundations" (14 days): threshold 30→50, 10-min sessions, focus on consistency
  - "Deepening" (21 days): threshold 50→70, 15-20 min, introduce markers for subjective tracking
  - "Research Mode" (ongoing): variable thresholds, formula experimentation, long sessions
- Each day: brief text instruction + target duration + threshold
- Track program progress in DB
- Users can still do free sessions anytime

---

### 5.4 Daily Reminder Notification

**Current state:** No notifications. Users must remember to open the app.

**Problem:** The #1 reason meditation habits fail is forgetting. A gentle daily reminder at a user-chosen time dramatically improves consistency.

**Proposal:**
- Settings: "Daily reminder" toggle + time picker
- Android: local notification via plyer or pyjnius
- Linux/Windows: system notification via plyer
- Configurable message: default "Time to meditate" or custom text
- Auto-disable if user hasn't opened app in 7 days (avoid spam)

---

### 5.5 Formula Library and Sharing

**Current state:** Formulas are per-user, stored in DB, exportable only as .txt file.

**Problem:** Formula development is isolated. Users can't benefit from each other's discoveries. No community knowledge base.

**Proposal:**
- **Phase 1 (local):** Import formulas from .txt files (complement existing export). Copy formula to clipboard button.
- **Phase 2 (sharing):** Export formula as a small JSON file with metadata (name, description, author, intended use, recommended threshold, sample correlation scores)
- **Phase 3 (community, future):** Optional formula submission to a shared repository (GitHub-based or simple server). Browse and install community formulas with ratings.
- Each phase is independently valuable

---

## Tier 6: Stability & Technical Improvements

### 6.1 Reduce Data Loss Window

**Current state:** Metrics flushed to DB every 60 seconds. App crash loses up to 60s of data.

**Problem:** On mobile, apps can be killed at any time. 60 seconds of lost meditation data is significant, especially if markers were placed in that window.

**Proposal:**
- Reduce default flush interval to 15 seconds
- Additionally flush on Android `on_pause` lifecycle event (app backgrounded)
- Flush immediately when a marker is placed (markers are rare but high-value)
- Make flush interval configurable in Advanced Settings for power users

---

### 6.2 Graph Performance on Low-End Devices

**Current state:** ScrollableGraphWidget renders up to 600 points with 7 metric lines. Full redraw on every update.

**Problem:** On budget Android phones, 4200 line segments redrawn 2x/second causes UI stutter, which degrades the meditation experience.

**Proposal:**
- Implement decimation: when viewport > 3 minutes, downsample display to 1 point/second (visually indistinguishable)
- Use dirty-region rendering: only redraw the rightmost ~10% of the graph on new data (scroll redraws full)
- Cache static portions of the graph as texture
- Profile on target devices (Android emulator + real low-end phone) to set thresholds

---

### 6.3 Bluetooth Reconnection UX

**Current state:** On BT disconnect, warble sound plays and status shows "Reconnecting..." No user controls.

**Problem:** Users can't retry connection, switch to mock mode, or understand why disconnection happened. Session may be stuck in a limbo state.

**Proposal:**
- Show reconnection dialog with options: "Retry", "Continue without device" (switch to mock, preserve session), "Stop session"
- Display last known signal quality and disconnect reason if available
- Auto-retry with exponential backoff (1s, 2s, 4s, max 10s) for 30 seconds before showing dialog
- Log disconnect events in metrics table (special marker type) for data quality tracking

---

### 6.4 Auto-Save on Unexpected Exit

**Current state:** If app is killed mid-session, unflushed data is lost and session may be left in inconsistent state.

**Problem:** Android aggressively kills background apps. Users lose sessions without warning.

**Proposal:**
- On `on_pause` (Android): flush all buffers, save session state to a recovery file
- On next launch: detect incomplete session, offer to resume or save what was collected
- Store recovery state: session_id, last flush timestamp, pending metrics buffer (serialized)
- Clean up recovery file on normal session stop

---

### 6.5 Database Backup and Restore

**Current state:** Single SQLite file (meditation.db). No backup mechanism.

**Problem:** If DB gets corrupted or device is lost, all historical data (the primary product of using this app) is gone.

**Proposal:**
- Manual backup: "Export Database" button in Settings → copies .db file to user-chosen location
- Manual restore: "Import Database" → replaces current DB (with confirmation)
- Optional auto-backup: weekly copy to a second location on device
- Future: optional cloud sync to user's own storage (Google Drive, Dropbox)

---

### 6.6 Power-Line Noise Mitigation

**Current state:** 50/60Hz noise is detected via Goertzel algorithm and shown as a UI warning. No mitigation applied.

**Problem:** Power-line noise contaminates EEG data, making formulas less accurate. Users may not be able to move away from the noise source.

**Proposal:**
- Add optional notch filter at detected frequency (50 or 60 Hz) applied to raw bands before metrics computation
- Configurable: Off / Auto-detect / Force 50Hz / Force 60Hz
- Show "Filtered" indicator when active
- Store filter state in metrics metadata so exported data is properly documented
- Note: NeuroSky processes internally, so this mainly helps with residual noise in band powers

---

## Tier 7: Storage Optimization

### The Problem: Storage Math

Current metrics table: 25 columns per row, ~250 bytes in SQLite with overhead.

| Usage Pattern | Rows/Year | DB Size |
|---------------|-----------|---------|
| Casual: 3x/week, 20 min | 374K | ~95 MB |
| Daily: 30 min | 1.3M | ~330 MB |
| Researcher: daily 1 hour | 2.6M | ~660 MB |
| Heavy: 2 sessions/day, 45 min | 3.9M | ~1 GB |

On Android with 32-64GB storage, 300MB+ for a meditation app is a problem. And this grows linearly forever.

**Two root causes:**
1. **Redundant columns:** 13 of 25 columns (normalized bands + computed metrics) are fully derivable from the 8 raw bands. That's ~52% wasted storage.
2. **No compression or archival:** Every tick is stored at full precision forever, even for 2-year-old sessions the user will never re-analyze at tick level.

---

### 7.0 Storage Engine Strategy: SQLite vs DuckDB vs Hybrid

**Evaluated option: DuckDB**

DuckDB is a columnar analytical database that excels at compressing float timeseries (8-15x) and running analytical queries 10-100x faster than SQLite. For a 30-min session, DuckDB would store ~60-120KB vs SQLite's ~900KB.

**Why we can't use DuckDB on Android:**
- DuckDB Python wheel is ~50MB native C++ binary
- No python-for-android (Buildozer) recipe exists — cross-compiling for arm64-v8a is a major effort
- 50MB APK size increase is significant for mobile
- DuckDB is optimized for batch analytical reads, not continuous 2Hz small writes during live sessions

**Recommended hybrid strategy:**

| Use Case | Engine | Rationale |
|----------|--------|-----------|
| Live session writes (2Hz inserts) | SQLite | Best at frequent small writes, zero overhead, guaranteed compatibility |
| Active sessions (<30 days) | SQLite | Fast random access for diary review, backtesting |
| Archived sessions (>30 days) | Compressed BLOBs in SQLite | zlib on packed float arrays = 5-8x compression, no new deps |
| Desktop research export | Parquet files | For pandas/polars/DuckDB analysis on laptop — best columnar format |
| Desktop power-user mode (optional) | DuckDB as alternative backend | Linux/Windows only, for users with 1000+ sessions who need fast cross-session analytics |

**Implementation approach:**
- Abstract storage behind a `StorageBackend` interface: `save_metrics()`, `get_session_metrics()`, `get_sessions_in_range()`, `export()`
- `SQLiteBackend` (default, all platforms) — current DatabaseManager refactored
- `DuckDBBackend` (optional, desktop only) — added to `requirements` only for desktop builds, not in `buildozer.spec`
- Backend selection in Settings (Researcher persona only): "Storage Engine: SQLite (default) / DuckDB (desktop only)"
- Data migration tool: "Convert existing SQLite data to DuckDB" (one-time, reversible)

**DuckDB benefits when available (desktop):**
- `SELECT avg(alpha1_raw), avg(beta1_raw) FROM metrics WHERE session_id IN (1,2,3,4,5) GROUP BY session_id` — instant cross-session analytics
- Window functions for formula backtesting: `SELECT *, avg(meditation_score) OVER (ROWS 10 PRECEDING) FROM metrics WHERE session_id = 42` — runs inside the DB, no Python loop
- Native Parquet export: `COPY (SELECT * FROM metrics WHERE session_id = 42) TO 'session_42.parquet'`
- Compression: 330MB/year SQLite → ~30-50MB/year DuckDB

**Parquet export (all platforms, no DuckDB needed):**
- Use `struct` module to write minimal Parquet files (no pyarrow dependency)
- Or use lightweight `fastparquet` (~2MB) if available
- Fallback: compressed CSV (.csv.gz) via Python stdlib `gzip` — ~5x compression over plain CSV

---

### 7.1 Eliminate Redundant Columns (Store Raw Only)

**Current state:** Each metrics row stores 8 raw bands + 5 normalized bands + 7 computed metrics + 2 native values + marker + timestamp + session_id = 25 columns.

**Problem:** `alpha_norm`, `beta_norm`, `theta_norm`, `delta_norm`, `gamma_norm` are just `band / total_power`. `meditation_score`, `shamatha_score`, `distraction`, `sinking`, `subtle_distraction`, `stability`, `calmness` are all computed from the 8 raw bands via MetricsEngine. Storing them is pure redundancy.

**Proposal:**
- **Metrics table (slim):** Store only what can't be recomputed:
  ```sql
  metrics_v2 (
      session_id INTEGER,
      timestamp REAL,
      delta REAL, theta REAL,
      alpha1 REAL, alpha2 REAL,
      beta1 REAL, beta2 REAL,
      gamma1 REAL, gamma2 REAL,
      native_attention REAL,
      native_meditation REAL,
      marker INTEGER,
      marker_label TEXT DEFAULT NULL
  )
  ```
  13 columns instead of 25. **~48% storage reduction.**

- **Recompute on read:** When loading a session for Diary/Analytics/Export, run MetricsEngine over the stored raw bands to produce all derived values. At 2Hz with simple math, recomputing a 30-min session (3600 rows) takes <50ms — imperceptible.

- **Cache computed results in memory** during session review to avoid re-computing on graph scroll.

- **Migration:** Add `metrics_v2` table. New sessions write to v2. Background migration job converts old sessions on demand (when user opens them in Diary) or in bulk ("Optimize Storage" button in Settings).

- **Session summary table already exists** — `sessions` table has `avg_meditation`, `avg_shamatha`, etc. for quick list display without touching metrics at all.

**Risk:** If MetricsEngine formula changes in a future version, recomputed values will differ from what was originally shown. Mitigation: store engine version in session metadata. For critical research, use CSV export (which snapshots the computed values at export time).

---

### 7.2 Float32 Precision (Optional, Stacks with 7.1)

**Current state:** SQLite stores REAL as 8-byte IEEE 754 double.

**Problem:** EEG band powers from NeuroSky are 24-bit unsigned integers cast to float. Storing them as 64-bit doubles wastes 4 bytes per value per row. With 8 bands, that's 32 bytes/row wasted.

**Proposal:**
- Pack raw bands as a single BLOB column using `struct.pack('<8f', ...)` — 32 bytes for all 8 bands instead of 64 bytes.
- Keep timestamp, session_id, marker, native values as normal columns (for indexing/filtering).
- On read: `struct.unpack('<8f', blob)` to restore.

**Storage reduction:** Additional ~15% on top of 7.1.

**Tradeoff:** Loses ability to query individual bands in SQL (e.g., `WHERE alpha1_raw > 1000`). This is rarely needed — most analysis loads full sessions.

**Alternative:** Skip this if 7.1 + 7.3 provide enough savings. This adds complexity for modest gains.

---

### 7.3 Session Archival with Compression

**Current state:** All sessions stored at full 2Hz tick resolution forever. No lifecycle management.

**Problem:** A researcher analyzing today's session doesn't need tick-level data from 6 months ago. But deleting old data destroys research value. Need a middle ground.

**Proposal — Tiered storage:**

**Tier A: Active (< 30 days old)**
- Full 2Hz resolution in metrics table
- Instant access for diary, backtesting, export
- This is the working dataset

**Tier B: Archived (> 30 days old)**
- Compress metrics rows using zlib and store as a single BLOB in a new `metrics_archive` table:
  ```sql
  metrics_archive (
      session_id INTEGER PRIMARY KEY,
      data BLOB NOT NULL,  -- zlib-compressed JSON or msgpack
      row_count INTEGER,
      original_size INTEGER,
      compressed_size INTEGER
  )
  ```
- On access: decompress in memory, recompute derived metrics
- EEG timeseries data compresses well (~5-8x with zlib) because consecutive band values are highly correlated
- **~80% storage reduction** for archived sessions

**Tier C: Summarized (optional, user-initiated)**
- Downsample to 1 point per 5 seconds (10x reduction) for very old sessions
- Keep only: mean band powers per 5-second window + marker positions
- User explicitly opts in: "This session is old, summarize to save space?"
- Irreversible — warn clearly

**Archival trigger:**
- Automatic: sessions > 30 days old archived on app startup (background, non-blocking)
- Manual: "Archive Now" button in Settings → Storage section
- Show storage breakdown: "Active: 45 MB (12 sessions), Archived: 23 MB (89 sessions), Total: 68 MB"

**Implementation:**
- `msgpack` (or `json` + `zlib`) for serialization — msgpack is ~2x smaller than JSON for numeric arrays
- Decompression is fast: ~10ms for a 30-min session on mobile
- Archived sessions load slightly slower in Diary but still feel instant

---

### 7.4 Storage Dashboard & Management

**Current state:** Analytics screen shows "Storage: X MB | Y sessions | Z data points" — a single line.

**Problem:** Users can't see which sessions are consuming space, can't selectively clean up, and have no visibility into storage growth.

**Proposal:**
- **Storage screen** (in Settings or Analytics):
  - Total DB size with breakdown: active metrics / archived metrics / sessions / settings
  - Per-session storage: list sorted by size, showing row count and compressed size
  - Growth trend: "You're adding ~8 MB/month. At this rate, you'll hit 500 MB in 14 months."
  - Storage actions:
    - "Archive sessions older than [30/60/90] days" — compress to Tier B
    - "Delete sessions older than [date]" — with export-first option
    - "Vacuum database" — reclaim freed space (SQLite doesn't auto-shrink)
    - "Export & Delete" — bulk export selected sessions as CSV/zip, then remove from DB
  - Show savings: "Archiving 89 sessions would free 180 MB (78% of current usage)"

- **Automatic warning:** When DB exceeds configurable threshold (default 200 MB), show a notification after session end suggesting archival.

---

### 7.5 Incremental Export for Large Datasets

**Current state:** CSV export loads entire session metrics into memory, writes to string, then to file.

**Problem:** A 2-hour session = 14,400 rows = ~3MB CSV. Loading 10 sessions for batch export = 30MB in memory. On low-RAM Android devices, this can cause OOM.

**Proposal:**
- Stream CSV export: write rows directly to file without holding full result in memory
- For batch export: process one session at a time, append to zip file
- Progress indicator for large exports
- Optional: Parquet export format (columnar, ~5x smaller than CSV, readable by pandas/polars/R)
  - `pyarrow` is heavy (~50MB), but `fastparquet` or manual Parquet writing is lighter
  - Alternative: compressed CSV (.csv.gz) — trivial to implement, ~5x compression

---

### 7.6 Computed Metrics Cache Table (Performance Optimization)

**Problem:** After implementing 7.1 (store raw only), every Diary session view requires recomputing all metrics. For session comparison (issue 1.4), loading 3-4 sessions means 4x recomputation.

**Proposal:**
- Optional `metrics_cache` table that stores precomputed results:
  ```sql
  metrics_cache (
      session_id INTEGER,
      engine_version TEXT,  -- e.g., "vernihor_win_v1"
      computed_at TEXT,
      data BLOB  -- compressed array of computed metrics
  )
  ```
- Cache populated lazily on first Diary view of a session
- Invalidated when engine version changes (user updates app)
- Not backed up — purely a performance cache, can be rebuilt
- Keeps the "store raw only" principle clean while avoiding repeated computation

---

## Tier 8: Future Vision

### 8.1 Multi-Device Support

Support for EEG devices beyond NeuroSky MindWave Mobile 2 — e.g., Muse, OpenBCI, or generic LSL streams. Abstract the EEG source interface to accept different band schemas and sample rates. This expands the user base and enables cross-device formula validation.

### 8.2 Real-Time Formula Collaboration

Two users run sessions simultaneously, sharing formula results in real-time. Useful for teacher-student meditation training where the teacher monitors the student's custom metrics remotely.

### 8.3 Machine Learning Formula Discovery

Given a labeled dataset (markers = states), automatically suggest formula candidates using symbolic regression or genetic programming. The user provides labeled sessions, the system proposes formulas that best predict the labels. Integrates with the existing custom formula syntax.

### 8.4 EEG Journal with AI Insights

After each session, optionally prompt the user for a brief text reflection. Over time, correlate journal entries with EEG patterns using NLP. Surface insights like "sessions where you mention 'tired' show 40% higher theta/alpha ratio in the first 5 minutes."

### 8.5 Research Applications: Extended Practice Types

The app currently targets shamatha (calm abiding) meditation. But the EEG data collection + labeled marker + formula pipeline is general-purpose. It can support research into any practice where brain states change.

#### 8.5.1 Loving-Kindness (Metta) + Shamatha Combined Training

**Scientific basis (strong):**
- Lutz et al., 2004 (PNAS): Tibetan monks with 10,000+ hours showed massive high-amplitude gamma synchrony (25-42 Hz) during compassion/metta meditation — orders of magnitude beyond novices
- Frontal gamma power increase is the most robust EEG signature of metta practice
- Theta coherence changes also observed during loving-kindness
- Single FP1 electrode CAN measure gamma1 (30-50Hz) and gamma2 (50-70Hz) changes

**What the app would need:**
- New state profile: "Metta Depth" = `(gamma1 + gamma2) / (beta1 + beta2 + 1) * 100`
- Calibration prompt specific to metta: "Generate feelings of compassion for a loved one" vs "Rest with neutral mind"
- Combined training mode: alternating shamatha (calm) and metta (compassion) blocks within one session
- Markers labeled "compassion arising", "lost the feeling", "strong warmth"
- Track gamma/theta ratio trends across sessions as metta skill develops

**Estimated feasibility:** HIGH — gamma measurement at FP1 is well-validated, no hardware changes needed.

#### 8.5.2 Extraordinary Abilities Research Platform

**Honest scientific context:**
- No peer-reviewed evidence establishes reproducible EEG signatures for telekinesis or similar claimed abilities
- However: the absence of evidence is partly due to lack of tools for large-scale personal EEG data collection with subjective state labeling
- The app's value here is NOT to prove/disprove anything, but to **collect the data that could be analyzed**

**What the app enables for schools/groups researching exceptional experiences:**
1. Record brain state during any practice (not just meditation)
2. Practitioner marks subjective moments: "felt energy", "visualization clear", "movement attempt", "nothing happening"
3. After many sessions, correlation discovery shows: "At your 'energy' markers, gamma1 is 3.2x baseline and theta drops 40%"
4. Build a formula detecting that personal pattern
5. Use it as neurofeedback: train to enter the state more reliably and sustain it longer
6. Track: does training make the state easier to achieve over weeks/months?

**The platform doesn't need to "believe" in any particular ability.** It measures brain states. If a practitioner reports a subjective experience, the platform shows whether their brain is doing something measurably different from their own baseline. That's legitimate neuroscience regardless of the interpretation.

#### 8.5.3 Statistical Framework for Evaluating Findings

For ANY research application (metta, extraordinary abilities, attention training), the app should provide built-in statistical tools to evaluate whether a finding is real or noise.

**Proposed metrics (accessible to Researcher persona):**

| Metric | What It Measures | Threshold for Credibility |
|--------|-----------------|--------------------------|
| **Within-person effect size (Cohen's d)** | Is the brain doing something different during marked states vs baseline? | d > 0.8 (large effect) |
| **Within-person reproducibility** | Does the same EEG pattern repeat across sessions when the same state is reported? | >70% of marked events show the pattern |
| **Formula detection accuracy** | Can a formula predict marked states from EEG alone (without knowing when marks were placed)? | Precision >60%, Recall >60% |
| **Null comparison (permutation test)** | Is the pattern different from random fluctuation? Shuffle marker times randomly 1000x and compare | p < 0.05 |
| **Time-locked specificity** | Does the EEG shift happen AT the marked moment, not at random times? | Peak within ±3 seconds of marker |
| **Cross-session stability** | Does the effect size hold up in the latest 5 sessions as well as the first 5? | No significant decay trend |
| **Cross-person replication** | If multiple users mark similar states, do they show similar EEG patterns? | Same direction of effect in >60% of users |

**Implementation:**
- "Research Report" button in Diary (Researcher persona) — select a marker label + formula, generate stats
- Uses stored session data, no new collection needed
- Runs permutation test in background (1000 shuffles, ~5 seconds for 30-min session)
- Shows clear verdict: "Strong evidence" / "Suggestive" / "Inconclusive" / "No evidence" based on combined metrics
- Export report as PDF/markdown for sharing with collaborators

**Why this matters:** Without built-in statistics, users will see patterns in noise and believe their formula works. The permutation test is the critical reality check — it answers: "Would I see this same pattern if the markers were placed at random times?" If yes, the finding is noise. If no, something real is happening at those marked moments.

#### 8.5.4 Multi-Practitioner Study Mode

For schools or research groups with multiple users on separate devices:

**Phase 1 — Manual aggregation:**
- Each practitioner exports their sessions as CSV/Parquet
- Researcher loads all exports into pandas/R and runs cross-person analysis
- App generates standardized export format with anonymized user IDs

**Phase 2 — Shared database:**
- Optional server backend (simple REST API) where multiple devices sync session data
- Researcher dashboard: see all practitioners' sessions, run cross-person formula backtesting
- Privacy controls: practitioners consent to share specific sessions, can redact marker labels
- Aggregate statistics: "Across 15 practitioners, gamma1 during 'energy' markers is 2.1x baseline (p=0.003)"

**Phase 3 — Live group sessions:**
- Teacher monitors multiple students' brain states in real-time
- Shared screen shows group average metrics and individual outliers
- Teacher can place markers on individual students ("student A entered deep state at 3:45")

---

### 8.6 Scientific Export and Reproducibility

Full EDF+ export with proper metadata headers. BIDS-compatible folder structure for research datasets. Integration with MNE-Python and EEGLAB import pipelines. DOI-ready dataset packaging for publications.

---

## Implementation Priority Matrix

### Sprint 1 — Foundation: Data Collection Pipeline
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 1.1 Labeled Markers | Medium | Critical | Medium |
| 1.2 Formula Backtesting | Medium | Critical | Medium |
| 1.3 Temporal Variables + Windowed Functions | Small | High | Low |
| 6.1 Reduce Data Loss (flush interval) | Small | High | Medium |

### Sprint 2 — State Detection MVP + Personas Foundation
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 1B.1 State Profile System (built-in + custom) | Large | Critical | High |
| 1B.6 Drowsiness/Alertness Monitor | Small | High | High |
| 1B.5 Focus Quality Index (TBR trend) | Small | High | Medium |
| 3.0 User Persona System (feature flags) | Medium | Medium | Critical |
| 2.4 Signal Quality Indicator | Small | Medium | High |

### Sprint 3 — Calibration, Correlation & Storage
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 1B.2 Personal Calibration Workflow | Large | Critical | High |
| 1B.4 Marker-to-EEG Correlation Discovery | Large | Critical | Medium |
| 7.1 Eliminate Redundant Columns (raw-only storage) | Medium | Medium | Low |
| 1B.7 Stress/Relaxation Tracker | Small | Medium | High |
| 1.8 Dataset Tagging & Filtering | Medium | High | Medium |

### Sprint 4 — Analysis & Comparison
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 1.4 Session Comparison & Overlay | Large | Critical | Medium |
| 1.5 Formula Correlation Report | Large | Critical | Low |
| 1B.3 Auto-State Tagger (timeline) | Medium | High | Medium |
| 1.7 Export Enhancements (batch, EDF+) | Medium | High | Medium |
| 7.3 Session Archival with Compression | Medium | Low | Medium |

### Sprint 5 — UX & Neurofeedback Polish
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 2.1 Logarithmic Audio Curve | Small | Low | High |
| 2.3 Zen Mode | Medium | Low | High |
| 2.2 Gentler Alert Sounds | Medium | Low | High |
| 4.3 Reframe State Labels | Small | Low | Medium |
| 4.4 Duration Presets on Start | Small | Low | Medium |
| 2.5 Warm-up/Cool-down | Medium | Medium | Medium |

### Sprint 6 — Navigation & Onboarding (Persona-Driven)
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 4.1 Simplified Navigation | Medium | Low | High |
| 4.2 Onboarding Flow (per-persona) | Medium | Low | High |
| 4.6 Settings Organization | Medium | Low | Medium |
| 2.6 Faster Audio Response Loop | Medium | Low | Medium |
| 7.4 Storage Dashboard & Management | Medium | Medium | Medium |

### Sprint 7 — Stability & Automation
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 1.6 Auto-Markers (formula-triggered) | Medium | High | Low |
| 6.4 Auto-Save on Crash | Medium | High | Medium |
| 6.3 Bluetooth Reconnect UX | Medium | Medium | Medium |
| 6.2 Graph Performance (decimation) | Medium | Low | Medium |
| 6.5 Database Backup/Restore | Medium | High | Medium |
| 7.5 Incremental Export for Large Datasets | Small | Medium | Low |

### Sprint 8 — Engagement & Sharing
| Issue | Effort | Impact on Research | Impact on UX |
|-------|--------|--------------------|--------------|
| 5.5 Formula Library & Sharing | Large | High | Medium |
| 5.1 Progress Milestones | Medium | Low | High |
| 5.3 Guided Training Programs | Large | Medium | High |
| 4.5 Theme/Branding/Visual Identity | Large | Low | High |
| 5.2 Session Summary Share Card | Small | Low | Medium |
| 5.4 Daily Reminder | Small | Low | Medium |
| 2.7 Haptic Feedback (Android) | Medium | Low | Medium |
| 2.8 Binaural Beat Layer | Medium | Low | Medium |
| 6.6 Power-Line Notch Filter | Medium | Medium | Low |

### Backlog — Future Vision
| Issue | Effort | Notes |
|-------|--------|-------|
| 7.0 DuckDB Desktop Backend | Large | Optional storage engine for power users with 1000+ sessions |
| 7.2 Float32 Precision | Small | Optional stacking optimization on top of 7.1 |
| 7.6 Computed Metrics Cache | Medium | Performance opt after 7.1 implemented |
| 8.1 Multi-Device Support (Muse, OpenBCI, LSL) | XL | Expands user base, enables cross-device validation |
| 8.2 Real-Time Formula Collaboration | XL | Teacher-student remote monitoring |
| 8.3 ML Formula Discovery (symbolic regression) | XL | Auto-suggest formulas from labeled datasets |
| 8.4 EEG Journal with AI Insights | XL | NLP correlation with journal entries |
| 8.5.1 Loving-Kindness Training Mode | Medium | Gamma-based metta depth profile, combined practice blocks |
| 8.5.2 Extraordinary Abilities Research | Medium | Platform support for open-ended practice research |
| 8.5.3 Statistical Framework for Findings | Large | Permutation tests, effect sizes, cross-session validation |
| 8.5.4 Multi-Practitioner Study Mode | XL | Shared database, group monitoring, cross-person analysis |
| 8.6 Scientific Export (EDF+, BIDS, MNE-Python) | Large | Research-grade reproducibility |
