"""Disabling all feedback must stay silent — no forced rain.

Bug: with the below channel set to Off, a program (or simple) session prepared an
empty player set; _start_noise_loop saw the empty dict, assumed 'not prepared
yet', and fell back to a rain player — so noise played below threshold despite
'Off'. The loop must play only what was prepared."""
from app.audio_feedback.noise import AudioEngine


def test_start_noise_loop_stays_silent_when_all_feedback_off(monkeypatch):
    eng = AudioEngine()
    eng.prepare_feedback({"none": ("none", "")}, "none")  # all off -> no players
    assert eng._feedback_players == {}
    eng._is_playing = True

    calls = []
    real_prepare = eng.prepare_feedback
    monkeypatch.setattr(eng, "prepare_feedback",
                        lambda *a, **k: (calls.append(a), real_prepare(*a, **k))[1])

    eng._start_noise_loop()

    assert not calls, "start must not force a rain player when all feedback is Off"
    assert eng._active_feedback == ""
    assert eng._noise_sound is None
