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
