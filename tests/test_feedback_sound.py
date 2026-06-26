from app.session.session_program import SessionProgram
from app.ui.app_manager import EEGMeditationApp


def test_source_spec_builtins_and_custom():
    assert EEGMeditationApp._source_spec("noise") == ("noise", "")
    assert EEGMeditationApp._source_spec("tone") == ("tone", "")
    assert EEGMeditationApp._source_spec("/a/b.wav") == ("custom", "/a/b.wav")


def test_feedback_source_id_inherits_global_on_blank():
    assert EEGMeditationApp._feedback_source_id("", "tone") == "tone"
    assert EEGMeditationApp._feedback_source_id("noise", "tone") == "noise"
    assert EEGMeditationApp._feedback_source_id("/x.wav", "noise") == "/x.wav"


def test_feedback_plan_distinct_sources_and_segment_ids():
    prog = SessionProgram([
        {"minutes": 5, "target": 50, "formula": "shamatha_score"},                       # default
        {"minutes": 5, "target": 70, "formula": "meditation_score", "feedback_sound": "tone"},
        {"minutes": 5, "target": 90, "formula": "shamatha_score", "feedback_sound": "/c.wav"},
    ])
    sources, seg_ids, initial = EEGMeditationApp._feedback_plan(prog, "noise")
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
    sources, seg_ids, initial = EEGMeditationApp._feedback_plan(prog, "tone")
    assert seg_ids == ["tone", "tone"]
    assert initial == "tone"
    assert sources == {"tone": ("tone", "")}
