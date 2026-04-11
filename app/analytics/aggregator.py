from datetime import datetime, timedelta

from app.storage.database import DatabaseManager


class AnalyticsAggregator:
    """Aggregates session data for trend analysis and long-term analytics."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db: DatabaseManager = db

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        """Get daily aggregated stats for the last N days."""
        end = datetime.now()
        start = end - timedelta(days=days)
        sessions = self._db.get_sessions_in_range(
            start.isoformat(), end.isoformat()
        )
        return self._aggregate_by_period(sessions, "day")

    def get_weekly_stats(self, weeks: int = 12) -> list[dict]:
        """Get weekly aggregated stats for the last N weeks."""
        end = datetime.now()
        start = end - timedelta(weeks=weeks)
        sessions = self._db.get_sessions_in_range(
            start.isoformat(), end.isoformat()
        )
        return self._aggregate_by_period(sessions, "week")

    def get_monthly_stats(self, months: int = 12) -> list[dict]:
        """Get monthly aggregated stats for the last N months."""
        end = datetime.now()
        start = end - timedelta(days=months * 30)
        sessions = self._db.get_sessions_in_range(
            start.isoformat(), end.isoformat()
        )
        return self._aggregate_by_period(sessions, "month")

    def _aggregate_by_period(
        self, sessions: list[dict], period: str
    ) -> list[dict]:
        """Group sessions by period and compute averages."""
        buckets: dict[str, list[dict]] = {}

        for s in sessions:
            dt = datetime.fromisoformat(s["date_time"])
            if period == "day":
                key = dt.strftime("%Y-%m-%d")
            elif period == "week":
                key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
            else:
                key = dt.strftime("%Y-%m")

            if key not in buckets:
                buckets[key] = []
            buckets[key].append(s)

        results = []
        for period_key in sorted(buckets.keys()):
            group = buckets[period_key]
            n = len(group)
            results.append(
                {
                    "period": period_key,
                    "session_count": n,
                    "avg_meditation": round(
                        sum(s.get("avg_meditation", 0) for s in group) / n, 2
                    ),
                    "avg_shamatha": round(
                        sum(s.get("avg_shamatha", 0) for s in group) / n, 2
                    ),
                    "total_duration": sum(s.get("duration", 0) for s in group),
                    "total_time_above": sum(
                        s.get("time_above_threshold", 0) for s in group
                    ),
                }
            )
        return results

    def compute_streak(self) -> int:
        """Count consecutive days with at least one session (current streak)."""
        sessions = self._db.get_all_sessions()
        if not sessions:
            return 0

        session_dates = set()
        for s in sessions:
            try:
                dt = datetime.fromisoformat(s["date_time"])
                session_dates.add(dt.date())
            except (ValueError, KeyError):
                continue

        today = datetime.now().date()
        streak = 0
        check_date = today

        while check_date in session_dates:
            streak += 1
            check_date -= timedelta(days=1)

        return streak

    def get_summary(self) -> dict:
        """Get overall summary statistics."""
        sessions = self._db.get_all_sessions()
        if not sessions:
            return {
                "total_sessions": 0,
                "total_minutes": 0,
                "avg_shamatha": 0.0,
                "current_streak": 0,
            }

        return {
            "total_sessions": len(sessions),
            "total_minutes": sum(s.get("duration", 0) for s in sessions) // 60,
            "avg_shamatha": round(
                sum(s.get("avg_shamatha", 0) for s in sessions) / len(sessions), 2
            ),
            "current_streak": self.compute_streak(),
        }


if __name__ == "__main__":
    import os
    import tempfile

    db_path = os.path.join(tempfile.gettempdir(), "test_analytics.db")
    db = DatabaseManager(db_path=db_path)

    for i in range(5):
        db.save_session({
            "duration": 600 + i * 60,
            "threshold_used": 50,
            "avg_meditation": 50 + i * 5,
            "avg_shamatha": 30 + i * 3,
            "max_meditation": 150,
            "time_above_threshold": 200 + i * 20,
        })

    agg = AnalyticsAggregator(db)
    summary = agg.get_summary()

    daily = agg.get_daily_stats(days=7)
    for _d in daily:
        pass


    db.close()
    os.remove(db_path)
