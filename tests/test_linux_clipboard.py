"""The first text input never waits on a clipboard command: Kivy picks a Linux clipboard by running xclip or xsel and
waits on them with no timeout, and one waiting on stdin or on the X selection hung the app at startup (#118)."""
import os
import pathlib
import signal
import subprocess
import sys

import pytest

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
        proc.communicate()
        pytest.fail("building the first text input waited on a clipboard command")
    assert b"picked ClipboardSDL2 None" in out, out.decode(errors="replace")[-2000:]
    assert b"picked its clipboard before" not in out
