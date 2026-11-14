"""The app made by its real constructor and build(), as main.py makes it, on a temp DB: the startup profile is restored,
or the gate blocks the app until one is made; the screens' hooks reach their flows, and each profile's settings come
back."""
from kivy.core.window import Window

from app.config import APP
from app.ui.widgets.user_picker import UserPickerForm
from tests._app import frames, frames_until, last_used, runner_alive, tap
from tests._picker import picker_rows


def _create(form: UserPickerForm, name: str) -> None:
    form._name_input.text = name
    form._on_create_pressed()


def test_the_built_app_restores_its_profile_and_the_hooks_reach_their_flows(build_app):
    app = build_app(last_used("me"))
    uid = app._current_user_id
    assert uid is not None and not app._gate.shown() and not app._bottom_nav.disabled
    tap(app._history_screen._toggle_col, "14d")  # History -> HistoryFlow -> the profile's setting
    assert app._db.get_user_setting(uid, "history_view_mode") == "bars"
    audio = app._settings_screen.audio
    audio._sinking_alert_cb.active = True  # Settings -> the settings store, through the real descriptors
    audio._subtle_alert_cb.active = True
    app._settings_screen.display.on_rotate_screen(90)
    assert app._db.get_user_setting(uid, "subtle_alert") == "True" and app._db.get_user_setting(uid, "rotation") == "90"
    form = app._settings_screen._user_picker_form
    _create(form, "other")  # Settings -> Profiles
    other = next(u["id"] for u in app._db.get_all_users() if u["name"] == "other")
    _create(form, "other")
    assert "already exists" in form._error_label.text and len(app._db.get_all_users()) == 2
    app._profiles.on_switch(other)
    frames()
    assert app._history_screen._view_mode == "calendar" and not audio._sinking_alert_cb.active
    assert not audio._subtle_alert_cb.active and Window.rotation == 0
    app._profiles.on_switch(uid)
    frames()
    assert app._history_screen._view_mode == "bars" and audio._sinking_alert_cb.active
    assert audio._subtle_alert_cb.active and Window.rotation == 90


def test_with_no_profile_to_restore_the_gate_blocks_the_app_until_one_is_made(build_app):
    app = build_app(lambda db: db.create_user("old"))  # a profile, but none last used: a restored DB, a reinstall
    assert app._current_user_id is None and app._bottom_nav.disabled  # at once: no tap before the gate is up
    frames_until(app._gate.shown)
    gate_form = next(w for w in app._gate._gate_popup.walk() if isinstance(w, UserPickerForm))
    _create(gate_form, "new")
    frames()
    new = next(u["id"] for u in app._db.get_all_users() if u["name"] == "new")
    assert app._current_user_id == new and not app._gate.shown() and not app._bottom_nav.disabled
    assert app._backup_flow._user_name() == "new"  # the profile a backup is named after


SAVED = ("00:11:22:33:44:55", "MindWave Mobile")  # the profile's headset


def _pick_saved(app) -> None:
    """Its row tapped in Settings › Device (the stream already set to it, as a profile load leaves it)."""
    app._real_stream.set_device(*SAVED)
    app._headset.on_select(*SAVED)


def _mode_writes(app) -> list:
    """Every DB write of `use_mock` from now on, as (uid, value)."""
    writes, put = [], app._db.set_user_setting
    app._db.set_user_setting = lambda uid, key, value: (writes.append((uid, value)) if key == "use_mock" else None,
                                                        put(uid, key, value))[1]
    return writes


def test_a_profile_switch_applies_the_device_mode_without_writing_it(build_app):
    app = build_app(last_used("me"))
    real = app._db.create_user("real")
    app._db.set_user_setting(real, "use_mock", "False")
    writes = _mode_writes(app)
    app._profiles.on_switch(real)
    frames()
    assert APP.USE_MOCK_DEVICE is False and not app._settings_screen.device._device_mode_cb.active
    assert app._settings_store.value("use_mock") is False and writes == []


def test_the_mode_checkbox_and_a_headset_pick_change_the_mode_through_the_store(build_app):
    app = build_app(last_used("me"))
    uid, writes = app._current_user_id, _mode_writes(app)
    app._settings_screen.device._device_mode_cb.active = False  # the user's toggle
    assert APP.USE_MOCK_DEVICE is False and app._settings_store.value("use_mock") is False
    app._settings_screen.device._device_mode_cb.active = True
    app._headset._use_real_device()  # a pick or a scan's find: the checkbox, whose hook is the one writer
    assert APP.USE_MOCK_DEVICE is False and app._settings_store.value("use_mock") is False
    assert writes == [(uid, "False"), (uid, "True"), (uid, "False")]
    app._settings_screen.device._device_mode_cb.active = True
    app._db.set_user_setting(uid, "use_mock", "False")  # a stale row: the batch save (leaving the app) writes the held value
    app._save_user_settings()
    assert app._db.get_user_setting(uid, "use_mock") == "True"


def test_picking_the_saved_headset_while_idle_leaves_the_mock(build_app):
    app = build_app(last_used("me"))
    _pick_saved(app)  # on Mock Data
    assert APP.USE_MOCK_DEVICE is False and app._settings_store.value("use_mock") is False
    assert not app._settings_screen.device._device_mode_cb.active


def test_a_mode_change_during_a_session_is_refused(build_app, monkeypatch):
    app = build_app(last_used("me"))
    said = []
    monkeypatch.setattr(app, "_info_popup", lambda title, message: said.append(title))
    app._on_start()
    frames_until(lambda: len(app._shown.mirror.metrics) >= 1, 5.0)
    label = app._live_screen._device_label
    shown = (label.text, list(label.color))
    app._settings_screen.device._device_mode_cb.active = False
    assert APP.USE_MOCK_DEVICE is True and app._settings_screen.device._device_mode_cb.active
    assert said == ["Session in progress"] and app._settings_store.value("use_mock") is True
    assert (label.text, list(label.color)) == shown  # the refusal repaints nothing
    _pick_saved(app)
    assert said == ["Session in progress"] * 2 and APP.USE_MOCK_DEVICE is True
    assert (label.text, list(label.color)) == shown
    app._stop_and_save()
    frames_until(lambda: app._session.run is None, 2.0)  # its runner saved it; its Ended event tore the screen down
    assert app._db.get_all_sessions(app._current_user_id)[0]["session_name"].endswith("Mock")


def test_a_slider_value_off_by_rounding_applies_its_width_once(build_app, monkeypatch):
    # The setting holds the rounded value; written back onto the slider, it would fire the slider's hook again.
    app = build_app(last_used("me"))
    applied = []
    monkeypatch.setattr(app, "_apply_line_width", applied.append)
    app._settings_screen.display._line_width_slider.value = 1.3000000000000003  # a drag's raw value
    assert applied == [1.3] and app._settings_store.value("line_width") == 1.3
    app._change_setting("line_width", 2.0)  # set from code (a profile's load): the slider follows
    assert app._settings_screen.display._line_width_slider.value == 2.0 and applied[-1] == 2.0


def test_mock_sessions_on_their_real_runner_are_each_saved_once(build_app):
    app = build_app(last_used("me"))
    uid = app._current_user_id
    for n in (1, 2):  # the second Start: a fresh run, ticking
        app._on_start()
        frames_until(lambda: len(app._shown.mirror.metrics) >= 3, 5.0)
        assert runner_alive(app) and len(app._shown.mirror.metrics) >= 3
        app._stop_and_save()  # a command: the runner ends and saves the run, and its Ended event tears the screen down
        frames_until(lambda: app._session.run is None and not runner_alive(app), 2.0)
        assert app._session.run is None and not runner_alive(app) and app._db.count_sessions(uid) == n
        app._shown.on_ok()
        frames()
    assert all(app._db.get_session_metrics(s["id"]) for s in app._db.get_all_sessions(uid))


_DEEP = [{"minutes": 5, "target": 60, "formula": {"name": "Deep", "formula": "alpha1"}},
         {"minutes": 5, "target": 60, "formula": "meditation_score"}]


def _saved_selection(app, keys: list[str]) -> list[str]:
    """The profile's saved live series, applied to the graph as a profile load does."""
    app._db.set_user_json_setting(app._current_user_id, "graph_series_live_metrics", keys)
    app._graph_series.restore(app._current_user_id)
    return keys


def _program_rows(app, monkeypatch) -> list[str]:
    return [row for row in picker_rows(app, monkeypatch) if row.startswith("Program")]


def _start_and_tick(app) -> None:
    app._on_start()
    frames_until(lambda: len(app._shown.mirror.metrics) >= 2, 5.0)


def test_a_program_session_owns_the_live_graph_until_its_ending_derives_the_idle_series(build_app, monkeypatch):
    app = build_app(last_used("me"))
    uid, g = app._current_user_id, app._live_screen.graph
    app._program_settings.segments = [dict(s) for s in _DEEP]
    app._program_settings.on_mode_change("program")  # the idle preview: shown, not listed
    assert g.is_visible("program_formula") and _program_rows(app, monkeypatch) == []
    _start_and_tick(app)
    assert _program_rows(app, monkeypatch) == ["Program: Deep"]
    app._profiles.on_switch(uid)  # the active profile re-picked mid-session: the session keeps its graph
    frames()
    assert g.is_visible("program_formula") and _program_rows(app, monkeypatch) == ["Program: Deep"]
    app._program_settings.on_mode_change("simple")  # Settings > Timer, mid-session
    assert g.is_visible("program_formula")
    app._stop_and_save()
    frames_until(lambda: app._session.run is None, 2.0)
    app._shown.on_ok()
    frames()
    assert g.program_keys == frozenset() and not g.is_visible("program_formula")  # simple mode: the saved selection
    assert not g.is_visible("meditation_score")  # the program's built-in line went with it
    g.set_visible("distraction", True)
    app._graph_series.persist(g)
    assert "distraction" in app._db.get_user_json_setting(uid, "graph_series_live_metrics")
    _start_and_tick(app)  # the next, simple, session
    assert _program_rows(app, monkeypatch) == []
    app._stop_and_save()
    frames_until(lambda: app._session.run is None, 2.0)


def test_a_duration_tap_while_a_program_previews_saves_nothing_of_it(build_app):
    app = build_app(last_used("me"))
    uid = app._current_user_id
    saved = _saved_selection(app, ["shamatha_score", "distraction"])
    app._program_settings.segments = [dict(s) for s in _DEEP]
    app._program_settings.on_mode_change("program")
    app._program_settings.on_duration_preset(20)  # the Session screen's duration: simple mode, the settings saved
    assert app._db.get_user_json_setting(uid, "graph_series_live_metrics") == saved
    assert not app._live_screen.graph.is_visible("program_formula")


def test_a_start_derives_the_idle_series_whatever_an_editor_change_left(build_app, monkeypatch):
    app = build_app(last_used("me"))
    app._program_settings.segments = [dict(s) for s in _DEEP]
    app._program_settings.on_mode_change("program")  # the preview, marked
    app._program_settings.segments = []  # a writer that skipped the derivation: the next Start is a simple session
    _start_and_tick(app)
    assert app._live_screen.graph.program_keys == frozenset() and _program_rows(app, monkeypatch) == []
    app._stop_and_save()
    frames()


def test_an_unrunnable_program_previews_the_saved_selection_and_saves_nothing(build_app):
    app = build_app(last_used("me"))
    uid = app._current_user_id
    saved = _saved_selection(app, ["shamatha_score", "distraction"])
    app._program_settings.segments = [{"minutes": 0, "target": 60, "formula": "meditation_score"}]  # a hand-edited record
    app._program_settings.on_mode_change("program")
    assert not app._program_settings.governs_live_series()
    app._save_user_settings()
    assert app._db.get_user_json_setting(uid, "graph_series_live_metrics") == saved
