# Audio feedback

The audio engine: below/reward feedback channels, one-shot cues, the timer gong, and the threading rules around Android MediaPlayer.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Engine

- **Audio feedback** (`app/audio_feedback/`): the engine (`noise.py` `AudioEngine`), the platform's players and audio focus (`players.py`), a one-shot's slot (`one_shot.py` `OneShot`);
  and the built-in sounds, synthesized as WAV files (`sounds.py`; the rain and tone loops crossfaded at their ends):
  selectable continuous feedback, tingsha bell (sinking), chime (subtle distraction; also the connect sound and a program segment's end cue, `play_transition_cue()`), warble (disconnect alert).
  Desktop plays everything through Kivy's `SoundLoader`.
  On Android the feedback loops, the **timer-end gong** and the alerts use `MediaPlayer` (`USAGE_MEDIA` audio attributes), not SDL_mixer, so they keep playing through screen lock; SoundLoader/SDL is silenced while locked.
  Each one-shot is a `OneShot` slot (`_bell`, `_chime`, `_disconnect`, `_gong`), which keeps one `players.make_player(path, loop=False)` player and replays it from its start.
  The timer gong (`_gong`) is the same kind of one-shot, and its file can change (a custom sound):
  a one-shot asked for another file gets a new player, built before the old one goes, so a file that can't be opened leaves the kept player as it was.
  The new player is built outside the slot's lock: SDL decodes a whole file at load, and a release waits on that lock.
  Each release (`OneShot.release`) bumps the slot's generation, so a player still being built when the app stops the sound (the end card's OK, a new session) is called off and released instead of stored;
  nothing failed, so the gong doesn't fall back.
  A kept player whose start fails is dropped, and the next play builds a fresh one.
  Every one-shot release goes through `OneShot._release_player`, which owns the thread rule: at once on the main thread;
  elsewhere the player is silenced at once (`setVolume`) and released on the next frame, never on the session's runner (and no frame comes while the screen is locked).
  A one-shot's `on_end` belongs to that play and runs once, on Kivy's thread, when the play is over (`OneShot.end`, which takes it under the slot's lock):
  it played to its end (a MediaPlayer completion listener on Android, `_completion_listener`, a pyjnius `OnCompletionListener`;
  the Sound's `on_stop` on desktop, minus the stops the app makes itself: a replay's rewind, Stop), another play replaced it, or the player was released.
  `_release_player` clears a player's end hook first, before any deferral, and then `unload()` stops it, so a released player's end never ends the next play.
  The Settings timer Test passes an `on_end`, so its button reads Test again however the gong stops.
  A custom gong the player can't open rings the default gong instead, as a missing file does.
  On desktop SDL loads a file it can't decode as an empty Sound, so `_KivyNoisePlayer` treats a `SoundSDL2` (wav, flac, mp3, ogg) of zero length as can't-open; `MusicSDL2` (MIDI, trackers) never reports a length.
  `play_timer_sound` returns the file it played ("" for none), and the Test reports a custom file it couldn't play, or no sound at all (`timer_sound_unplayable`).
  **Selectable feedback source** (#10): `AudioEngine.prepare_feedback(sources, active_id)` (main thread) pre-instantiates one looping player per distinct source id (`"noise"`, `"tone"`, `"heartbeat"`, or a custom file path);
  `set_active_feedback(source_id)` is setVolume-only — the active player goes to the modulated volume, all others go to 0.
  No player is created or released mid-session, so switching is tick- and lock-safe, like `mute()`.
  **The session drives its own sound** on the main thread (`RunningSession._deliver`, right after the app's part of each event):
  `Connected` starts the feedback (a headset's start also plays the connect chime), `Paused`/`Resumed` call `pause()`/`resume()`, `Ended` and a discard `stop()` the players;
  a pause or an ending silences them even when the app's part fails (a `finally`), and a start plays only after the app's part succeeded, on a screen that shows the session.
  A Start's session players are prepared by `SoundSources.prepare_session`, which first stops the last session's gong and ends a Settings test still playing
  (the Test is allowed while a Start scans for its headset: the run isn't live then, and a Test left playing would keep the session's feedback from starting).
  **Pause keeps the player set** (#37): `pause()` and `resume()`, never `stop()`/`start()`.
  `pause()` sets every prepared player to volume 0 and stops it, stops the ramp and clears `_is_playing`, so the bell/chime alert gates and `update()` go quiet;
  `resume()` replays the same players (`_play_prepared`), and the ramp restores each role's last target.
  `stop()`, the session-end teardown, tears the prepared set down, which only a session start's `prepare_feedback` + `set_reward` rebuild (`SoundSources.prepare_session`), so both channels would stay silent after Resume.
  The `"tone"` source is a harmonic-pad drone (fundamental + fifth), generated on first use.
  **The built-in sounds are generated once and kept** in `APP.BUILT_IN_SOUNDS_DIR` (`built_in_sounds/` beside the database, the engine's alone; the custom sounds imported on Android are in `sounds/`):
  generating them is pure-Python work on the main thread at every launch otherwise.
  `KeptSounds` (`sounds.py`, the engine's `_sounds`) keeps them: a file's name carries the generators' version (`_SOUNDS_VERSION`) and the arguments that shape it (`_kept_sounds`), and a file under that name is reused as it is:
  `_write_wav` writes through `fileops.write_file_atomic`, so a name never holds part of a sound, and a launch removes the files of other versions.
  Every use reads a sound's path through `KeptSounds.path(name)`, which generates a file that is missing.
  A change to a generator's samples bumps `_SOUNDS_VERSION`; `tests/test_kept_sounds.py` pins the generators' source and the sounds' arguments (their file names) to the version and fails until it is looked at.
  The launch generates what a session can't wait for (rain, both bells, chime, warble; `KeptSounds.prepare`); the tone and crickets loops on first use.
  The `"heartbeat"` source (#11 — stable internal id; the timbre is **Crickets**) is a looping `_NOISE_BUFFER_SECONDS`-long (10 s) WAV: a silent bed with one `_HEARTBEAT_PULSE_SECONDS` (0.1 s) cricket chirp
  — a high tonal carrier (~4.8 kHz) + 2nd harmonic gated by a ~40 Hz half-wave amplitude trill, Hann-windowed to zero at both ends (`_generate_heartbeat_wav`)
  — so a chirp every ~10 s rides the same looping player + volume ramp with **no** tick-loop scheduling, and the silent loop edges keep it gapless.
  It's **reward-only**: `_REWARD_SOURCE_OPTIONS` offers it as "Crickets", `_FEEDBACK_SOURCE_OPTIONS` doesn't.
  `test_audio(reward_id)` runs an `_AudioTest` on a daemon thread, which holds the run's state (active, whether it started the engine's playback, the volume to hand back) and takes one step at a time:
  the reward source first (players are near loop start so the chirp is caught), the below-channel sweep, the three alerts, then the teardown.
  The test prepares its own players over whatever is prepared, so the app refuses it while a session runs, is paused or connects (`SessionControls.refused`);
  a session start ends a test still playing (`end_test()`, next to `stop_timer_bell()` in `SoundSources.prepare_session`):
  the engine holds the run that has it (`_test`), and a run checks it still has the engine before each step and before its last write, so a run taken over touches the engine no more;
  its deferred teardown (`_finish_test`) is called off;
  and `_is_playing`, which the test set, goes back, so the session's `start()` isn't skipped.
  A test started again supersedes the running one the same way; `SoundSources.on_test_audio`/`test_sources` prepare both the below and reward sources.
  Which sounds play is `app/ui/sound_sources.py` (the app's `_sounds`): `SoundSources` reads the sources the settings hold and changes them through the app's settings path,
  and the pure `feedback_plan` / `source_spec` with `SoundSources.global_feedback_id` resolve the global setting and per-segment override (`""` inherits global);
  `ProgramRun._enter_segment` calls `set_active_feedback` at each boundary.
  Persisted per-user: `feedback_source` (`"none"` / `"noise"` / `"tone"` / `"custom"`, default `"noise"`) and `feedback_sound_path`.
  **Dual-zone feedback** (#12, #9): two metric-keyed channels driven from one `update(score, threshold)`.
  The **below** channel is the selected feedback source (`compute_volume(score, threshold)`: log curve, 0 at/above threshold);
  the threshold is the tick's score target, passed with each `update(score, threshold)`: the engine holds no copy of it.
  The **above-threshold reward** channel (`compute_reward_volume`: mirror log curve rising 0→max over `[threshold, threshold + APP.REWARD_SPAN(=30)]`, clamped) is a second prepared player designated by `set_reward(source_id)` (`""`=none).
  Both zones are 0 exactly at the threshold → clean cross-fade.
  The ramp loop drives **every** prepared player toward its role target (below→`_target_volume`, reward→`_reward_target_volume`, others→0); volume-only, tick/lock-safe.
  A channel source of `"none"`/`""` (`source_spec`→`("none","")`) instantiates no player; `prepare_feedback` skips `kind=="none"`, and `_resolve_active("" | "none")` returns `""` so a None **below** channel never grabs the reward player.
  `_teardown_feedback_players` (run by `prepare_feedback` and `stop`) resets `_reward_feedback`, so `set_reward` must be called **after** `prepare_feedback` at session start (the order `SoundSources.prepare_session` uses).
  Reward is **global only** — programs keep per-segment switching on the below channel; reward stays armed across segments.
  `SoundSources.reward_id()` resolves the reward source: a custom selection with no file is silent, where the below channel falls back to rain.
  Persisted per-user: `reward_source` (`"none"`/`"noise"`/`"tone"`/`"heartbeat"`/`"custom"`, default `"none"`) + `reward_sound_path`; `SoundSources.on_reward_source_change` mirrors `on_feedback_source_change`.
  **Source selection UI**: one button per channel, showing the current label (`common.source_label`), opens the shared popup picker:
  `settings_sections.common.open_sound_picker(title, options, on_pick)`, the shared list popup (`open_source_picker`) whose `"custom"` opens the file chooser directly, → the channel's `SourcePicker`;
  the timer's and a program segment's sound pickers open it too.
- **Custom sound files** are picked through `settings_sections.common.open_audio_file_chooser`, the one picker for the feedback, reward, timer and segment sounds.
  The desktop uses Kivy's file browser.
  On Android an app can't list `/data` (the `~` of an app with no `HOME`), or shared storage by path (scoped storage; the app holds no storage permission), so the picker is the system one, `android_saf.open_document(_AUDIO_TYPES)`:
  `audio/*` plus `application/ogg` and `application/x-flac`, which some providers report for ogg and flac.
  `android_saf.import_document` then copies the pick to `EEGMeditation/sounds/<content hash>/<its name>`: the same file picked twice is stored once, and two files sharing a name keep their own bytes.
  A name the provider can't give falls back to `sound`, and a name without an extension takes one from the file's type, for the loaders that choose a decoder by extension.
  Imports run on one thread, one at a time in pick order, so after a slow copy (a cloud file) and a quick second pick, the second pick is the one that stays;
  one at a time also lets them share one part file, which the next import overwrites if the app was killed mid-copy.
  The copy's path is what plays (`MediaPlayer`) and is saved, so the sound survives restarts and the original being moved or deleted, with no persistable URI grant.
  A read that fails reports `sound_pick_failed` and leaves nothing behind.
  Copies are never deleted: one replaced or no longer used stays in `sounds/`.
- Volume uses log scaling (`_log_rise`, `k=9`): rises fast initially, flattens near the max (`APP.MAX_VOLUME` = 0.3).
  Prevents harsh noise at low scores.

## Threading and teardown

- **Android MediaPlayer teardown must never run on the session's runner.**
  `MediaPlayer`'s event handler lives on the main Looper, which is paused while the screen is locked, so `release()`/`stop()` from the runner deadlocks against it (a hung runner → session never saved, noise never stops).
  `setVolume()` has no Looper sync and is safe from the runner.
  Rule: silence on the runner with `AudioEngine.mute()` (non-blocking volume→0, setVolume only); defer the real `AudioEngine.stop()` / gong `release()` to the main thread.
  The Settings **Test audio** sequence runs on a daemon thread, so its closing `stop()` runs on the main thread too (`players.next_frame` → `_finish_test`).
  Every ending (`RunningSession._finish`) mutes, saves, and leaves the players' teardown to the main thread; a timer's gong rings after the save, so a hang can never cost the session.
- **No SoundLoader (SDL_mixer) call off the main thread on Android.**
  While the app is paused (screen locked), SDL holds its audio device's mixer lock until it resumes (`ANDROIDAUDIO_PauseDevices`), and Kivy's `audio_sdl2` calls SDL_mixer without releasing the GIL.
  A SoundLoader play or stop from the runner blocks on that lock with the GIL held, every Python thread stops, and the resume that would free the lock needs the GIL: the app freezes, with an ANR on unlock.
  So the alerts the tick plays are MediaPlayers there (above), and one whose MediaPlayer fails stays silent rather than fall back to SoundLoader (`players.make_player` raises for `loop=False`).
  The gong is that same kept player, replayed at the timer end on the runner, so the Settings Test doesn't fall back either: it plays what the timer end will, and a custom file MediaPlayer can't play rings the default gong in both.
  A noise loop still falls back: it is created and started on the main thread, and the tick only sets its volume, which takes no lock.
  Each alert keeps its one player because the main thread, where a MediaPlayer is released, doesn't run while the screen is locked: a player per alert (cooldowns of 15–20 s) would pile up unreleased all through a long locked session.
- **Audio focus is the engine's, not a player's.** Players never request it:
  a request with no listener is keyed by the `AudioManager`, which every player shares, so per-player requests would be one client that any player's release abandons.
  `AudioFocus` (`players.py`) is the app's one request, kept while any holder plays and abandoned when the last one leaves (`hold`/`release`).
  The session's feedback holds it with `AUDIOFOCUS_GAIN` from its start or resume (`_start_noise_loop`, main thread; a session with every channel off asks for none) to `pause()` or `stop()`:
  nothing plays while paused, and Resume takes the focus back from an app that started playing meanwhile.
  The timer gong holds it (`OneShot.play(..., focus=AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)`, on the runner at a timer end, under its slot's name) from its start until its play is over (`OneShot.end`:
  played out, replayed or released), so other audio dips under it and comes back after, the Settings Test included.
  Under a screen lock the gong's end reaches the app only at unlock (the completion listener runs on the paused main Looper), so its hold lasts until then, as the session's does (its `stop()` waits for the main thread too).
  The first holder's gain stands: a gong at a session's end keeps the session's full focus until it has rung, although `stop()` released the session's hold.
  A refused request (during a call) isn't kept, so the next hold asks again.
  The alerts hold none: they ring under the session's.
- `AudioEngine.stop()` releases only the chime's slot and deliberately leaves the two **session-end cues**, which start just before it runs:
  `_gong` (the timer gong — `RunningSession._finish` rings it on the runner and the ending's teardown runs `stop()` on the main thread a frame later, so unloading it would cut the gong off) and `_disconnect` (the failure warble
  — the ending's teardown calls `_audio.stop()` just after `RunningSession.persist`, whose `SessionManager.stop(reason)` plays it, so unloading it would silence a stale-data/BT-lost end).
  The gong's lifecycle is owned by `play_timer_sound` / `stop_timer_bell`; the alert players are released (`OneShot.release`, main thread) by `cleanup()` at app exit, the chime also by `stop()`.
