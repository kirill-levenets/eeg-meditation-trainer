"""What a session start prepares, through the real SoundSources: the feedback and reward players in the order the
engine needs (set_reward after prepare_feedback, which resets the reward channel), a program's per-segment sources,
and the gong checked only while the timer is on."""
from unittest.mock import MagicMock, call

from app.session.session_program import SessionProgram
from app.ui.sound_sources import SoundSources
from tests._context import stub_context

SETTINGS = {"feedback_source": "tone", "feedback_sound_path": "", "reward_source": "heartbeat",
            "reward_sound_path": ""}


def _sounds(timer_on: bool = True) -> tuple[SoundSources, MagicMock]:
    audio = MagicMock()
    sounds = SoundSources(stub_context(setting=SETTINGS.__getitem__), audio,
                          MagicMock(enabled=timer_on, custom_sound_path="/gong.wav"), MagicMock())
    sounds.warn_missing = MagicMock()
    return sounds, audio


def test_the_reward_is_set_after_the_players_are_prepared():
    sounds, audio = _sounds()
    sounds.prepare_session(None)
    assert audio.mock_calls == [call.prepare_feedback({"tone": ("tone", ""), "heartbeat": ("heartbeat", "")}, "tone"),
                                call.set_reward("heartbeat")]


def test_a_program_gets_its_per_segment_sources_back():
    sounds, audio = _sounds()
    program = SessionProgram([{"minutes": 1, "target": 50, "formula": "shamatha_score", "feedback_sound": sound}
                              for sound in ("", "noise")])
    assert sounds.prepare_session(program) == ["tone", "noise"]
    assert audio.prepare_feedback.call_args.args[1] == "tone"  # the first segment's
    assert sounds.prepare_session(None) == []


def test_the_gong_is_checked_only_while_the_timer_is_on():
    on, _ = _sounds(timer_on=True)
    on.prepare_session(None)
    assert on.warn_missing.call_args.args[1] == "/gong.wav"
    off, _ = _sounds(timer_on=False)
    off.prepare_session(None)
    assert off.warn_missing.call_args.args[1] == ""
