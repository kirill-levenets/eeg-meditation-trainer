"""What more than one History part uses: History's clock and a score's colour."""
import datetime

from app.ui.theme import C


def today() -> datetime.date:
    """History's clock, read through this module wherever History asks for today, so a test sets it in one place."""
    return datetime.date.today()


def score_colour(score: float):
    """A day's or a session's colour by its average score: the card's for none, dim blue at 0 to bright green at 100."""
    if score <= 0:
        return C.BG_CARD
    t = min(score / 100.0, 1.0)
    r = 0.12 + (0.20 - 0.12) * (1 - t) + (0.25 * t)
    g = 0.18 + (0.85 - 0.18) * t
    b = 0.30 + (0.55 - 0.30) * (1 - t) * (1 - t)
    return (r, g, b, 1.0)
