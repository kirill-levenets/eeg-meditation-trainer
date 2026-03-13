# EEG Meditation Trainer — Technical Specification
Version: 1.0  
Target platform: Android  
Language: Python  
Framework: Kivy
Unit tests for each module

---

# 1. Purpose of the Application

Mobile application for training meditation using EEG neurofeedback.

The application must:

- read EEG signals from a headset
- calculate meditation quality metrics
- provide real-time biofeedback using white noise
- visualize brain activity
- detect meditation states
- store complete session telemetry
- allow diary entries and long-term analytics

---

# 2. Core Functional Modules

The application must be organized into the following modules:


app
├── ui
├── eeg
├── metrics
├── audio_feedback
├── session
├── storage
└── analytics

Each module must be logically isolated.

---

# 3. EEG Input Data Model

Each EEG sample must contain:


timestamp
delta
theta
alpha1
alpha2
beta1
beta2
gamma1
gamma2
attention
meditation

Derived bands:


alpha = alpha1 + alpha2
beta = beta1 + beta2
gamma = gamma1 + gamma2

---

# 4. Signal Preprocessing

All EEG signals must be smoothed using a rolling average.

Rolling window:


window_size = 5 samples

Smoothed value:


smooth(x_t) = (x_t + x_t-1 + ... + x_t-4) / 5

---

# 5. Normalized Brain Energy

Total power:


total_power = alpha + beta + gamma + theta + delta + 1

Normalized bands:


alpha_norm = alpha / total_power
beta_norm = beta / total_power
gamma_norm = gamma / total_power
theta_norm = theta / total_power
delta_norm = delta / total_power

---

# 6. Calmness Ratio

Calmness represents balance between relaxation and cognitive activity.

Formula:


calmness = alpha / (beta + gamma + 1)

---

# 7. Meditation Score

Meditation score is normalized calmness.

Range:


0 – 200

Formula:


meditation_score = clamp(200 * calmness / Cmax)

Where:


Cmax = empirical calmness max (≈4)

Clamp:


0 ≤ meditation_score ≤ 200

---

# 8. Stability Metric

Stability indicates consistency of meditation.

Compute variance over last 20 seconds.


stability = variance(meditation_score_last_20s)

Low variance = stable attention.

---

# 9. Distraction Detection

Distraction occurs when cognitive activity dominates.

Formula:


distraction_raw = (beta + gamma) / (alpha + 1)

Normalize:
distraction = clamp(100 * distraction_raw / Dmax)
or use sigmoid normalization

Typical:
Dmax ≈ 5

Range:


0 – 100

---

# 10. Subtle Distraction

Subtle distraction occurs when meditation score remains high but becomes unstable.

Condition:


if meditation_score > meditation_threshold
and stability > stability_limit

Compute subtle distraction intensity:


subtle_distraction = stability / stability_max

Range:


0 – 100

---

# 11. Sinking (Dullness) Detection

Sinking corresponds to reduced clarity or drowsiness.

EEG indicators:

- increase in theta
- increase in delta
- decrease in beta

Formula:
sinking_raw = (theta + delta) / (alpha + beta + 1)

Normalize:
sinking = clamp(100 * sinking_raw / Smax)
or use sigmoid normalization

Typical:


Smax ≈ 3

Range:


0 – 100

---

# 12. Focus Ratio

Focus ratio indicates attention clarity.

Formula:


focus_ratio = alpha / (theta + delta + 1)

Higher value = clearer attention.

---

# 13. Shamatha Score

Shamatha score represents balanced meditation quality.

Combine three factors:


clarity
stability
calmness

Definitions:


clarity = focus_ratio
calmness = calmness
stability = 1 / (1 + variance(meditation_score))

Final score:


shamatha_score = 100 *
normalize(
calmness * 0.4 +
clarity * 0.3 +
stability * 0.3
)

Range:


0 – 100

---

# 14. Meditation State Classification

Each moment must be classified into one of the states.

### State 1 — Stable Focus

Condition:


meditation_score ≥ threshold
stability < stability_limit
sinking < sinking_limit
distraction < distraction_limit

---

### State 2 — Subtle Distraction

Condition:


meditation_score ≥ threshold
stability ≥ stability_limit

---

### State 3 — Gross Distraction

Condition:


distraction ≥ distraction_limit

---

### State 4 — Sinking

Condition:


sinking ≥ sinking_limit

---

# 15. Real-Time Graphs

The session screen must display real-time graphs.

-------------------------------------
Start | Pause | Stop

Meditation threshold:
(40) (50) (60) (70)

Sound when threshold:
[ ] tone
[ ] white noise

Timer:
(1) (5) (10) (30)

-------------------------------------
|                                     |
|            GRAPH                    |
|                                     |
-------------------------------------

Metrics
delta
theta
alpha
beta
gamma
meditation
attention

Metrics plotted:


meditation_score
distraction
subtle_distraction
sinking
shamatha_score

Graph window:


last 5 minutes

Update frequency:


2 Hz

---

# 16. Audio Feedback

The application must continuously generate white noise.

Volume must depend on meditation score.

If:


meditation_score ≥ threshold

Then:


volume = 0

Otherwise:


volume = max_volume * (threshold - meditation_score) / threshold

Behavior:


low meditation → loud noise
deep meditation → silence

---

# 17. Session Lifecycle

Session states:


IDLE
RUNNING
PAUSED
FINISHED

Session flow:


Start → RUNNING
Pause → PAUSED
Resume → RUNNING
Stop → FINISHED

---

# 18. Session Statistics

During the session calculate:


average_meditation
max_meditation
time_above_threshold
distraction_rate
sinking_rate
subtle_distraction_rate
average_shamatha

---

# 19. Data Storage

Storage engine:


SQLite

---

## sessions table


id
date
duration
avg_meditation
max_meditation
avg_shamatha
notes

---

## metrics table


session_id
timestamp
alpha
beta
gamma
theta
delta
meditation_score
distraction
subtle_distraction
sinking
shamatha_score

---

# 20. Diary

Each session may contain:


text notes
tags
mood

Example:


notes
tags
mood_rating

---

# 21. Analytics

Analytics screen must provide long-term graphs.

Required analytics:


meditation_score trend
session duration trend
distraction frequency
sinking frequency
shamatha score trend
streak counter

Aggregation periods:


daily
weekly
monthly

---

# 22. Performance Requirements

The application must maintain:


CPU usage < 10%
RAM usage < 150MB

Strategies:


use rolling buffers
limit graph resolution
avoid recalculating full history

---

# 23. Signal Buffer

Maintain a rolling buffer:


buffer_duration = 120 seconds

Used for:


stability calculation
variance calculation
state detection

---

# 24. Update Loop

Processing pipeline per sample:


EEG sample received
↓
signal smoothing
↓
normalized band computation
↓
metric calculation
↓
state detection
↓
audio feedback update
↓
graph update
↓
storage

---

# 25. Development Phases

## Phase 1 — Base Application

Implement:


Kivy app
ScreenManager
Session screen
History screen

---

## Phase 2 — EEG Interface

Implement:


EEG device connection
sample stream
signal buffer

---

## Phase 3 — Metrics Engine

Implement:


meditation score
distraction
subtle distraction
sinking
shamatha score

---

## Phase 4 — Realtime Visualization

Implement:


rolling graphs
metric overlays
session UI

---

## Phase 5 — Audio Neurofeedback

Implement:


white noise generator
dynamic volume control
threshold feedback

---

## Phase 6 — Session Engine

Implement:


session lifecycle
statistics calculation
timers

---

## Phase 7 — Storage

Implement:


SQLite schema
session persistence
metric logging

---

## Phase 8 — Diary and History

Implement:


session list
session details
notes

---

## Phase 9 — Analytics

Implement:


trend graphs
statistics
progress tracking

---

# 26. Optional Future Extensions

Possible future improvements:


AI meditation coach
adaptive thresholds
guided meditation modes
progress prediction
community comparison

---

# End of Specification
