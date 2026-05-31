"""Promote on-disk-completed jobs whose DB row is stuck in RUNNING.

Background: when a gRINN container's runtime exceeds Celery's
``task_time_limit``, the worker process is SIGKILLed mid-``container.wait()``.
The detached container keeps running to completion and writes
``grinn_workflow_summary.json``, but the Python code that flips the DB row
to COMPLETED never executes. This module reconciles the on-disk truth back
into the database from a periodic beat task.

Kept Celery-free so that the parsing helpers and orchestration are unit
testable without the full task-queue stack.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_GRINN_SUCCESS_MARKER = "### gRINN workflow completed successfully ###"
_ELAPSED_RE = re.compile(r"Elapsed time:\s*([0-9]+(?:\.[0-9]+)?)\s*seconds")


def _calc_log_ends_with_success(path: Path) -> bool:
    """Return True iff the tail of ``path`` contains the gRINN success marker.

    The marker is the last line ``grinn_workflow.py`` writes on success, so if
    we see it the preceding ``grinn_workflow_summary.json`` write has fully
    flushed. Returns False on any IO error or missing file.
    """
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    return _GRINN_SUCCESS_MARKER in tail


def _read_elapsed_seconds(path: Path) -> Optional[float]:
    """Return the last ``Elapsed time: N seconds`` value from ``path``, or None.

    gRINN logs the elapsed time once at the end of the run, just before the
    success marker. We tail-read 8 KiB to stay well clear of any in-run
    ``Elapsed time`` log lines that might appear in future versions.
    """
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    matches = _ELAPSED_RE.findall(tail)
    return float(matches[-1]) if matches else None


def reconcile_completed_jobs(db, storage) -> int:
    """Promote running jobs whose output dir signals successful completion.

    Args:
        db: A ``DatabaseManager``-like object exposing ``get_jobs_by_status``
            and ``set_job_completed``.
        storage: A ``LocalStorageManager``-like object exposing
            ``get_output_directory(job_id) -> str``.

    Returns:
        The number of rows promoted to COMPLETED in this pass.
    """
    # Imported lazily to keep this module's top-level free of the DB/Celery
    # stack (helps the unit-tested parsers stay zero-dep).
    from shared.database import JobStatus

    reconciled = 0

    for job_id in db.get_job_ids_by_status(JobStatus.RUNNING, limit=200):
        try:
            output_dir = Path(storage.get_output_directory(job_id))
            summary_path = output_dir / "grinn_workflow_summary.json"
            calc_log_path = output_dir / "calc.log"

            if not summary_path.is_file():
                continue
            if not _calc_log_ends_with_success(calc_log_path):
                continue

            completed_at = datetime.fromtimestamp(
                summary_path.stat().st_mtime, tz=timezone.utc,
            )
            elapsed = _read_elapsed_seconds(calc_log_path)
            started_at = (
                completed_at - timedelta(seconds=elapsed) if elapsed else None
            )

            ok = db.set_job_completed(
                job_id=job_id,
                completed_at=completed_at,
                started_at=started_at,
                processing_time_seconds=int(elapsed) if elapsed else None,
                current_step="Job completed successfully (reconciled)",
            )
            if ok:
                reconciled += 1
                logger.info(
                    "Reconciled job %s: completed_at=%s elapsed=%ss",
                    job_id, completed_at.isoformat(),
                    int(elapsed) if elapsed else "?",
                )
        except Exception as exc:  # noqa: BLE001 — defensive per-job guard
            logger.warning("Reconciler error on job %s: %s", job_id, exc)

    if reconciled:
        logger.info(
            "Reconciler pass complete: %d job(s) promoted to COMPLETED",
            reconciled,
        )
    return reconciled
