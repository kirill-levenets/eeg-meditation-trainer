import functools
import os
import sys
import tempfile

# Tests pump frames themselves (EventLoop.idle loops): Kivy's 60 fps cap would sleep ~12 ms in each.
os.environ.setdefault("KCFG_GRAPHICS_MAXFPS", "0")

import pytest
from kivy import properties

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.audio_feedback import noise
from app.config import APP, METRICS, SIGMOID

# Python-2-only methods that raise on every pos/size read; Kivy's 3.12 wheel leaks each caught exception's traceback.
for _cls in (properties.ObservableReferenceList, properties.ObservableList):
    if "__setslice__" in vars(_cls):
        delattr(_cls, "__setslice__")

# The app builds one AudioEngine; tests build many, each synthesizing the same sounds again.
_synthesizers = [name for name in vars(noise) if name.startswith("_generate_") and name.endswith("_wav")]
assert _synthesizers, "noise has no _generate_*_wav left to cache: update the pattern"
for _name in _synthesizers:
    setattr(noise, _name, functools.cache(getattr(noise, _name)))


def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", help="also run the tests marked slow (before every push)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long checks that run only with --run-slow")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip = pytest.mark.skip(reason="slow: run with --run-slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True, scope="session")
def _temp_files_in_basetemp(tmp_path_factory):
    """Temp files the code under test leaves (each AudioEngine's sound folder) go to pytest's rotated basetemp."""
    saved = tempfile.tempdir
    tempfile.tempdir = str(tmp_path_factory.mktemp("tmp"))
    yield
    tempfile.tempdir = saved


@pytest.fixture(autouse=True)
def _restore_config():
    """A test that changes the global config (APP.USE_MOCK_DEVICE, a threshold) must not leave it to the next file."""
    saved = [(cfg, dict(vars(cfg))) for cfg in (APP, METRICS, SIGMOID)]
    yield
    for cfg, attrs in saved:
        for key in set(vars(cfg)) - set(attrs):
            delattr(cfg, key)
        for key, value in attrs.items():
            setattr(cfg, key, value)
