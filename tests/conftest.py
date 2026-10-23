import os
import sys

# Tests pump frames themselves (EventLoop.idle loops): Kivy's 60 fps cap would sleep ~12 ms in each.
os.environ.setdefault("KCFG_GRAPHICS_MAXFPS", "0")

import pytest
from kivy import properties

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import APP, METRICS, SIGMOID

# Kivy's 3.12 wheel (Cython < 3.0.3) leaks the traceback of every exception caught inside it, and these Python-2-only
# methods raise AttributeError on each pos/size read; without them Kivy takes the same fallback without raising.
for _cls in (properties.ObservableReferenceList, properties.ObservableList):
    if "__setslice__" in vars(_cls):
        delattr(_cls, "__setslice__")


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
