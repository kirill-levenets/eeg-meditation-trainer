"""A session loads without the screen: no module of app/session imports Kivy or app.ui at import time, directly or
through what it imports, so it can be built without a widget."""
import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_session_package_loads_no_kivy_and_no_screen_module():
    modules = sorted(f"app.session.{p.stem}" for p in (_ROOT / "app" / "session").glob("*.py") if p.stem != "__init__")
    assert "app.session.running_session" in modules
    probe = (f"import importlib, sys\nfor m in {modules!r}:\n    importlib.import_module(m)\n"
             "print('\\n'.join(sorted(k for k in sys.modules if k.split('.')[0] == 'kivy' or k.startswith('app.ui'))))")
    child = subprocess.run([sys.executable, "-c", probe], cwd=_ROOT, capture_output=True, text=True, timeout=60)
    assert child.returncode == 0, child.stderr
    assert child.stdout.split() == []
