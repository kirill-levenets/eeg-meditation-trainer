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


def test_maybe_migrate_desktop_db_copies_old_to_new(tmp_path):
    from app.config import _maybe_migrate_desktop_db

    old_dir = tmp_path / "old_install"
    new_dir = tmp_path / "user_data"
    old_dir.mkdir()
    new_dir.mkdir()
    old_db = old_dir / "meditation.db"
    old_db.write_bytes(b"SQLITE-FAKE")

    _maybe_migrate_desktop_db(new_dir=str(new_dir), legacy_dirs=[str(old_dir)])

    new_db = new_dir / "meditation.db"
    assert new_db.exists()
    assert new_db.read_bytes() == b"SQLITE-FAKE"
    # Old left in place (rollback path)
    assert old_db.exists()


def test_maybe_migrate_desktop_db_skips_when_new_exists(tmp_path):
    from app.config import _maybe_migrate_desktop_db

    old_dir = tmp_path / "old_install"
    new_dir = tmp_path / "user_data"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "meditation.db").write_bytes(b"OLD")
    (new_dir / "meditation.db").write_bytes(b"NEW")

    _maybe_migrate_desktop_db(new_dir=str(new_dir), legacy_dirs=[str(old_dir)])

    assert (new_dir / "meditation.db").read_bytes() == b"NEW"


def test_maybe_migrate_desktop_db_queues_error_on_permission_error(monkeypatch, tmp_path):
    from app import crash_handler
    from app.config import _maybe_migrate_desktop_db

    old_dir = tmp_path / "old_install"
    new_dir = tmp_path / "user_data"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "meditation.db").write_bytes(b"OLD")

    crash_handler._PRE_APP_ERRORS.clear()

    def boom(src, dst):
        raise PermissionError("denied")

    monkeypatch.setattr("shutil.copy2", boom)
    _maybe_migrate_desktop_db(new_dir=str(new_dir), legacy_dirs=[str(old_dir)])

    assert len(crash_handler._PRE_APP_ERRORS) == 1
    label, detail = crash_handler._PRE_APP_ERRORS[0]
    assert label == "db_migration_desktop"
    assert "denied" in detail
