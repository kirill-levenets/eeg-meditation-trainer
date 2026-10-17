"""Custom sound files on Android (#96): every sound picker opens the system picker for audio, never Kivy's file
browser (an app can't list /data, or shared storage by path); the picked file is copied into app storage under its own
name, and the copy's path is what plays and is saved. The desktop keeps Kivy's browser."""

import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from kivy.clock import Clock

import app.storage.android_saf as saf
import app.ui.settings_sections.common as common
from app.config import APP
from app.ui.settings_screen import SettingsScreen

BOWL = "content://com.android.providers.media.documents/document/audio%3A41"
RAIN = "content://com.android.providers.downloads.documents/document/77"


@pytest.fixture
def phone(monkeypatch, tmp_path):
    """Android, with a document picker that returns what `picks` holds and a provider serving `files`."""
    monkeypatch.setattr(saf, "_IS_ANDROID", True)
    monkeypatch.setattr(APP, "DB_PATH", str(tmp_path / "EEGMeditation" / "meditation.db"))
    monkeypatch.setattr(common, "ThemedFileChooser", lambda *a, **k: pytest.fail("Kivy's file browser opened on Android"))
    state = {"picks": [], "launched": [], "files": {BOWL: ("Singing bowl.mp3", b"ID3 bowl"),
                                                     RAIN: ("Singing bowl.mp3", b"ID3 rain")}}

    def open_document(on_result, mime_types=("*/*",)):
        state["launched"].append(mime_types)
        on_result(state["picks"].pop(0))

    def read_uri_to_file(uri, dst):
        Path(dst).write_bytes(state["files"][uri][1])
        return True

    monkeypatch.setattr(saf, "open_document", open_document)
    monkeypatch.setattr(saf, "read_uri_to_file", read_uri_to_file)
    monkeypatch.setattr(saf, "query_display_name", lambda uri: state["files"][uri][0])
    monkeypatch.setattr(saf, "query_extension", lambda uri: "mp3")
    return state


def _settle(done, seconds: float = 3.0) -> None:
    """Run the main loop until `done()`: the copy runs on a thread and hands its path back through the Clock."""
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        Clock.tick()
        time.sleep(0.01)


def _pick(uri, phone, seconds: float = 3.0) -> list[str]:
    """Pick `uri` through the shared sound picker: the paths it hands back."""
    phone["picks"].append(uri)
    got: list[str] = []
    common.open_audio_file_chooser(got.append)
    _settle(lambda: got, seconds)
    return got


def _sounds() -> Path:
    return Path(APP.DB_PATH).parent / "sounds"


def _segment_custom_file(screen, monkeypatch):
    """A program segment's feedback picker, choosing Custom file..."""
    rows = []
    monkeypatch.setattr(common, "make_scroll_popup", lambda title, buttons, **k: rows.extend(buttons) or Mock())
    screen.timer._open_segment_feedback_picker(screen.timer._segment_rows[0], screen.timer._segment_rows[0]._feedback_btn)
    next(b for b in rows if b.text == "Custom file...").dispatch("on_release")


def test_every_sound_picker_opens_the_system_picker_for_audio(phone, monkeypatch):
    screen = SettingsScreen()
    screen.timer.load_program([{"minutes": 10, "target": 50, "formula": "shamatha_score"}], "program")
    segment = screen.timer._segment_rows[0]
    for opener, picked in ((lambda: screen.audio._choose_feedback_source("custom"), lambda: screen.audio._feedback_sound_path),
                           (lambda: screen.audio._choose_reward_source("custom"), lambda: screen.audio._reward_sound_path),
                           (lambda: screen.timer._choose_timer_sound("custom"), lambda: screen.timer.timer_sound_path),
                           (lambda: _segment_custom_file(screen, monkeypatch), lambda: segment._feedback_sound)):
        phone["picks"].append(BOWL)
        opener()
        _settle(picked)
    assert phone["launched"] == [common._AUDIO_TYPES] * 4 and common._AUDIO_TYPES[0] == "audio/*"
    assert (screen.audio._feedback_sound_path == screen.audio._reward_sound_path == screen.timer.timer_sound_path
            == segment._feedback_sound)
    assert screen.audio._feedback_source_btn.text == "Custom: Singing bowl.mp3"


def test_a_picked_sound_is_copied_into_app_storage_under_its_own_name(phone):
    [path] = _pick(BOWL, phone)
    assert Path(path).name == "Singing bowl.mp3" and Path(path).read_bytes() == b"ID3 bowl"
    assert Path(path).is_relative_to(_sounds())


def test_two_sounds_sharing_a_name_keep_their_own_bytes_and_one_picked_twice_is_stored_once(phone):
    [bowl] = _pick(BOWL, phone)
    [rain] = _pick(RAIN, phone)
    [again] = _pick(BOWL, phone)
    assert bowl != rain and again == bowl
    assert Path(bowl).read_bytes() == b"ID3 bowl" and Path(rain).read_bytes() == b"ID3 rain"
    assert sorted(p.name for p in _sounds().rglob("*") if p.is_file()) == ["Singing bowl.mp3"] * 2


def test_a_cancelled_pick_changes_nothing(phone):
    assert _pick(None, phone, seconds=0.3) == []
    assert not _sounds().exists() or not any(_sounds().iterdir())


def _refused(uri, dst):
    Path(dst).write_bytes(b"ID3")
    return False


def _broken(uri, dst):
    Path(dst).write_bytes(b"ID3")
    raise OSError("the provider closed the stream")


@pytest.mark.parametrize("read", [_refused, _broken])
def test_a_sound_that_cannot_be_read_is_reported_and_leaves_nothing_behind(phone, monkeypatch, read):
    reports = []
    monkeypatch.setattr(saf, "read_uri_to_file", read)
    monkeypatch.setattr(common, "report_soft_error", lambda label, detail="", **k: reports.append(label))
    assert _pick(BOWL, phone) == []
    assert reports == ["sound_pick_failed"]
    assert [p for p in _sounds().rglob("*") if p.is_file()] == []


def test_a_name_from_the_provider_never_leaves_the_sounds_folder(phone):
    phone["files"][BOWL] = ("../../meditation.db", b"ID3 bowl")
    [path] = _pick(BOWL, phone)
    assert Path(path).name == "meditation.db" and Path(path).parent.parent == _sounds()
    assert not (Path(APP.DB_PATH)).exists()


def test_the_desktop_keeps_kivys_file_browser(monkeypatch):
    monkeypatch.setattr(saf, "_IS_ANDROID", False)
    monkeypatch.setattr(saf, "open_document", lambda *a, **k: pytest.fail("the document picker opened on the desktop"))
    opened = []
    monkeypatch.setattr(common.ThemedPopup, "open", lambda popup, *a, **k: opened.append(popup))
    common.open_audio_file_chooser(lambda p: None)
    [popup] = opened
    [chooser] = [w for w in popup.content.walk() if isinstance(w, common.ThemedFileChooser)]
    assert os.path.isdir(chooser.path)


def test_the_last_pick_is_the_one_that_stays(phone, monkeypatch):
    held = threading.Event()
    fast_read = saf.read_uri_to_file

    def slow_bowl(uri, dst):
        if uri == BOWL:
            held.wait(3)
        return fast_read(uri, dst)

    monkeypatch.setattr(saf, "read_uri_to_file", slow_bowl)
    got: list[str] = []
    phone["picks"] += [BOWL, RAIN]
    common.open_audio_file_chooser(got.append)  # a slow copy (a cloud file)
    common.open_audio_file_chooser(got.append)  # then the user picks another
    _settle(lambda: False, 0.3)
    held.set()
    _settle(lambda: len(got) == 2)
    assert [Path(p).read_bytes() for p in got] == [b"ID3 bowl", b"ID3 rain"]


def test_a_name_the_provider_cannot_give_falls_back_and_keeps_the_copy(phone, monkeypatch):
    def no_name(uri):
        raise OSError("the provider refused the query")

    monkeypatch.setattr(saf, "query_display_name", no_name)
    [path] = _pick(BOWL, phone)
    assert Path(path).name == "sound.mp3" and Path(path).read_bytes() == b"ID3 bowl"


def test_a_name_without_an_extension_takes_one_from_the_files_type(phone, monkeypatch):
    phone["files"][BOWL] = ("Evening bowl", b"OggS bowl")
    monkeypatch.setattr(saf, "query_extension", lambda uri: "ogg")
    [path] = _pick(BOWL, phone)
    assert Path(path).name == "Evening bowl.ogg"


def test_a_copy_cut_off_by_the_app_being_killed_is_cleared_by_the_next_one(phone):
    _sounds().mkdir(parents=True)
    (_sounds() / ".incoming.part").write_bytes(b"ID3 half a fi")
    _pick(BOWL, phone)
    assert [p.name for p in _sounds().rglob("*.part")] == []


def test_a_failing_callback_does_not_stop_later_imports(phone):
    def broken(path):
        raise RuntimeError("a callback bug")

    got: list[str] = []
    phone["picks"] += [BOWL, RAIN]
    saf.open_document(lambda uri: saf.import_document(uri, str(_sounds()), "sound", broken))
    saf.open_document(lambda uri: saf.import_document(uri, str(_sounds()), "sound", got.append))
    _settle(lambda: got)
    assert [Path(p).read_bytes() for p in got] == [b"ID3 rain"]


def test_every_sound_picker_has_a_cancel_that_picks_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(common, "make_scroll_popup", lambda title, rows, footer=None, **k: opened.append(
        (title, footer, Mock())) or opened[-1][2])
    screen = SettingsScreen()
    changes = []
    screen.audio.set_feedback_source_callback(lambda *a: changes.append(a))
    for open_picker in (screen.audio._open_feedback_source_picker, screen.audio._open_reward_source_picker):
        open_picker()
    for title, footer, popup in opened:
        assert footer is not None and footer.text == "Cancel", title
        footer.dispatch("on_release")
        popup.dismiss.assert_called_once()
    assert changes == []
