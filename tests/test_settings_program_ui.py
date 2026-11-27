from unittest.mock import Mock

import app.ui.settings_sections.common as common
from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen
from app.ui.settings_sections import program_editor


def _screen():
    return SettingsScreen()


def _tap_in_picker(monkeypatch, button, label: str) -> list:
    """Tap `button`, then `label` in the list it opens; the list's rows."""
    shown = []
    monkeypatch.setattr(common, "make_scroll_popup", lambda title, rows, **k: shown.extend(rows) or Mock())
    monkeypatch.setattr(program_editor, "make_scroll_popup", lambda title, rows, **k: shown.extend(rows) or Mock())
    button.dispatch("on_release")
    next(b for b in shown if b.text == label).dispatch("on_release")
    return shown


def test_load_program_populates_without_firing_changed():
    s = _screen()
    changed = []
    wire(s.timer.editor, on_change=lambda segs: changed.append(segs))
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"},
            {"minutes": 5, "target": 70, "formula": "meditation_score"}]
    s.timer.editor.show(segs, "Ramp")
    assert changed == []                      # programmatic load must NOT fire changed
    assert s.timer.editor.segments() == segs   # editor round-trips the segments
    assert s.timer.editor._loaded_label.text == "Loaded: Ramp"
    assert s.timer.editor._total_label.text == "Total: 15 min"
    s.timer.editor.show([], "")
    assert (s.timer.editor._loaded_label.text, s.timer.editor._total_label.text) == ("Loaded: (unsaved)", "Total: 0 min")


def test_add_and_remove_segment_fire_changed():
    s = _screen()
    changed = []
    wire(s.timer.editor, on_change=lambda segs: changed.append(segs))
    s.timer.editor.show([], "")
    s.timer.editor.add_segment()
    assert changed == [[{"minutes": 10, "target": 50, "formula": "shamatha_score"}]]
    s.timer.editor.rows[0].box.children[0].dispatch("on_release")  # its X
    assert changed[-1] == [] and s.timer.editor.rows == []
    assert s.timer.editor._segments_box.children == []


def test_a_typed_minute_count_updates_the_total_and_reports_the_edit():
    s = _screen()
    changed = []
    s.timer.editor.show([{"minutes": 10, "target": 50, "formula": "shamatha_score"},
                         {"minutes": 5, "target": 70, "formula": "meditation_score"}], "")
    wire(s.timer.editor, on_change=lambda segs: changed.append(segs))
    s.timer.editor.rows[1].minutes_input.text = "25"
    s.timer.editor.rows[0].target_input.text = "65"
    assert s.timer.editor._total_label.text == "Total: 35 min"
    assert [(seg["minutes"], seg["target"]) for seg in changed[-1]] == [(10, 65), (25, 70)]
    s.timer.editor.rows[1].minutes_input.text = ""  # the total counts it as 0, the program as one minute
    assert s.timer.editor._total_label.text == "Total: 10 min" and changed[-1][1]["minutes"] == 1


def test_set_program_mode_does_not_fire_callback():
    s = _screen()
    seen = []
    wire(s.timer, on_mode=lambda m: seen.append(m))
    s.timer.show_mode("program")
    assert seen == []                          # programmatic set is silent
    assert s.timer.editor.box.parent is not None and s.timer._simple_box.parent is None


def test_a_mode_tap_swaps_its_controls_and_reports_it():
    s = _screen()
    seen = []
    wire(s.timer, on_mode=lambda m: seen.append(m))
    s.timer._mode_toggle.buttons["program"].dispatch("on_release")
    assert seen == ["program"]
    assert s.timer.editor.box.parent is not None and s.timer._simple_box.parent is None
    s.timer._mode_toggle.buttons["simple"].dispatch("on_release")
    assert seen == ["program", "simple"] and s.timer.editor.box.parent is None


def test_set_saved_programs_populates_list():
    s = _screen()
    loads, deletes = [], []
    wire(s.timer.editor, on_load=loads.append, on_delete=deletes.append)
    s.timer.editor.show_saved([{"name": "Ramp", "segments": []}, {"name": "Steps", "segments": []}])
    rows = s.timer.editor._saved_box.children[::-1]
    assert len(rows) == 2
    rows[1].children[1].dispatch("on_release")  # "Steps"
    rows[0].children[0].dispatch("on_release")  # Ramp's X
    assert (loads, deletes) == ([1], [0])


def test_save_reports_the_typed_name():
    s = _screen()
    saved = []
    wire(s.timer.editor, on_save=saved.append)
    s.timer.editor.show([], "  Ramp ")
    s.timer.editor._save_button.dispatch("on_release")
    assert saved == ["Ramp"]
    s.timer.editor.confirm_saved()  # the flow's cue once the save is written
    assert "Saved" in s.timer.editor._save_button.text


def test_custom_formula_segment_roundtrips():
    s = _screen()
    seg = {"minutes": 8, "target": 120, "formula": {"name": "Foo", "formula": "alpha1"}}
    s.timer.editor.show([seg], "")
    assert s.timer.editor.segments() == [seg]


def test_a_segment_s_metric_picker_offers_the_built_ins_and_the_saved_formulas(monkeypatch):
    s = _screen()
    s.formulas.show_saved([{"name": "Calm", "formula": "theta / (delta + 1)"}, {"name": "", "formula": "alpha1 * 2"}])
    s.timer.editor.show([{"minutes": 5, "target": 60, "formula": "shamatha_score"},
                         {"minutes": 5, "target": 60, "formula": "shamatha_score"}], "")
    changed = []
    wire(s.timer.editor, on_change=lambda segs: changed.append(segs))
    second = s.timer.editor.rows[1]
    offered = _tap_in_picker(monkeypatch, second.formula_button, "Calm")
    # An unnamed one by its text, as Saved Formulas lists it.
    assert [b.text for b in offered] == ["Shamatha", "Meditation", "NS Attention", "NS Meditation", "Calm", "alpha1 * 2"]
    assert [row.children[1].text for row in s.formulas._saved_box.children[::-1]] == ["Calm", "alpha1 * 2"]
    assert second.formula_button.text == "Calm"
    assert [seg["formula"] for seg in changed[-1]] == ["shamatha_score", {"name": "Calm",
                                                                          "formula": "theta / (delta + 1)"}]
    _tap_in_picker(monkeypatch, second.formula_button, "NS Attention")
    assert (second.formula_button.text, s.timer.editor.segments()[1]["formula"]) == ("NS Attention", "native_attention")


def test_set_feedback_source_does_not_fire_callback(monkeypatch):
    s = _screen()
    fired = []
    wire(s.audio, on_feedback_source_change=lambda src, path: fired.append((src, path)))
    s.audio.feedback.show("custom", "/tmp/x.wav")  # restore -> silent
    assert fired == []
    _tap_in_picker(monkeypatch, s.audio.feedback.button, "Tone")  # user action -> fires, clears stale custom path
    assert fired == [("tone", "")]


def test_a_sound_picker_given_no_source_shows_its_channel_s_default():
    s = _screen()
    s.audio.feedback.show("", "")
    s.audio.reward.show("", "")
    assert (s.audio.feedback.source, s.audio.reward.source) == ("noise", "none")
    assert (s.audio.feedback.button.text, s.audio.reward.button.text) == ("Rain", "Off")


def test_choose_feedback_source_updates_button_label(monkeypatch):
    s = _screen()
    _tap_in_picker(monkeypatch, s.audio.feedback.button, "Tone")
    assert s.audio.feedback.button.text == "Tone"


def test_choose_reward_crickets_fires_and_labels(monkeypatch):
    s = _screen()
    fired = []
    wire(s.audio, on_reward_source_change=lambda src, path: fired.append((src, path)))
    _tap_in_picker(monkeypatch, s.audio.reward.button, "Crickets")
    assert fired == [("heartbeat", "")]
    assert s.audio.reward.button.text == "Crickets"


def test_segment_feedback_sound_roundtrips():
    s = _screen()
    segs = [
        {"minutes": 10, "target": 50, "formula": "shamatha_score", "feedback_sound": "tone"},
        {"minutes": 5, "target": 70, "formula": "meditation_score"},   # default -> omitted
    ]
    s.timer.editor.show(segs, "")
    out = s.timer.editor.segments()
    assert out[0].get("feedback_sound") == "tone"
    assert "feedback_sound" not in out[1]   # Default is not serialized


def test_custom_choice_opens_chooser(monkeypatch):
    calls = []
    monkeypatch.setattr(common, "open_audio_file_chooser", lambda *a, **k: calls.append(k["title"]))
    s = _screen()
    _tap_in_picker(monkeypatch, s.audio.feedback.button, "Custom file...")
    assert calls == ["Feedback sound file"], "choosing Custom file... should open the chooser"


def test_rain_choice_does_not_open_chooser(monkeypatch):
    calls = []
    monkeypatch.setattr(common, "open_audio_file_chooser", lambda *a, **k: calls.append(a))
    s = _screen()
    _tap_in_picker(monkeypatch, s.audio.feedback.button, "Rain")
    assert calls == []


def test_a_segments_sound_pickers_set_its_cue_and_feedback_and_no_other_row_s(monkeypatch):
    s = _screen()
    s.timer.editor.show([{"minutes": 5, "target": 60, "formula": "shamatha_score"},
                         {"minutes": 5, "target": 60, "formula": "shamatha_score"}], "")
    first, second = s.timer.editor.rows
    _tap_in_picker(monkeypatch, second.end_cue_button, "Warble")
    _tap_in_picker(monkeypatch, second.feedback_button, "Tone")
    assert (second.end_cue_button.text, second.feedback_button.text) == ("Warble", "Tone")
    assert (first.end_cue_button.text, first.feedback_button.text) == ("Chime", "Default")
    assert s.timer.editor.segments() == [{"minutes": 5, "target": 60, "formula": "shamatha_score"},
                                         {"minutes": 5, "target": 60, "formula": "shamatha_score",
                                          "end_sound": "warble", "feedback_sound": "tone"}]
    _tap_in_picker(monkeypatch, second.end_cue_button, "Chime")  # back to the defaults: neither is stored
    _tap_in_picker(monkeypatch, second.feedback_button, "Default (use global)")
    assert s.timer.editor.segments()[1] == {"minutes": 5, "target": 60, "formula": "shamatha_score"}
    assert (second.end_cue_button.text, second.feedback_button.text) == ("Chime", "Default")


def test_a_segment_s_custom_feedback_file_is_kept_as_its_path(monkeypatch):
    s = _screen()
    s.timer.editor.show([{"minutes": 5, "target": 60, "formula": "shamatha_score"}], "")
    monkeypatch.setattr(common, "open_audio_file_chooser", lambda on_select, **_k: on_select("/sounds/bowl.mp3"))
    _tap_in_picker(monkeypatch, s.timer.editor.rows[0].feedback_button, "Custom file...")
    assert s.timer.editor.segments()[0]["feedback_sound"] == "/sounds/bowl.mp3"
    assert s.timer.editor.rows[0].feedback_button.text == "bowl.mp3"
