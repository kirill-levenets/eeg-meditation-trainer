"""The foreground service's start and stop state (android_src/…/ServiceStartState.java), compiled and run with javac:
a stop before startForeground crashes the app, so every transition is checked, not read."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path("org/eeg/eegmeditation")


@pytest.mark.skipif(not (shutil.which("javac") and shutil.which("java")), reason="needs a JDK")
def test_the_service_state_follows_its_transition_table(tmp_path):
    sources = [ROOT / "android_src" / PACKAGE / "ServiceStartState.java",
               ROOT / "tests" / "java" / PACKAGE / "ServiceStartStateTest.java"]
    built = subprocess.run(["javac", "-d", str(tmp_path), *map(str, sources)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    run = subprocess.run(["java", "-cp", str(tmp_path), "org.eeg.eegmeditation.ServiceStartStateTest"],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("OK ")


def test_the_service_keeps_its_state_in_the_tested_class():
    service = (ROOT / "android_src" / PACKAGE / "SessionForegroundService.java").read_text()
    assert "STATE.starting()" in service and "STATE.stop()" in service and "STATE.wentForeground()" in service
    assert "synchronized" not in service  # the state lives in ServiceStartState, where the test reaches it
