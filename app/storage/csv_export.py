"""Bundle multiple per-session CSV exports into one ZIP (issue #7)."""
import zipfile


def build_sessions_zip(path: str, session_csvs: dict[int, str]) -> int:
    """Write one `session_<id>.csv` entry per non-empty CSV into a ZIP at `path`.

    Returns the number of entries written. Sessions with empty CSV (no data) are
    skipped; if nothing would be written, no file is created and 0 is returned.
    """
    entries = {sid: csv for sid, csv in session_csvs.items() if csv}
    if not entries:
        return 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for sid, csv in entries.items():
            z.writestr(f"session_{sid}.csv", csv)
    return len(entries)
