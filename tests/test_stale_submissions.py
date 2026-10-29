"""Tests for expiring submissions abandoned in PENDING/UPLOADING."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.database import DatabaseManager, JobModel, JobStatus
from shared.local_storage import LocalStorageManager
from shared.reconciler import expire_stale_submissions


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


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


def _seed_job(db, storage, *, job_id, status, age_minutes):
    """Insert a job created ``age_minutes`` before NOW, with an input file on disk."""
    with db.get_session() as session:
        session.add(JobModel(
            id=job_id,
            job_name=job_id,
            status=status.value,
            created_at=NOW - timedelta(minutes=age_minutes),
            current_step="Waiting for file uploads",
            is_private=False,
        ))
    storage.create_job_directories(job_id)
    input_file = Path(storage.get_input_directory(job_id)) / "traj.xtc"
    input_file.write_bytes(b"partial upload")
    return input_file


def _get_job(db, job_id):
    with db.get_session() as session:
        row = session.query(JobModel).filter(JobModel.id == job_id).first()
        return {
            "status": row.status,
            "error_message": row.error_message,
            "completed_at": row.completed_at,
        }


@pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.UPLOADING])
def test_stale_submission_is_failed_and_files_deleted(db, storage, status):
    input_file = _seed_job(db, storage, job_id="abandoned", status=status, age_minutes=90)

    n = expire_stale_submissions(db, storage, max_age_minutes=60, now=NOW)

    assert n == 1
    job = _get_job(db, "abandoned")
    assert job["status"] == JobStatus.FAILED.value
    assert "never" in job["error_message"].lower()
    assert job["completed_at"] is not None
    assert not input_file.exists()


def test_recent_submission_is_left_alone(db, storage):
    input_file = _seed_job(db, storage, job_id="uploading-now",
                           status=JobStatus.UPLOADING, age_minutes=5)

    n = expire_stale_submissions(db, storage, max_age_minutes=60, now=NOW)

    assert n == 0
    assert _get_job(db, "uploading-now")["status"] == JobStatus.UPLOADING.value
    assert input_file.exists()


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED])
def test_old_jobs_past_submission_are_untouched(db, storage, status):
    input_file = _seed_job(db, storage, job_id="real-job", status=status, age_minutes=600)

    n = expire_stale_submissions(db, storage, max_age_minutes=60, now=NOW)

    assert n == 0
    assert _get_job(db, "real-job")["status"] == status.value
    assert input_file.exists()


def test_conditional_fail_refuses_job_that_moved_on(db, storage):
    """If /start queued the job after the sweep listed it, it must not be failed."""
    _seed_job(db, storage, job_id="just-started", status=JobStatus.QUEUED, age_minutes=90)

    ok = db.fail_job_if_status(
        "just-started",
        [JobStatus.PENDING, JobStatus.UPLOADING],
        error_message="Submission was never completed",
        current_step="Submission abandoned",
    )

    assert ok is False
    assert _get_job(db, "just-started")["status"] == JobStatus.QUEUED.value


def test_conditional_fail_on_missing_job_returns_false(db):
    assert db.fail_job_if_status(
        "no-such-job", [JobStatus.PENDING], error_message="x", current_step="x",
    ) is False
