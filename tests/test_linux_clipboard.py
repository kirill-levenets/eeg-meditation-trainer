"""The first text input never waits on a clipboard command: Kivy picks a Linux clipboard by running xclip or xsel and
waits on them with no timeout, and one waiting on stdin or on the X selection hung the app at startup (#118)."""
import os
import pathlib
import signal
import subprocess
import sys

import kivy
import pytest

from app.logger import logger
from app.ui import kivy_providers

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The app's own import chain, then the first text input, then which clipboard Kivy picked.
BUILD = ("import app.ui.app_manager\nfrom kivy.uix.textinput import TextInput\nTextInput()\n"
         "from kivy.core.clipboard import Clipboard, CutBuffer\nprint('picked', type(Clipboard).__name__, CutBuffer)")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Kivy probes xclip and xsel on Linux only")
def test_the_first_text_input_never_runs_a_clipboard_command(tmp_path):
    for name in ("xsel", "xclip"):  # stand-ins that never answer, as xsel does with an open stdin
        tool = tmp_path / name
        tool.write_text("#!/bin/sh\nexec sleep 60\n")
        tool.chmod(0o755)
    data = tmp_path / "data" / "EEGMeditation"
    data.mkdir(parents=True)
    (data / "meditation.db").touch()  # an existing DB: the import copies no legacy one in
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
           "XDG_DATA_HOME": str(tmp_path / "data"), "HOME": str(tmp_path)}
    proc = subprocess.Popen([sys.executable, "-c", BUILD], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # the interpreter and the stand-in it waits on
        out, _ = proc.communicate()
        pytest.fail("building the first text input waited on a clipboard command\n"
                    + out.decode(errors="replace")[-2000:])
    assert b"picked ClipboardSDL2 None" in out, out.decode(errors="replace")[-2000:]


@pytest.fixture
def stock_options(monkeypatch):
    """Kivy's own provider options, before the app limits them (no cutbuffer key: every cut buffer may be picked); the
    test's changes are undone after it."""
    monkeypatch.setitem(kivy.kivy_options, "clipboard", ("xsel", "xclip", "sdl2", "dummy"))
    monkeypatch.setitem(kivy.kivy_options, "cutbuffer", ())  # so the undo restores the key's value, or its absence
    monkeypatch.delitem(kivy.kivy_options, "cutbuffer")
    monkeypatch.delitem(sys.modules, "kivy.core.clipboard", raising=False)
    return kivy.kivy_options


def test_on_linux_the_clipboard_is_sdl2_then_kivys_dummy_and_there_is_no_cut_buffer(monkeypatch, stock_options, caplog):
    monkeypatch.setattr(kivy_providers, "kivy_platform", "linux")
    kivy_providers.clipboard_without_commands()
    assert stock_options["clipboard"] == ("sdl2", "dummy")
    assert stock_options["cutbuffer"] == ()
    assert [r for r in caplog.records if r.name == logger.name] == []


def test_a_clipboard_kivy_already_picked_is_logged(monkeypatch, stock_options, caplog):
    monkeypatch.setattr(kivy_providers, "kivy_platform", "linux")
    monkeypatch.setitem(sys.modules, "kivy.core.clipboard", object())
    kivy_providers.clipboard_without_commands()
    assert [r.levelname for r in caplog.records if r.name == logger.name] == ["ERROR"]


@pytest.mark.parametrize("platform", ["android", "win", "macosx"])
def test_other_platforms_keep_kivys_providers(monkeypatch, stock_options, platform):
    monkeypatch.setattr(kivy_providers, "kivy_platform", platform)
    kivy_providers.clipboard_without_commands()
    assert stock_options["clipboard"] == ("xsel", "xclip", "sdl2", "dummy")
    assert "cutbuffer" not in stock_options
