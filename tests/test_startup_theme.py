"""The UI is built in the theme the startup profile will apply, so a launch never builds in one palette and repaints."""

from app.storage.database import DatabaseManager
from app.ui.app_manager import startup_theme, theme_seed
from app.ui.theme import DEFAULT_THEME


def _db(tmp_path) -> DatabaseManager:
    return DatabaseManager(db_path=str(tmp_path / "t.db"))


def test_the_startup_profiles_own_theme_wins(tmp_path):
    db = _db(tmp_path)
    uid = db.create_user("a")
    db.set_setting("last_user_id", str(uid))
    db.set_setting("theme", "Dark Green")  # the legacy global setting
    db.set_user_setting(uid, "theme", "Light Cream")
    assert startup_theme(db) == "Light Cream"
    db.close()


def test_a_profile_without_a_theme_gets_the_global_seed(tmp_path):
    db = _db(tmp_path)
    uid = db.create_user("a")
    db.set_setting("last_user_id", str(uid))
    db.set_setting("theme", "Dark Green")
    assert startup_theme(db) == theme_seed(db) == "Dark Green"
    db.close()


def test_no_startup_profile_or_an_unknown_name_falls_back_to_the_seed(tmp_path):
    db = _db(tmp_path)
    assert startup_theme(db) == theme_seed(db) == DEFAULT_THEME  # fresh install: the gate opens, no profile yet
    uid = db.create_user("a")
    db.set_setting("last_user_id", str(uid))
    db.set_user_setting(uid, "theme", "No Such Theme")
    db.set_setting("theme", "Also Unknown")
    assert startup_theme(db) == DEFAULT_THEME
    db.close()


def test_a_profile_with_an_unknown_stored_theme_gets_the_seed_not_the_previous_profiles(tmp_path):
    from app.settings.registry import SettingsStore
    from app.ui.app_manager import theme_setting
    from app.ui.theme import C

    db = _db(tmp_path)
    uid = db.create_user("b")
    db.set_user_setting(uid, "theme", "No Such Theme")
    saved = C.theme_name
    try:
        C.set_theme("Light Green")  # the previous profile's theme
        SettingsStore(db, [theme_setting("Dark Blue")]).load(uid)
        assert C.theme_name == "Dark Blue"
    finally:
        C.set_theme(saved)
        db.close()
