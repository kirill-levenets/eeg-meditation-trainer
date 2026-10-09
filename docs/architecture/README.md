# Architecture

How each subsystem works and why. [CLAUDE.md](../../CLAUDE.md) holds the commands, the module map and the invariants; read the file for a subsystem before changing it, and update it in the same commit as the change.

| File | Covers | Main code |
|---|---|---|
| [eeg-bluetooth.md](eeg-bluetooth.md) | EEG sources, the NeuroSky link, the single-reader lifecycle, the BT wait at session start, BT throughput and render stats, diagnostic tools | `app/eeg/`, `app/ui/app_manager.py` (`_begin_bt_wait`, `_handle_bt_wait`, `_abort_bt_wait`), `app/ui/render_stats.py`, `tools/` |
| [metrics-scoring.md](metrics-scoring.md) | Metrics engine and its formulas, custom formulas, the scored metric (#51), the threshold in force (#83) | `app/metrics/`, `app/session/scoring.py`, `app/session/manager.py` |
| [session.md](session.md) | Session state machine, tick thread, session names and labels, checkpoints (#30), the session ending path, timer, screen lock | `app/session/manager.py`, `app/session/timer_state.py`, `app/ui/app_manager.py`, `app/ui/session_labels.py`, `service/` |
| [programs.md](programs.md) | Session programs: model, live series, Settings and picker controls, per-segment feedback | `app/session/session_program.py`, `app/ui/app_manager.py`, `app/ui/settings_screen.py` |
| [audio.md](audio.md) | Audio engine: below/reward channels, cues, timer gong, MediaPlayer threading | `app/audio_feedback/noise.py` |
| [storage.md](storage.md) | SQLite, write lock, DB paths and migrations, per-user settings registry, backup/restore and SAF | `app/storage/`, `app/settings/registry.py` |
| [ui-theme.md](ui-theme.md) | Navigation, theme system and colour roles, shared widgets, modals | `app/ui/theme.py`, `app/ui/widgets/` |
| [graphs.md](graphs.md) | `ScrollableGraphWidget`: fit, threshold steps, drawing cost, touch routing, fullscreen | `app/ui/raw_eeg_screen.py`, `app/ui/touch_utils.py` |
| [live-session-and-settings.md](live-session-and-settings.md) | Session screen, Settings screen, first-run wizard | `app/ui/live_session.py`, `app/ui/settings_screen.py`, `app/ui/wizard_screen.py` |
| [history.md](history.md) | History screen: charts, totals, RecycleView list, select mode | `app/ui/history_screen.py`, `app/ui/period_totals.py` |
| [session-detail.md](session-detail.md) | Session detail: stats, notes, graphs, what-if threshold (#50), band breakdown, loading | `app/ui/diary_screen.py`, `app/session/what_if.py`, `app/ui/widgets/what_if.py`, `app/ui/widgets/band_totals.py` |
| [app-platform.md](app-platform.md) | User gate and profiles, Android back button, crash handler, perf logging, test guardrails, build/CI | `app/ui/app_manager.py`, `app/crash_handler.py`, `app/logger.py`, build scripts |
