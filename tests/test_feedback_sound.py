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


def test_global_feedback_id_resolves_source():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._feedback_source, app._feedback_sound_path = "noise", ""
    assert app._global_feedback_id() == "noise"
    app._feedback_source = "tone"
    assert app._global_feedback_id() == "tone"
    app._feedback_source, app._feedback_sound_path = "custom", "/my.wav"
    assert app._global_feedback_id() == "/my.wav"
    app._feedback_sound_path = ""                       # custom selected but no file
    assert app._global_feedback_id() == "noise"         # falls back to rain


def test_on_test_audio_prepares_selected_source():
    from unittest.mock import MagicMock
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._feedback_source, app._feedback_sound_path = "tone", ""
    app._audio = MagicMock()
    app._on_test_audio()
    app._audio.prepare_feedback.assert_called_once_with({"tone": ("tone", "")}, "tone")
    app._audio.test_audio.assert_called_once()


# --- Bug: program-formula key leaked into the persisted audio metric, driving
#     simple-session volume from a key that's 0 (missing) -> constant max volume.
def test_baseline_audio_metric_rejects_program_keys():
    assert EEGMeditationApp._baseline_audio_metric("program_formula_2") == "shamatha_score"
    assert EEGMeditationApp._baseline_audio_metric("") == "shamatha_score"
    assert EEGMeditationApp._baseline_audio_metric("native_attention") == "native_attention"
    assert EEGMeditationApp._baseline_audio_metric("custom_formula") == "custom_formula"


def _drive_app(metric_key, program_active=False, program_key=""):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._audio_metric_key = metric_key
    app._session_program_active = program_active
    app._program_audio_key = program_key
    app._formula_slots = []
    return app


def test_drive_key_program_slot_outside_program_falls_back():
    # The leaked saved value: simple session must not drive audio from a 0/missing program key.
    assert _drive_app("program_formula_2").  _audio_drive_key() == "shamatha_score"


def test_drive_key_uses_program_key_during_program():
    app = _drive_app("shamatha_score", program_active=True, program_key="program_formula_2")
    assert app._audio_drive_key() == "program_formula_2"


def test_drive_key_normal_metric_passthrough():
    assert _drive_app("native_attention")._audio_drive_key() == "native_attention"
    assert _drive_app("shamatha_score")._audio_drive_key() == "shamatha_score"
