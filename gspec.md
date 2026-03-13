# Technical Specification: EEG Meditation Trainer (Kivy / Android)
**Version:** 2.0 (Merged & Optimized for AI Assistant)  
**Target Platform:** Android  
**Tech Stack:** Python 3.x, Kivy / KivyMD, SQLite  
**Core Goal:** Mobile application for training Shamatha meditation using EEG neurofeedback, featuring real-time biofeedback (white noise), advanced brainwave state calculations, and diary analytics.

---

## 1. Project Architecture & Modules
The application codebase must be strictly organized into logically isolated modules to maintain clean architecture:

```text
app/
├── ui/                 # Kivy screens, widgets, and ScreenManager
├── eeg/                # Bluetooth/Socket connection and hardware parsers
├── metrics/            # Signal processing, math, and state formulas
├── audio_feedback/     # White noise generator and volume control
├── session/            # Session lifecycle (Start, Pause, Stop) and state machine
├── storage/            # SQLite database interactions and JSON/CSV logging
└── analytics/          # Data aggregation for history and trend graphs
```

---

## 2. Data Preprocessing & Core Pipeline

### 2.1. Processing Loop (2 Hz Update Frequency)
The `UIManager` schedules an update loop (`Clock.schedule_interval`) twice per second. 
**Pipeline per tick:** `EEG Sample Received → Rolling Average Smoothing → Total Power Normalization → Metric Calculation → State Detection → Audio Update → Graph Update → Storage Buffer`.

### 2.2. Signal Smoothing
All raw EEG bands must pass through a rolling average buffer to prevent graph spikes.
*   **Window Size:** `5 samples`.
*   **Formula:** `smooth(x_t) = (x_t + x_{t-1} + ... + x_{t-4}) / 5`

### 2.3. Derived Bands & Normalization
*   `alpha = alpha1 + alpha2`
*   `beta = beta1 + beta2`
*   `gamma = gamma1 + gamma2`
*   **Total Power:** `total_power = alpha + beta + gamma + theta + delta + 1` *(+1 prevents DivisionByZero)*.
*   All subsequent formulas should use normalized bands (e.g., `alpha_norm = alpha / total_power`).

---

## 3. Metrics Engine & Sigmoid Normalization

All custom states must be mapped to a **0–100 scale** (or 0-200 to match the UI graph) using a standard Sigmoid function to prevent unbounded values.
**Generic Sigmoid Formula:** 
`Normalized_Value = MAX_SCALE / (1 + math.exp(-k * (Raw_Ratio - Midpoint)))`
*(AI Assistant note: Extract `k` and `Midpoint` into a configuration file for easy calibration).*

### 3.1. Meditation Score (Calmness)
*   **Raw Calmness:** `calmness = alpha / (beta + gamma + 1)`
*   **Score:** Map/Clamp `calmness` to a `0-200` range (using max expected calmness `Cmax ≈ 4`).

### 3.2. Sinking / Dullness (Утопание)
Reduced clarity, drowsiness, increase in slow waves.
*   **Raw Ratio:** `sinking_raw = (theta + delta) / (alpha + beta + 1)`
*   **Normalization:** Apply **Sigmoid Normalization** to output `0-100`.

### 3.3. Gross Distraction (Грубое отвлечение)
Active thinking, stress, wandering mind.
*   **Raw Ratio:** `distraction_raw = (beta + gamma) / (alpha + 1)`
*   **Normalization:** Apply **Sigmoid Normalization** to output `0-100`.

### 3.4. Stability Metric & Subtle Distraction
*   **Stability Buffer:** Maintain a rolling buffer of the `Meditation Score` over the last **20 seconds**.
*   **Stability Math:** `stability = variance(meditation_score_last_20s)`. (Low variance = stable).
*   **Subtle Distraction Logic:** Occurs when the user holds the meditation object (High Meditation Score) but background thoughts cause micro-fluctuations (High Variance).
    *   *Condition:* `IF meditation_score > threshold AND stability > stability_limit`
    *   *Raw Ratio:* `subtle_raw = stability / stability_max`
    *   *Normalization:* Apply **Sigmoid Normalization** to output `0-100`.

### 3.5. Composite Shamatha Score
A final holistic metric representing balanced meditation.
*   `clarity = alpha / (theta + delta + 1)`
*   `stability_factor = 1 / (1 + stability)`
*   `shamatha_raw = (calmness * 0.4) + (clarity * 0.3) + (stability_factor * 0.3)`
*   **Final Score:** Normalize to `0-100`.

---

## 4. UI Layout & Screens (Kivy / Mobile Adapted)

### 4.1. Screen 1: Live Session
*   **Header:** Device status, Timer, Current State Label (Stable, Distracted, Sinking).
*   **Graph:** Real-time multi-line chart (showing last 5 minutes, 2 Hz refresh rate).
*   **Current Stats (Grid):** Meditation, Shamatha, Distraction, Sinking.
*   **Controls (Bottom):** Start, Pause, Stop.

### 4.2. Screen 2: Settings (ScrollView)
*   **Threshold Settings:** Target Meditation score (Slider: 40-70).
*   **Audio Logic:** White noise continuous generation. 
    *   `IF meditation_score >= threshold`: `volume = 0` (Silence).
    *   `ELSE`: `volume = max_volume * (threshold - meditation_score) / threshold`.
*   **Graph Toggles:** Checkboxes to select which metrics to render on the live graph.

### 4.3. Screen 3: Diary & Analytics
*   **Session List:** `RecycleView` of past sessions.
*   **Session Details:** Selecting a session shows its historical graph, basic stats (avg shamatha, % time above threshold), and allows entering **text notes, tags, and a mood rating**.
*   **Analytics Tab:** Long-term trends (weekly/monthly charts for Average Shamatha and Streak counters).

---

## 5. Storage Schema (SQLite)

### Table 1: `sessions` (Metadata)
*   `id` (Primary Key)
*   `date_time` (Timestamp)
*   `duration` (Integer, seconds)
*   `threshold_used` (Integer)
*   `avg_meditation` (Real)
*   `avg_shamatha` (Real)
*   `time_above_threshold` (Integer, seconds)
*   `notes` (Text)
*   `mood_rating` (Integer 1-5)

### Table 2: `metrics` (Timeseries Data)
*   `session_id` (Foreign Key)
*   `timestamp` (Integer, relative offset in seconds)
*   `alpha_norm`, `beta_norm`, `theta_norm`, `delta_norm`, `gamma_norm` (Real)
*   `meditation_score`, `distraction`, `subtle_distraction`, `sinking`, `shamatha_score` (Real)

---

## 6. Performance Constraints (Crucial for Android)
*   **CPU / RAM limits:** Target CPU usage < 10%, RAM < 150MB.
*   **Graph Optimization:** Do not plot every single data point if the session is long. Downsample visual points on the fly using `kivy_garden.graph`.
*   **Memory Management:** Do not hold the entire session's high-resolution metrics in RAM. Flush the rolling buffer to the SQLite `metrics` table (or a temporary chunked file) every 60 seconds.

---

## 7. AI Assistant Development Roadmap

*Instruction to AI: When generating code, follow these phases sequentially.*

*   **Phase 1 - Skeleton:** Setup `app/` folder structure, ScreenManager, base Kivy layouts.
*   **Phase 2 - Mock & Buffer:** Implement `MockEEGStream`, 5-sample rolling buffer, and 20-second variance buffer.
*   **Phase 3 - Math Engine:** Implement the `metrics/` module. Write the Total Power normalizers and **Sigmoid-based** formulas for Sinking, Distraction, and Subtle Distraction. Write Unit Tests for this module.
*   **Phase 4 - Kivy Graphing:** Integrate real-time updating graphs onto the Live Session screen.
*   **Phase 5 - Audio Neurofeedback:** Implement Kivy `SoundLoader` white noise loop with dynamic volume math.
*   **Phase 6 - Database & Diary:** Implement SQLite schema, saving flow on "Stop", and Diary UI (with Notes/Mood).
*   **Phase 7 - Hardware:** Replace Mock with actual NeuroSky ThinkGear Bluetooth parsing. Buildozer spec setup.
