import os
import sys


def test_resolve_desktop_base_dir_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from app.config import _resolve_desktop_base_dir
    base = _resolve_desktop_base_dir()
    assert base == os.path.join(str(tmp_path), "EEGMeditation")
    assert os.path.isdir(base)


def test_resolve_desktop_base_dir_linux_no_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path)) if p.startswith("~") else p)
    from app.config import _resolve_desktop_base_dir
    base = _resolve_desktop_base_dir()
    assert base == os.path.join(str(tmp_path), ".local", "share", "EEGMeditation")
    assert os.path.isdir(base)


def test_resolve_desktop_base_dir_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from app.config import _resolve_desktop_base_dir
    base = _resolve_desktop_base_dir()
    assert base == os.path.join(str(tmp_path), "EEGMeditation")


def test_resolve_desktop_base_dir_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path)) if p.startswith("~") else p)
    from app.config import _resolve_desktop_base_dir
    base = _resolve_desktop_base_dir()
    assert base == os.path.join(str(tmp_path), "Library", "Application Support", "EEGMeditation")
