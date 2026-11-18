"""The built-in sounds are generated once and kept in a folder of their own: a launch generates only what is missing."""
import hashlib
import inspect
import os

import pytest

import app.audio_feedback.noise as noise
import app.storage.fileops as fileops
from app.audio_feedback.noise import AudioEngine
from app.config import APP

# The generators' version and the digest of their source and of the sounds' file names (their arguments): a sound
# kept by an earlier launch is reused by its name, and only another version's files are removed.
_PINNED = (1, "6fb03aaaac9ae5d0613705c935cc4fbbbd2877b51117430cf7283cd329252ebc")

_AT_LAUNCH = ["_generate_bell_wav", "_generate_bell_wav", "_generate_chime_wav", "_generate_disconnect_wav",
              "_generate_noise_wav"]


def _generators() -> list[str]:
    return [name for name in vars(noise) if name.startswith("_generate_") and name.endswith("_wav")]


@pytest.fixture
def generated(tmp_path, monkeypatch):
    """A sounds folder of the test's own; the list of the generators called, each returning a few samples."""
    monkeypatch.setattr(APP, "BUILT_IN_SOUNDS_DIR", str(tmp_path / "sounds"))
    calls = []
    for name in _generators():
        monkeypatch.setattr(noise, name, lambda *args, name=name: calls.append(name) or b"\x01\x00" * 8)
    return calls


def _files() -> list[str]:
    return sorted(os.listdir(APP.BUILT_IN_SOUNDS_DIR))


def test_the_tests_sounds_are_not_kept_in_the_apps_folder():
    assert APP.BUILT_IN_SOUNDS_DIR != type(APP).BUILT_IN_SOUNDS_DIR


def test_the_first_launch_generates_the_sounds_and_the_next_none(generated):
    first = AudioEngine()
    assert sorted(generated) == _AT_LAUNCH
    paths = [first._kept("noise"), first._kept("bell"), first._kept("timer_bell"), first._kept("chime"), first._kept("disconnect")]
    assert sorted(paths) == [os.path.join(APP.BUILT_IN_SOUNDS_DIR, file) for file in _files()]
    first.cleanup()  # closing the app keeps them
    del generated[:]
    second = AudioEngine()
    assert generated == [] and second._kept("noise") == first._kept("noise") and len(_files()) == 5


def test_the_generated_sounds_are_wav_files_a_player_opens(tmp_path, monkeypatch):
    monkeypatch.setattr(APP, "BUILT_IN_SOUNDS_DIR", str(tmp_path / "sounds"))
    engine = AudioEngine()
    seconds = {engine._kept("noise"): 10, engine._kept("bell"): APP.BELL_DURATION,
               engine._kept("timer_bell"): APP.TIMER_BELL_DURATION, engine._kept("chime"): APP.CHIME_DURATION,
               engine._kept("disconnect"): APP.DISCONNECT_DURATION}
    for path, length in seconds.items():
        with noise.wave.open(path, "rb") as wav:
            assert wav.getnframes() == int(APP.WHITE_NOISE_SAMPLE_RATE * length), path
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (APP.WHITE_NOISE_SAMPLE_RATE, 1, 2)


def test_a_missing_sound_is_generated_again(generated):
    bell = AudioEngine()._kept("bell")
    os.remove(bell)
    del generated[:]
    AudioEngine()
    assert generated == ["_generate_bell_wav"] and os.path.exists(bell)


@pytest.mark.parametrize("kind, generator", [("tone", "_generate_tone_wav"), ("heartbeat", "_generate_heartbeat_wav")])
def test_a_loop_few_sessions_play_is_generated_on_its_first_use_and_kept(generated, kind, generator):
    engine = AudioEngine()
    del generated[:]
    path = engine._feedback_path_for(kind)
    assert generated == [generator] and os.path.exists(path) and kind in os.path.basename(path)
    assert AudioEngine()._feedback_path_for(kind) == path and generated == [generator]


def test_a_sound_shaped_by_other_values_is_another_file(generated, monkeypatch):
    bell = AudioEngine()._kept("bell")
    del generated[:]
    monkeypatch.setattr(APP, "BELL_FREQUENCY", APP.BELL_FREQUENCY + 50)
    retuned = AudioEngine()._kept("bell")
    assert retuned != bell and generated == ["_generate_bell_wav"] and os.path.exists(retuned)


def test_the_sounds_of_another_generator_version_are_removed(generated, monkeypatch):
    AudioEngine()
    old = _files()
    being_written = os.path.join(APP.BUILT_IN_SOUNDS_DIR, ".another_launch.part")
    open(being_written, "wb").close()
    os.mkdir(os.path.join(APP.BUILT_IN_SOUNDS_DIR, "not_ours"))
    not_ours = os.path.join(APP.BUILT_IN_SOUNDS_DIR, "not_ours", "a.wav")
    open(not_ours, "wb").close()
    del generated[:]
    monkeypatch.setattr(noise, "_SOUNDS_VERSION", noise._SOUNDS_VERSION + 1)
    AudioEngine()
    assert sorted(generated) == _AT_LAUNCH
    assert len(_files()) == 7 and not set(old) & set(_files())
    assert os.path.exists(being_written) and os.path.exists(not_ours)  # only this folder's own sounds are removed


def test_a_sound_of_another_version_that_cannot_be_removed_is_reported(generated, monkeypatch):
    AudioEngine()
    warned = []
    monkeypatch.setattr(fileops.logger, "warning", warned.append)
    monkeypatch.setattr(fileops.os, "remove", lambda path: (_ for _ in ()).throw(PermissionError(13, "denied", path)))
    monkeypatch.setattr(noise, "_SOUNDS_VERSION", noise._SOUNDS_VERSION + 1)
    AudioEngine()
    assert len(warned) == 5 and all("Could not remove" in message for message in warned)


def test_a_sound_cut_off_while_written_is_not_kept(generated, monkeypatch):
    # A file under the sound's name is played as it is: half of one would be the session's sound from then on.
    def fails(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fileops.os, "fsync", fails)
    with pytest.raises(OSError):
        AudioEngine()
    assert _files() == []


def _names(code) -> set[str]:
    nested = [const for const in code.co_consts if inspect.iscode(const)]
    return set(code.co_names).union(*(_names(inner) for inner in nested))


def _generators_source() -> str:
    """The source of each generator and of the module's functions and numbers it reaches."""
    found, names = {}, set(_generators())
    while names:
        name = names.pop()
        value = vars(noise).get(name)
        if name in found or isinstance(value, bool):
            continue
        if inspect.isfunction(value) and value.__module__ == noise.__name__:
            found[name] = inspect.getsource(value)
            names |= _names(value.__code__)
        elif isinstance(value, (int, float)):
            found[name] = repr(value)
    return "\n".join(f"{name}: {found[name]}" for name in sorted(found))


def test_a_changed_generator_or_argument_takes_a_new_version():
    source = _generators_source()
    assert "_loop_pcm" in source and "_FADE_SAMPLES: 512" in source  # what a generator reaches is followed
    names = sorted(os.path.basename(path).split("-", 1)[1] for path, _ in noise._kept_sounds(APP.WHITE_NOISE_SAMPLE_RATE).values())
    digest = hashlib.sha256("\n".join([source, *names]).encode()).hexdigest()
    assert (noise._SOUNDS_VERSION, digest) == _PINNED, (
        "a generator's source or a sound's arguments changed: if the samples did, bump noise._SOUNDS_VERSION, so "
        f"the sounds kept by the old one are removed, not reused or left; then pin ({noise._SOUNDS_VERSION}, {digest!r}) here")
