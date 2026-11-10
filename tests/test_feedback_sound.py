from unittest.mock import MagicMock

from app.session.session_program import SessionProgram
from app.ui.audio_metric import baseline_audio_metric
from app.ui.sound_sources import feedback_plan, source_spec
from tests._audio_metric import audio_metric_alone
from tests._program_run import make_run
from tests._sound_sources import sounds_alone


def test_source_spec_builtins_and_custom():
    assert source_spec("noise") == ("noise", "")
    assert source_spec("tone") == ("tone", "")
    assert source_spec("/a/b.wav") == ("custom", "/a/b.wav")


def test_a_segment_with_no_sound_of_its_own_inherits_the_global_source():
    prog = SessionProgram([{"minutes": 1, "target": 50, "formula": "shamatha_score", "feedback_sound": sound}
                           for sound in ("", "noise", "/x.wav")])
    assert feedback_plan(prog, "tone")[1] == ["tone", "noise", "/x.wav"]


def test_feedback_plan_distinct_sources_and_segment_ids():
    prog = SessionProgram([
        {"minutes": 5, "target": 50, "formula": "shamatha_score"},                       # default
        {"minutes": 5, "target": 70, "formula": "meditation_score", "feedback_sound": "tone"},
        {"minutes": 5, "target": 90, "formula": "shamatha_score", "feedback_sound": "/c.wav"},
    ])
    sources, seg_ids, initial = feedback_plan(prog, "noise")
    assert seg_ids == ["noise", "tone", "/c.wav"]   # '' resolved to global 'noise'
    assert initial == "noise"                        # first segment's source
    assert sources == {
        "noise": ("noise", ""),
        "tone": ("tone", ""),
        "/c.wav": ("custom", "/c.wav"),
    }


def test_feedback_plan_global_tone_default_segments():
    prog = SessionProgram([
        {"minutes": 5, "target": 50, "formula": "shamatha_score"},
        {"minutes": 5, "target": 70, "formula": "meditation_score"},
    ])
    sources, seg_ids, initial = feedback_plan(prog, "tone")
    assert seg_ids == ["tone", "tone"]
    assert initial == "tone"
    assert sources == {"tone": ("tone", "")}


def test_global_feedback_id_resolves_source():
    settings = {"feedback_source": "noise", "feedback_sound_path": ""}
    sounds = sounds_alone(settings)
    assert sounds.global_feedback_id() == "noise"
    settings["feedback_source"] = "tone"
    assert sounds.global_feedback_id() == "tone"
    settings.update(feedback_source="custom", feedback_sound_path="/my.wav")
    assert sounds.global_feedback_id() == "/my.wav"
    settings["feedback_sound_path"] = ""              # custom selected but no file
    assert sounds.global_feedback_id() == "noise"         # falls back to rain


def test_on_test_audio_prepares_selected_source():
    audio = MagicMock()
    sounds = sounds_alone({"feedback_source": "tone", "feedback_sound_path": "", "reward_source": "none",
                           "reward_sound_path": ""}, audio=audio)  # no session: not refused
    sounds.on_test_audio()
    audio.prepare_feedback.assert_called_once_with({"tone": ("tone", "")}, "tone")
    audio.test_audio.assert_called_once()


# --- Bug: program-formula key leaked into the persisted audio metric, driving
#     simple-session volume from a key that's 0 (missing) -> constant max volume.
def test_baseline_audio_metric_rejects_program_keys():
    assert baseline_audio_metric("program_formula_2") == "shamatha_score"
    assert baseline_audio_metric("") == "shamatha_score"
    assert baseline_audio_metric("native_attention") == "native_attention"
    assert baseline_audio_metric("custom_formula") == "custom_formula"


def _drive_key(metric_key, program_active=False, program_key="") -> str:
    run = make_run(program=SessionProgram([{"minutes": 1}]) if program_active else None, audio_key=program_key)
    return audio_metric_alone(metric_key, program_run=run).drive_key()


def test_drive_key_program_slot_outside_program_falls_back():
    # The leaked saved value: simple session must not drive audio from a 0/missing program key.
    assert _drive_key("program_formula_2") == "shamatha_score"


def test_drive_key_uses_program_key_during_program():
    assert _drive_key("shamatha_score", program_active=True, program_key="program_formula_2") == "program_formula_2"


def test_drive_key_normal_metric_passthrough():
    assert _drive_key("native_attention") == "native_attention"
    assert _drive_key("shamatha_score") == "shamatha_score"
