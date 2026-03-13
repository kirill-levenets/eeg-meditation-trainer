


Here is an analysis of the provided text, the extracted useful features, and the fully updated Technical Specification (Version 4.0) tailored for the AI code assistant.

### Extracted Useful Features & Insights

1.  **New Normalization Math (Hill Function):** Instead of a complex exponential sigmoid, the text proposes a computationally cheaper and highly effective logistic curve variant: $f(x) = 100 \cdot \frac{Ratio}{Ratio + Pivot}$.
    *   *Why it's better:* It naturally bounds the value between 0 and 100. It handles extreme biometric outliers seamlessly. It provides a perfect mathematical midpoint: when the raw `Ratio` equals the `Pivot`, the resulting score is exactly 50.
2.  **Refined Raw Ratios:**
    *   **Distraction Ratio:** `High_Beta / Total_Alpha` (Thoughts vs. Calmness). Default Pivot = 1.0.
    *   **Sinking Ratio:** `Theta / (Total_Beta + High_Alpha)` (Drowsiness vs. Waking/Calm state). Default Pivot = 1.2.
3.  **Crucial UX Feature - User Calibration:** Because skull thickness and baseline EEG amplitudes vary wildly between users, the `Pivot` values **must be adjustable via the UI**. Adding "Sensitivity" sliders (ranging from 0.5 to 2.0) allows users to calibrate the device to their unique brainwaves if the metrics feel permanently "stuck" at 10 or 90.

---

# Technical Specification: EEG Meditation Trainer (Kivy / Android)
**Version:** 4.0 (Updated with Pivot-based Normalization & User Calibration)  
**Target Platform:** Android  
**Tech Stack:** Python 3.x, Kivy / KivyMD, SQLite  

---

## 1. Project Architecture & Modules
The application codebase must be strictly organized into logically isolated modules:

```text
app/
├── ui/                 # Kivy screens, widgets, ScreenManager
├── eeg/                # Bluetooth/Socket connection and hardware parsers
├── metrics/            # Signal processing, Pivot math, and state formulas
├── audio_feedback/     # Dual-channel audio (White noise + Alert bells)
├── session/            # Session lifecycle (Start, Pause, Stop)
├── storage/            # SQLite database interactions and JSON logging
└── analytics/          # Data aggregation for history and trend graphs
```

---

## 2. Data Preprocessing & Core Pipeline

### 2.1. Processing Loop (2 Hz Update Frequency)
The `UIManager` schedules an update loop (`Clock.schedule_interval`) twice per second. 
**Pipeline per tick:** `EEG Sample Received → Rolling Average Smoothing → Metric Calculation (Ratios) → Pivot Normalization → Dual Audio Update → Graph Update → Storage Buffer`.

### 2.2. Signal Smoothing
*   **Window Size:** `5 samples`.
*   **Formula:** `smooth(x_t) = (x_t + x_{t-1} + ... + x_{t-4}) / 5`
*   *Note: Protect all division operations against `ZeroDivisionError` by adding a small epsilon or conditional checks.*

---

## 3. Metrics Engine & Pivot Normalization

All custom states must be mapped to a **0–100 scale** using the Hill function variant.
**Core Normalization Formula:** 
`Normalized_Score = 100 * (Raw_Ratio / (Raw_Ratio + Pivot))`
*(Where `Pivot` is a user-configurable sensitivity constant).*

### 3.1. Meditation Score (Native or Calculated)
*   If provided by NeuroSky hardware natively, use the `eSense Meditation` value (0-100). 
*   *Scale up to 0-200 on the graph purely for visual UI representation if needed to match the reference design.*

### 3.2. Gross Distraction (Грубое отвлечение)
Active thinking, stress, wandering mind.
*   **Raw Ratio:** `dist_ratio = high_beta / (low_alpha + high_alpha)`
*   **Normalization:** `distraction_100 = int(100 * (dist_ratio / (dist_ratio + dist_pivot)))`
*   **Default `dist_pivot`:** 1.0

### 3.3. Sinking / Dullness (Утопание)
Reduced clarity, drowsiness, increase in slow waves.
*   **Raw Ratio:** `sink_ratio = theta / (low_beta + high_beta + high_alpha)`
*   **Normalization:** `sinking_100 = int(100 * (sink_ratio / (sink_ratio + sink_pivot)))`
*   **Default `sink_pivot`:** 1.2

### 3.4. Composite Shamatha Score
A balanced representation of the meditation quality.
*   `shamatha_raw = (meditation_score * 0.4) + ((100 - distraction_100) * 0.3) + ((100 - sinking_100) * 0.3)`
*   *(Shamatha is high when Meditation is high, and both Distraction and Sinking are low).*

---

## 4. Dual-Channel Audio Engine (Neurofeedback)
This module handles two distinct audio streams to prevent the "White Noise Trap" during sinking.

### 4.1. Channel 1: Active Distraction (Continuous)
*   **Sound:** White Noise (seamless loop).
*   **Logic:** 
    *   `IF meditation_score >= target_threshold`: `volume = 0.0` (Reward silence).
    *   `IF meditation_score < target_threshold`: Volume increases dynamically.
    *   `volume = clamp((target_threshold - meditation_score) / target_threshold, 0.0, 1.0)`.

### 4.2. Channel 2: Sinking Alert (Discrete)
*   **Sound:** Tibetan Bell (Tingsha), Water Drop, or crisp click (short `.wav` file).
*   **Logic:**
    *   `IF sinking_100 > sinking_alert_threshold` (e.g., > 60): Play the sound once.
    *   **Debounce/Cooldown:** Implement a cooldown timer (e.g., 15-20 seconds) after the bell rings. It resets when `sinking_100` drops below the threshold.

---

## 5. UI Layout & Screens (Kivy / Mobile Adapted)

### 5.1. Screen 1: Live Session
*   **Header:** Device status, Timer, Current State.
*   **Graph:** Real-time multi-line chart (showing last 5 minutes).
*   **Current Stats (Grid):** Meditation, Shamatha, Distraction, Sinking.
*   **Controls (Bottom):** Start, Pause, Stop.

### 5.2. Screen 2: Settings (ScrollView)
*   **Target Thresholds:**
    *   Meditation Target (Slider: 40-90, default 80).
    *   Sinking Alert Threshold (Slider: 40-90, default 60).
*   **Calibration (Sensitivity Pivots):**
    *   Distraction Sensitivity (Slider: 0.5 to 2.0, default 1.0). *Changes `dist_pivot`.*
    *   Sinking Sensitivity (Slider: 0.5 to 2.0, default 1.2). *Changes `sink_pivot`.*
*   **Audio Toggles:** Enable/Disable White Noise, Enable/Disable Sinking Bell.
*   **Graph Toggles:** Checkboxes for visible metrics.

### 5.3. Screen 3: Diary & Analytics
*   **Session List:** `RecycleView` of past sessions.
*   **Session Details:** Shows historical graph, text notes, tags, and a mood rating.

---

## 6. Storage Schema (SQLite)

### Table 1: `sessions` (Metadata)
`id` (PK), `date_time`, `duration`, `meditation_threshold`, `sinking_threshold`, **`dist_pivot_used`**, **`sink_pivot_used`**, `avg_meditation`, `avg_shamatha`, `sinking_alerts_triggered` (Integer count), `notes`, `mood_rating`.
*(Saving the used pivots ensures historical graphs can be recalculated accurately if the user changes sensitivity later).*

### Table 2: `metrics` (Timeseries Data)
`session_id` (FK), `timestamp` (relative offset in seconds), `alpha_total`, `beta_total`, `theta`, `meditation_score`, `distraction_100`, `sinking_100`, `shamatha_score`.

---

## 7. AI Assistant Development Roadmap

*   **Phase 1 - Skeleton:** Setup `app/` folder structure, ScreenManager, base Kivy layouts.
*   **Phase 2 - Mock & Buffer:** Implement `MockEEGStream` and the 5-sample rolling buffers.
*   **Phase 3 - Math Engine:** Implement the `metrics/` module. Write the `calculate_normalized_metrics()` function using the new **Ratio / (Ratio + Pivot)** logic.
*   **Phase 4 - Kivy Graphing:** Integrate real-time updating graphs on the Live Session screen.
*   **Phase 5 - Dual Audio Engine:** Implement `AudioFeedbackManager` utilizing `kivy.core.audio`. Include the dynamic white noise logic and the debounced Sinking Bell logic.
*   **Phase 6 - Database & Settings UI:** Implement SQLite schema (including pivot metadata), Calibration Sliders in the Settings screen, and Diary UI.
*   **Phase 7 - Hardware:** Replace Mock with NeuroSky ThinkGear Bluetooth parsing. Configure Android `buildozer.spec`.