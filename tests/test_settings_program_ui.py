from app.ui.settings_screen import SettingsScreen


def _screen():
    return SettingsScreen()


def test_load_program_populates_without_firing_changed():
    s = _screen()
    changed = []
    s.timer.set_program_changed_callback(lambda segs: changed.append(segs))
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"},
            {"minutes": 5, "target": 70, "formula": "meditation_score"}]
    s.timer.load_program(segs, "program")
    assert changed == []                      # programmatic load must NOT fire changed
    assert s.timer.get_program_segments() == segs   # editor round-trips the segments
    assert s.timer.program_mode == "program"


def test_add_segment_fires_changed():
    s = _screen()
    changed = []
    s.timer.set_program_changed_callback(lambda segs: changed.append(segs))
    s.timer.load_program([], "program")
    s.timer._add_segment_row()
    assert len(changed) >= 1
    assert len(changed[-1]) == 1


def test_set_program_mode_does_not_fire_callback():
    s = _screen()
    seen = []
    s.timer.set_program_mode_callback(lambda m: seen.append(m))
    s.timer.set_program_mode("program")
    assert seen == []                          # programmatic set is silent
    assert s.timer.program_mode == "program"


def test_set_saved_programs_populates_list():
    s = _screen()
    s.timer.set_saved_programs([{"name": "Ramp", "segments": []},
                          {"name": "Steps", "segments": []}])
    assert len(s.timer._saved_programs_box.children) == 2


def test_custom_formula_segment_roundtrips():
    s = _screen()
    seg = {"minutes": 8, "target": 120, "formula": {"name": "Foo", "formula": "alpha1"}}
    s.timer.load_program([seg], "program")
    assert s.timer.get_program_segments() == [seg]


def test_set_feedback_source_does_not_fire_callback():
    s = _screen()
    fired = []
    s.set_feedback_source_callback(lambda src, path: fired.append((src, path)))
    s.set_feedback_source("custom", "/tmp/x.wav")  # restore -> silent
    assert fired == []
    s._choose_feedback_source("tone")  # user action -> fires, clears stale custom path
    assert fired == [("tone", "")]


def test_choose_feedback_source_updates_button_label():
    s = _screen()
    s._choose_feedback_source("tone")
    assert s._feedback_source_btn.text == "Tone"


def test_choose_reward_crickets_fires_and_labels():
    s = _screen()
    fired = []
    s.set_reward_source_callback(lambda src, path: fired.append((src, path)))
    s._choose_reward_source("heartbeat")
    assert fired == [("heartbeat", "")]
    assert s._reward_source_btn.text == "Crickets"


def test_segment_feedback_sound_roundtrips():
    s = _screen()
    segs = [
        {"minutes": 10, "target": 50, "formula": "shamatha_score", "feedback_sound": "tone"},
        {"minutes": 5, "target": 70, "formula": "meditation_score"},   # default -> omitted
    ]
    s.timer.load_program(segs, "program")
    out = s.timer.get_program_segments()
    assert out[0].get("feedback_sound") == "tone"
    assert "feedback_sound" not in out[1]   # Default is not serialized


def test_custom_choice_opens_chooser(monkeypatch):
    import app.ui.settings_screen as ss
    calls = []
    monkeypatch.setattr(ss, "open_audio_file_chooser", lambda *a, **k: calls.append(a))
    s = _screen()
    s._choose_feedback_source("custom")
    assert len(calls) == 1, "choosing Custom file... should open the chooser"


def test_rain_choice_does_not_open_chooser(monkeypatch):
    import app.ui.settings_screen as ss
    calls = []
    monkeypatch.setattr(ss, "open_audio_file_chooser", lambda *a, **k: calls.append(a))
    s = _screen()
    s._choose_feedback_source("noise")
    assert calls == []


def test_segment_end_sound_picker_sets_value():
    s = _screen()
    s.timer.load_program([{"minutes": 10, "target": 50, "formula": "shamatha_score"}], "program")
    row = s.timer._segment_rows[0]
    btn = row._end_sound_btn if hasattr(row, "_end_sound_btn") else None
    # the picker calls _set_segment_end_sound; exercise it directly
    s.timer._set_segment_end_sound(row, row._formula_btn, "warble")  # any label-bearing btn
    assert row._end_sound == "warble"
    assert s.timer.get_program_segments()[0].get("end_sound") == "warble"
    s.timer._set_segment_end_sound(row, row._formula_btn, None)      # back to default (Chime)
    assert row._end_sound is None
    assert "end_sound" not in s.timer.get_program_segments()[0]


def test_a_segments_sound_pickers_set_its_cue_and_feedback(monkeypatch):
    from unittest.mock import Mock

    import app.ui.settings_sections.common as common
    shown = []
    monkeypatch.setattr(common, "make_scroll_popup", lambda title, rows, **k: shown.append(rows) or Mock())
    s = _screen()
    s.timer.load_program([{"minutes": 5, "target": 60, "formula": "shamatha_score"}], "program")
    row = s.timer._segment_rows[0]
    end_btn, fb_btn = Mock(text=""), Mock(text="")
    s.timer._open_segment_end_sound_picker(row, end_btn)
    next(b for b in shown[-1] if b.text == "Warble").dispatch("on_release")
    s.timer._open_segment_feedback_picker(row, fb_btn)
    next(b for b in shown[-1] if b.text == "Tone").dispatch("on_release")
    assert (row._end_sound, end_btn.text) == ("warble", "Warble")
    assert (row._feedback_sound, fb_btn.text) == ("tone", "Tone")
