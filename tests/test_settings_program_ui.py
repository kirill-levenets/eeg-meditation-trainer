from app.ui.settings_screen import SettingsScreen


def _screen():
    return SettingsScreen()


def test_load_program_populates_without_firing_changed():
    s = _screen()
    changed = []
    s.set_program_changed_callback(lambda segs: changed.append(segs))
    segs = [{"minutes": 10, "target": 50, "formula": "shamatha_score"},
            {"minutes": 5, "target": 70, "formula": "meditation_score"}]
    s.load_program(segs, "program")
    assert changed == []                      # programmatic load must NOT fire changed
    assert s.get_program_segments() == segs   # editor round-trips the segments
    assert s.program_mode == "program"


def test_add_segment_fires_changed():
    s = _screen()
    changed = []
    s.set_program_changed_callback(lambda segs: changed.append(segs))
    s.load_program([], "program")
    s._add_segment_row()
    assert len(changed) >= 1
    assert len(changed[-1]) == 1


def test_set_program_mode_does_not_fire_callback():
    s = _screen()
    seen = []
    s.set_program_mode_callback(lambda m: seen.append(m))
    s.set_program_mode("program")
    assert seen == []                          # programmatic set is silent
    assert s.program_mode == "program"


def test_set_saved_programs_populates_list():
    s = _screen()
    s.set_saved_programs([{"name": "Ramp", "segments": []},
                          {"name": "Steps", "segments": []}])
    assert len(s._saved_programs_box.children) == 2


def test_custom_formula_segment_roundtrips():
    s = _screen()
    seg = {"minutes": 8, "target": 120, "formula": {"name": "Foo", "formula": "alpha1"}}
    s.load_program([seg], "program")
    assert s.get_program_segments() == [seg]


def test_set_feedback_source_does_not_fire_callback():
    s = _screen()
    fired = []
    s.set_feedback_source_callback(lambda src, path: fired.append((src, path)))
    s.set_feedback_source("custom", "/tmp/x.wav")  # restore -> silent
    assert fired == []
    s._on_feedback_source_pressed(s._feedback_source_buttons["tone"])  # user action -> fires
    assert fired == [("tone", "/tmp/x.wav")]


def test_segment_feedback_sound_roundtrips():
    s = _screen()
    segs = [
        {"minutes": 10, "target": 50, "formula": "shamatha_score", "feedback_sound": "tone"},
        {"minutes": 5, "target": 70, "formula": "meditation_score"},   # default -> omitted
    ]
    s.load_program(segs, "program")
    out = s.get_program_segments()
    assert out[0].get("feedback_sound") == "tone"
    assert "feedback_sound" not in out[1]   # Default is not serialized


def test_custom_press_opens_chooser_when_no_path(monkeypatch):
    import app.ui.settings_screen as ss
    calls = []
    monkeypatch.setattr(ss, "open_audio_file_chooser", lambda *a, **k: calls.append(a))
    s = _screen()
    s.set_feedback_source("noise", "")
    s._on_feedback_source_pressed(s._feedback_source_buttons["custom"])
    assert len(calls) == 1, "tapping Custom with no file should open the chooser"


def test_custom_press_no_chooser_when_path_set(monkeypatch):
    import app.ui.settings_screen as ss
    calls = []
    monkeypatch.setattr(ss, "open_audio_file_chooser", lambda *a, **k: calls.append(a))
    s = _screen()
    s.set_feedback_source("custom", "/tmp/x.wav")     # already configured
    s._on_feedback_source_pressed(s._feedback_source_buttons["custom"])
    assert calls == [], "re-tapping Custom with a file already set must not reopen the chooser"


def test_rain_press_does_not_open_chooser(monkeypatch):
    import app.ui.settings_screen as ss
    calls = []
    monkeypatch.setattr(ss, "open_audio_file_chooser", lambda *a, **k: calls.append(a))
    s = _screen()
    s._on_feedback_source_pressed(s._feedback_source_buttons["noise"])
    assert calls == []
