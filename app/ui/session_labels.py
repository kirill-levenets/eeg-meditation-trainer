"""How a stored session is named and summarized on screen: History's rows and the session detail share it (#49)."""

from datetime import datetime

from app.session.scoring import recorded_score
from app.ui.theme import format_duration


def start_stamp(when: datetime) -> str:
    """'YYYY-MM-DD HH:MM': a session's start in its default name and in its title, so the title can recognise it."""
    return when.strftime("%Y-%m-%d %H:%M")


def _started(session: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(session.get("date_time", "") or "")
    except ValueError:
        return None


def session_label(session: dict) -> str:
    """The name without the session's own start time, which a default name begins with: what the user renames, and
    what the title shows after the time. A time the user typed is part of the name."""
    name = session.get("session_name", "") or ""
    started = _started(session)
    if started is not None:
        # "YYYY-MM-DD HH:MM - " now, "HH:MM - " in older sessions; both made with the row's date_time.
        for prefix in (f"{start_stamp(started)} - ", f"{started:%H:%M} - "):
            if name.startswith(prefix):
                return name[len(prefix):]
    return name


def session_title(session: dict) -> str:
    """'YYYY-MM-DD HH:MM - name': every session says when it ran, whatever it was named."""
    started = _started(session)
    when = start_stamp(started) if started is not None else session.get("date_time", "") or ""
    label = session_label(session)
    return f"{when} - {label}" if label else when


def session_stats_line(session: dict) -> str:
    """The metric the session was scored on and its average, the duration, the longest streak. A session that saved
    no metric (before #51) keeps its old line, average shamatha and the duration: its streak was measured on
    meditation, so it isn't shown next to a shamatha average."""
    duration = format_duration(int(session.get("duration", 0) or 0))
    score = recorded_score(session)
    if score is None:
        return f"Shamatha {session.get('avg_shamatha', 0) or 0:.0f} · {duration}"
    _key, name, avg = score
    # No average for a program (one metric per segment, on different scales) or a session with no scored tick.
    parts = [name if avg is None else f"{name} {avg:.0f}", duration]
    streak = int(session.get("longest_streak", 0) or 0)
    if streak:
        parts.append(f"Streak {format_duration(streak)}")
    return " · ".join(parts)


def session_notes_line(session: dict) -> str:
    """The notes' first line with text, or '' when there are none."""
    return next((line.strip() for line in (session.get("notes") or "").splitlines() if line.strip()), "")


def session_threshold_row(session: dict) -> tuple[str, str]:
    """(label, value) of the row above Time Above Threshold and Longest Streak: what they were measured against — the
    saved metric and its threshold, or a program, whose segments have their own. A session that saved no metric keeps
    its old Threshold Used row."""
    threshold = session.get("threshold_used", 0) or 0
    score = recorded_score(session)
    if score is None:
        return "Threshold Used", str(threshold)
    key, name, _avg = score
    if key == "program":
        return "Scored on", name if name == "Program" else f"{name} (program)"
    return "Scored on", f"{name} \u2265 {threshold}"
