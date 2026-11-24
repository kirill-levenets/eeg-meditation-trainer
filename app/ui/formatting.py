"""Text the UI shows for numbers: a duration, a count with its noun. Kivy-free."""


def format_duration(seconds: int) -> str:
    """Human-friendly duration: seconds if <1m, minutes if <1h, hours otherwise."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m"


def format_count(n: int, noun: str) -> str:
    """'1 session', '3 sessions': a count with its noun (a regular one, plural + s), singular for one."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
