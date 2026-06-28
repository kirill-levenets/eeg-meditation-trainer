from app.audio_feedback.noise import AudioEngine
from app.config import APP
from app.ui.app_manager import EEGMeditationApp


def _engine(threshold):
    e = AudioEngine()
    e.set_threshold(threshold)
    return e


def test_reward_is_zero_at_and_below_threshold():
    e = _engine(50)
    assert e.compute_reward_volume(50) == 0.0   # exactly at threshold: silent
    assert e.compute_reward_volume(30) == 0.0   # below: silent


def test_reward_saturates_at_threshold_plus_span():
    e = _engine(50)
    top = 50 + APP.REWARD_SPAN
    assert e.compute_reward_volume(top) == e._max_volume
    assert e.compute_reward_volume(top + 40) == e._max_volume  # clamps beyond span


def test_reward_rises_monotonically_above_threshold():
    e = _engine(50)
    prev = e.compute_reward_volume(50)
    for s in range(51, 50 + APP.REWARD_SPAN + 1):
        v = e.compute_reward_volume(s)
        assert v >= prev
        prev = v
    assert e.compute_reward_volume(60) > 0.0


def test_threshold_is_a_clean_crossfade_both_channels_zero():
    e = _engine(50)
    # At the threshold both zones are silent -> seamless handoff, no overlap spike.
    assert e.compute_volume(50) == 0.0
    assert e.compute_reward_volume(50) == 0.0


def test_set_reward_designates_known_player_and_clears():
    e = AudioEngine()
    e._feedback_players = {"noise": object(), "tone": object()}
    e.set_reward("tone")
    assert e._reward_feedback == "tone"
    e.set_reward("")
    assert e._reward_feedback == ""


def test_update_drives_both_zones_when_reward_armed():
    e = _engine(50)
    e._is_playing = False          # exercise target-setting without the ramp thread/players
    e._reward_feedback = "tone"
    e.update(30)                   # below threshold: noise on, reward silent
    assert e._volume > 0.0
    assert e._reward_target_volume == 0.0
    e.update(50 + APP.REWARD_SPAN)  # well above: noise silent, reward at max
    assert e._volume == 0.0
    assert e._reward_target_volume == e._max_volume


def test_update_keeps_reward_silent_when_channel_is_none():
    e = _engine(50)
    e._is_playing = False
    e._reward_feedback = ""        # None channel
    e.update(80)                   # above threshold, but no reward channel
    assert e._reward_target_volume == 0.0


def test_resolve_active_empty_is_no_below_not_a_fallback():
    # below=None (active_id="" or "none") must NOT auto-grab the reward (tone) player.
    assert AudioEngine._resolve_active("", ["tone"]) == ""
    assert AudioEngine._resolve_active("none", ["tone"]) == ""
    assert AudioEngine._resolve_active("noise", ["noise", "tone"]) == "noise"
    assert AudioEngine._resolve_active("missing", ["noise"]) == "noise"  # defensive only for non-empty


def test_source_spec_none_is_silent_sentinel():
    assert EEGMeditationApp._source_spec("none") == ("none", "")
    assert EEGMeditationApp._source_spec("") == ("none", "")
    assert EEGMeditationApp._source_spec("noise") == ("noise", "")
    assert EEGMeditationApp._source_spec("/x.wav") == ("custom", "/x.wav")


def test_reward_id_resolves_none_builtin_and_missing_custom():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._reward_source, app._reward_sound_path = "none", ""
    assert app._reward_id() == ""
    app._reward_source = "tone"
    assert app._reward_id() == "tone"
    app._reward_source, app._reward_sound_path = "custom", ""
    assert app._reward_id() == ""          # missing custom -> silent, no rain surprise
    app._reward_source, app._reward_sound_path = "custom", "/x.wav"
    assert app._reward_id() == "/x.wav"
