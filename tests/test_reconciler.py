"""Integration tests for the reconciler orchestration."""

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.database import DatabaseManager, JobModel, JobStatus
from shared.local_storage import LocalStorageManager
from shared.reconciler import reconcile_completed_jobs


FIXTURES = Path(__file__).parent / "fixtures"
COMPLETED_LOG = FIXTURES / "calc_log_completed.log"
FAILED_LOG = FIXTURES / "calc_log_failed_midrun.log"


@pytest.fixture
def db():
    """In-memory SQLite DB with a fresh schema."""
    manager = DatabaseManager(database_url="sqlite:///:memory:")
    manager.init_db()
    return manager


@pytest.fixture
def storage(tmp_path):
    """Storage manager rooted at a per-test temp dir."""
    return LocalStorageManager(storage_path=str(tmp_path))


def _seed_job(db: DatabaseManager, *, job_id: str, status: JobStatus) -> None:
    """Insert a job row with an explicit ID and status."""
    with db.get_session() as session:
        session.add(JobModel(
            id=job_id,
            job_name=job_id,
            status=status.value,
            progress_percentage=25 if status == JobStatus.RUNNING else 100,
            current_step="Processing gRINN analysis" if status == JobStatus.RUNNING else "Job completed successfully",
            is_private=False,
        ))


def _seed_output(storage: LocalStorageManager, job_id: str, *,
                 calc_log: Path = None, write_summary: bool = False) -> Path:
    """Create the on-disk output dir for a job and (optionally) drop markers."""
    output_dir = Path(storage.get_output_directory(job_id))
    if calc_log is not None:
        shutil.copy2(calc_log, output_dir / "calc.log")
    if write_summary:
        (output_dir / "grinn_workflow_summary.json").write_text('{"ok": true}')
    return output_dir


def _get_job(db: DatabaseManager, job_id: str) -> dict:
    """Return a detached snapshot of the job row as a dict."""
    with db.get_session() as session:
        row = session.query(JobModel).filter(JobModel.id == job_id).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "status": row.status,
            "progress_percentage": row.progress_percentage,
            "current_step": row.current_step,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "processing_time_seconds": row.processing_time_seconds,
            "error_message": row.error_message,
        }


def test_running_with_summary_and_success_marker_is_promoted(db, storage):
    """The exact bug we just fixed by hand-written SQL — automated."""
    _seed_job(db, job_id="stuck-success", status=JobStatus.RUNNING)
    output_dir = _seed_output(storage, "stuck-success",
                              calc_log=COMPLETED_LOG, write_summary=True)

    n = reconcile_completed_jobs(db, storage)

    assert n == 1
    job = _get_job(db, "stuck-success")
    assert job["status"] == JobStatus.COMPLETED.value
    assert job["progress_percentage"] == 100
    assert job["completed_at"] is not None
    assert job["started_at"] is not None
    assert job["processing_time_seconds"] == 5557  # from the COMPLETED_LOG fixture
    assert "reconciled" in job["current_step"].lower()
    assert job["error_message"] is None


def test_running_without_summary_is_unchanged(db, storage):
    """A row still in calc, no summary yet, must not be touched."""
    _seed_job(db, job_id="mid-calc", status=JobStatus.RUNNING)
    _seed_output(storage, "mid-calc", calc_log=FAILED_LOG, write_summary=False)

    n = reconcile_completed_jobs(db, storage)

    assert n == 0
    job = _get_job(db, "mid-calc")
    assert job["status"] == JobStatus.RUNNING.value
    assert job["completed_at"] is None


def test_running_with_summary_but_no_success_marker_is_unchanged(db, storage):
    """Defends against a partial-write where summary exists but the success
    line hasn't been logged. (Can't actually happen with gRINN today — the
    success line is the very last thing written — but the reconciler is
    paranoid about it.)
    """
    _seed_job(db, job_id="partial-write", status=JobStatus.RUNNING)
    _seed_output(storage, "partial-write", calc_log=FAILED_LOG, write_summary=True)

    n = reconcile_completed_jobs(db, storage)

    assert n == 0
    job = _get_job(db, "partial-write")
    assert job["status"] == JobStatus.RUNNING.value


def test_already_completed_row_is_not_repicked(db, storage):
    """Idempotency: a row already in COMPLETED is not visited."""
    _seed_job(db, job_id="already-done", status=JobStatus.COMPLETED)
    _seed_output(storage, "already-done", calc_log=COMPLETED_LOG, write_summary=True)

    n = reconcile_completed_jobs(db, storage)

    assert n == 0
    job = _get_job(db, "already-done")
    assert job["status"] == JobStatus.COMPLETED.value
    # The reconciler should not have rewritten the row.
    assert job["completed_at"] is None  # we never set one when seeding


def test_started_at_is_completed_minus_elapsed(db, storage):
    """processing_time_seconds should bridge started_at and completed_at."""
    _seed_job(db, job_id="time-math", status=JobStatus.RUNNING)
    _seed_output(storage, "time-math",
                 calc_log=COMPLETED_LOG, write_summary=True)

    reconcile_completed_jobs(db, storage)

    job = _get_job(db, "time-math")
    delta = (job["completed_at"] - job["started_at"]).total_seconds()
    assert delta == pytest.approx(job["processing_time_seconds"], abs=1)
