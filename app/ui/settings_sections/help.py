"""Settings → Help & Troubleshooting: the help topics, from app/assets/help/ in the device's language."""

import os
import re

from kivy.metrics import dp

from app import android_jni
from app.logger import logger
from app.ui.theme import C, Divider, F, ThemedLabel, fit_height_to_text, text_wraps_at_width

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "help")
_HELP_FILE_LANG = {"uk": "ua"}  # the help files' suffix where it isn't the ISO 639 code


def help_language() -> str:
    """The first wanted language with a help file, else English: Android's locale, or LANGUAGE's list in order and then
    the first of LC_ALL / LC_MESSAGES / LANG (Windows and macOS builds usually set none of these)."""
    try:
        if android_jni.on_android():
            wanted = [android_jni.language()]
        else:
            first_set = next((os.environ[v] for v in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(v)), "")
            wanted = [*os.environ.get("LANGUAGE", "").split(":"), first_set]
    except Exception:  # noqa: BLE001 - the help falls back to English rather than break the Settings screen
        logger.exception("Device language lookup failed; help in English")
        wanted = []
    for tag in wanted:
        code = re.match(r"[A-Za-z]*", tag).group().lower()
        code = _HELP_FILE_LANG.get(code, code)
        if code and os.path.exists(os.path.join(HELP_DIR, f"help_{code}.txt")):
            return code
    return "en"


def load_help_topics(lang: str = "en") -> list[tuple[str, str]]:
    """The (title, body) topics of help_{lang}.txt, English when it has none: its sections start at '## Title' lines."""
    path = os.path.join(HELP_DIR, f"help_{lang}.txt")
    if not os.path.exists(path):
        path = os.path.join(HELP_DIR, "help_en.txt")
    if not os.path.exists(path):
        return [("Help", "Help file not found")]
    topics: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("## "):
                if current_title:
                    topics.append((current_title, "\n".join(current_body).strip()))
                current_title = line[3:].strip()
                current_body = []
            else:
                current_body.append(line.rstrip())
    if current_title:
        topics.append((current_title, "\n".join(current_body).strip()))
    return topics


class HelpSection:
    """Builds the section's content into `section`: each topic's title, its text and a divider."""

    def __init__(self, section) -> None:
        for title, text in load_help_topics(help_language()):
            title_label = ThemedLabel(text=f"[b]{title}[/b]", markup=True, font_size=F.BODY, color=C.PRIMARY,
                                      size_hint_y=None, height=dp(24), halign="left")
            text_wraps_at_width(title_label)
            section.add_widget(title_label)
            body = ThemedLabel(text=text, font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint_y=None, halign="left",
                               valign="top")
            fit_height_to_text(body, extra=dp(8))
            section.add_widget(body)
            section.add_widget(Divider())
