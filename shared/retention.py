"""Job-file retention math for user-facing "time until deletion" displays.

The cleanup beat task deletes a job's files once
``created_at + JOB_FILE_RETENTION_HOURS`` is in the past, where ``created_at``
is the job's *submission* time (not completion) — see
``shared/local_storage.py`` ``cleanup_old_jobs`` and
``shared/database.py`` ``mark_jobs_as_expired``, which use the same basis.

Kept Dash-free and Celery-free so the queue banner and monitor countdown can
share one source of truth that is unit testable without the frontend app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _as_utc(dt: datetime) -> datetime:
    """Return ``dt`` as timezone-aware UTC; a naive ``dt`` is assumed to be UTC.

    Job timestamps reach us from both tz-aware DB columns and naive
    ``datetime.utcnow()`` defaults, so we normalise before any arithmetic to
    avoid ``TypeError`` and silent off-by-offset bugs.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def file_expiry(created_at: datetime, retention_hours: float) -> datetime:
    """When a job's files become eligible for deletion (tz-aware UTC)."""
    return _as_utc(created_at) + timedelta(hours=retention_hours)


def remaining_until_deletion(
    created_at: datetime,
    retention_hours: float,
    now: datetime | None = None,
) -> timedelta:
    """Time left until file deletion; non-positive once the deadline has passed."""
    now = datetime.now(timezone.utc) if now is None else _as_utc(now)
    return file_expiry(created_at, retention_hours) - now


def format_remaining(delta: timedelta) -> str:
    """Human "time left" using the two most-significant non-zero units.

    Examples: ``2d 4h``, ``5h 12m``, ``8m``. Returns ``"imminently"`` when the
    deadline has passed and ``"less than a minute"`` for sub-minute slivers.
    """
    total = int(delta.total_seconds())
    if total <= 0:
        return "imminently"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return "less than a minute"


def format_retention(retention_hours: float) -> str:
    """Banner-ready phrasing, e.g. ``"72 hours (3 days)"`` or ``"12 hours"``."""
    hours = retention_hours
    hours_str = f"{int(hours)}" if float(hours).is_integer() else f"{hours:g}"
    unit_h = "hour" if hours == 1 else "hours"
    if hours < 24:
        return f"{hours_str} {unit_h}"
    days = hours / 24
    days_str = f"{int(days)}" if float(days).is_integer() else f"{days:g}"
    unit_d = "day" if days == 1 else "days"
    return f"{hours_str} {unit_h} ({days_str} {unit_d})"
