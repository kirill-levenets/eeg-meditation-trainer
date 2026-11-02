"""The startup profile and the settings that style every screen: the profile to restore, and the theme, text size and
line colours the UI is built in before that profile's settings load."""
from app.logger import logger
from app.settings.registry import FLOAT, STR, Setting, stored_value
from app.ui.line_colours import DEFAULT as LINE_DEFAULT
from app.ui.line_colours import LINE_COLOURS
from app.ui.line_colours import OPTIONS as LINE_OPTIONS
from app.ui.theme import DEFAULT_THEME, TEXT_SIZES, THEMES, C, F


def resolve_startup_user(db) -> int | None:
    """The uid to restore at startup, or None when the user must be asked: no `last_user_id`, a corrupt one, or a
    deleted user's; each opens the blocking profile gate rather than leave the app usable with no profile (#29)."""
    saved = db.get_setting("last_user_id")
    if not saved:
        return None
    try:
        uid = int(saved)
    except (ValueError, TypeError):
        logger.warning(f"Corrupt last_user_id setting {saved!r} — prompting for user")
        return None
    if uid <= 0:  # not a valid AUTOINCREMENT id — don't rely on get_user(0) missing
        return None
    return uid if db.get_user(uid) else None


def theme_seed(db) -> str:
    """The theme of a profile without its own: the global setting from before themes were per-user, else the
    default."""
    seed = db.get_setting("theme")
    return seed if seed in THEMES else DEFAULT_THEME


def _parse_theme(raw: str) -> str:
    if raw not in THEMES:
        raise ValueError(f"unknown theme {raw!r}")
    return raw


def theme_setting(seed: str) -> Setting:
    """The per-user theme. An unknown stored name loads the seed: set_theme ignores it, which kept the previous
    profile's palette."""
    return Setting("theme", seed, _parse_theme, STR[1], lambda: C.theme_name, C.set_theme)


def _parse_text_size(raw: str) -> float:
    size = float(raw)
    if size not in {scale for scale, _name in TEXT_SIZES}:
        raise ValueError(f"text size {raw!r} isn't on offer")
    return size


def text_size_setting() -> Setting:
    """The per-user text size: loading a profile applies its size to every screen at once."""
    return Setting("text_size", 1.0, _parse_text_size, FLOAT[1], lambda: F.SCALE, F.set_scale)


def _parse_line_colours(raw: str) -> str:
    if raw not in {name for name, _label in LINE_OPTIONS}:
        raise ValueError(f"line colours {raw!r} aren't on offer")
    return raw


def line_colours_setting() -> Setting:
    """The per-user scored line colours: loading a profile redraws every graph in its choice."""
    return Setting("line_colours", LINE_DEFAULT, _parse_line_colours, STR[1], lambda: LINE_COLOURS.name,
                   LINE_COLOURS.set)


def startup_value(db, setting: Setting):
    """The startup profile's value, to build the UI in: its settings load then re-applies it as a no-op."""
    return stored_value(db, resolve_startup_user(db), setting)


def startup_text_size(db) -> float:
    return startup_value(db, text_size_setting())


def startup_theme(db) -> str:
    """The startup profile's theme, else the seed."""
    return startup_value(db, theme_setting(theme_seed(db)))
