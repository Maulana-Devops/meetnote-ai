"""Pengujian mode worker/antrean DB (provider tetap mock, DB test terisolasi)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.database import migrations as migration_module
from app.models.job_queue import JobQueue, JobQueueStatus
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import TranscriptionJob, TranscriptionStatus
from app.services.job_queue import (
    ACTION_ITEMS,
    TRANSCRIPTION,
    claim_next,
    dispatch_job,
    mark_finished,
    outcome_from_job,
    recover_stale,
)
from worker import process_batch


class FakeBackgroundTasks:
    """Pengganti BackgroundTasks untuk memeriksa mode default."""

    def __init__(self) -> None:
        self.tasks: list[tuple[object, tuple[object, ...]]] = []

    def add_task(self, func, *args) -> None:  # noqa: ANN001 - kontrak FastAPI
        self.tasks.append((func, args))


def _meeting_and_job(s2_db, *, run_token: str = "token-uji") -> tuple[Meeting, TranscriptionJob]:
    meeting = Meeting(title="Rapat Antrean", status=MeetingStatus.UPLOADED)
    s2_db.add(meeting)
    s2_db.commit()

    job = TranscriptionJob(
        meeting_id=meeting.id,
        status=TranscriptionStatus.PROCESSING,
        run_token=run_token,
        provider="mock",
        model="mock-1",
        has_timestamps=False,
    )
    s2_db.add(job)
    s2_db.commit()
    return meeting, job


def _queue_row(s2_db, meeting_id: str, **overrides) -> JobQueue:
    values = {
        "job_type": TRANSCRIPTION,
        "meeting_id": meeting_id,
        "run_token": "token-uji",
        "status": JobQueueStatus.PENDING,
        "attempts": 0,
    }
    values.update(overrides)
    row = JobQueue(**values)
    s2_db.add(row)
    s2_db.commit()
    s2_db.refresh(row)
    return row


def _make_stale(s2_db, row_id: str) -> None:
    old = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=2)
    s2_db.query(JobQueue).filter(JobQueue.id == row_id).update(
        {JobQueue.updated_at: old}, synchronize_session=False
    )
    s2_db.commit()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_mode_default_memakai_background_tasks(s2_db, monkeypatch):
    monkeypatch.setattr(settings, "JOB_RUNNER", "background")
    background = FakeBackgroundTasks()
    meeting_id = uuid.uuid4()

    def runner(value: uuid.UUID) -> None:
        return None

    row = dispatch_job(s2_db, background, TRANSCRIPTION, meeting_id, runner)

    assert row is None
    assert background.tasks == [(runner, (meeting_id,))]
    assert s2_db.query(JobQueue).count() == 0


def test_mode_worker_menulis_baris_antrean_dengan_run_token(s2_db, monkeypatch):
    monkeypatch.setattr(settings, "JOB_RUNNER", "worker")
    meeting, job = _meeting_and_job(s2_db)
    background = FakeBackgroundTasks()

    row = dispatch_job(s2_db, background, TRANSCRIPTION, uuid.UUID(meeting.id), lambda _: None)

    assert row is not None
    assert row.job_type == TRANSCRIPTION
    assert row.meeting_id == meeting.id
    assert row.run_token == job.run_token
    assert row.status == JobQueueStatus.PENDING
    assert row.attempts == 0
    assert background.tasks == []


def test_mode_worker_menolak_job_yang_tidak_processing(s2_db, monkeypatch):
    monkeypatch.setattr(settings, "JOB_RUNNER", "worker")
    meeting, job = _meeting_and_job(s2_db)
    job.status = TranscriptionStatus.NOT_STARTED
    s2_db.commit()

    with pytest.raises(RuntimeError, match="PROCESSING"):
        dispatch_job(s2_db, FakeBackgroundTasks(), TRANSCRIPTION, uuid.UUID(meeting.id), lambda _: None)


def test_gagal_menulis_antrean_menandai_job_failed(s2_db, monkeypatch):
    """Fail-closed: job tidak boleh terjebak PROCESSING tanpa baris antrean."""
    monkeypatch.setattr(settings, "JOB_RUNNER", "worker")
    meeting, job = _meeting_and_job(s2_db)
    original_add = s2_db.add
    calls = {"count": 0}

    def flaky_add(value):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulasi gagal menulis antrean")
        return original_add(value)

    monkeypatch.setattr(s2_db, "add", flaky_add)

    with pytest.raises(RuntimeError, match="simulasi gagal"):
        dispatch_job(
            s2_db,
            FakeBackgroundTasks(),
            TRANSCRIPTION,
            uuid.UUID(meeting.id),
            lambda _: None,
        )

    s2_db.refresh(job)
    assert job.status == TranscriptionStatus.FAILED
    assert job.run_token is None
    assert s2_db.query(JobQueue).count() == 0


# ---------------------------------------------------------------------------
# Klaim & status
# ---------------------------------------------------------------------------


def test_claim_next_mengambil_satu_baris_dan_menambah_attempts(s2_db):
    meeting, _ = _meeting_and_job(s2_db)
    first = _queue_row(s2_db, meeting.id)
    second = _queue_row(s2_db, meeting.id)

    claimed = claim_next(s2_db, "worker-a")
    assert claimed is not None
    assert claimed.id in {first.id, second.id}
    assert claimed.status == JobQueueStatus.PROCESSING
    assert claimed.attempts == 1
    assert claimed.worker_id == "worker-a"

    another = claim_next(s2_db, "worker-b")
    assert another is not None
    assert another.id != claimed.id
    assert claim_next(s2_db, "worker-c") is None


def test_claim_busy_ditunda_tanpa_mengubah_baris(s2_db, monkeypatch):
    meeting, _ = _meeting_and_job(s2_db)
    row = _queue_row(s2_db, meeting.id)
    original_commit = s2_db.commit
    calls = {"count": 0}

    def flaky_commit():
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("SELECT 1", {}, Exception("database is locked"))
        return original_commit()

    monkeypatch.setattr(s2_db, "commit", flaky_commit)

    assert claim_next(s2_db, "worker-a") is None
    s2_db.refresh(row)
    assert row.status == JobQueueStatus.PENDING
    assert row.attempts == 0


def test_outcome_dan_mark_finished_memakai_status_job_asli(s2_db):
    meeting, job = _meeting_and_job(s2_db)
    row = _queue_row(s2_db, meeting.id, status=JobQueueStatus.PROCESSING, attempts=1)

    job.status = TranscriptionStatus.COMPLETED
    s2_db.commit()
    assert outcome_from_job(s2_db, row) == (JobQueueStatus.COMPLETED, None)

    mark_finished(s2_db, row.id, JobQueueStatus.COMPLETED)
    s2_db.refresh(row)
    assert row.status == JobQueueStatus.COMPLETED
    assert row.error_category is None

    job.status = TranscriptionStatus.FAILED
    s2_db.commit()
    assert outcome_from_job(s2_db, row) == (JobQueueStatus.FAILED, "JobFailed")


# ---------------------------------------------------------------------------
# Stale recovery
# ---------------------------------------------------------------------------


def test_stale_dengan_attempts_belum_habis_kembali_ke_pending(s2_db):
    meeting, job = _meeting_and_job(s2_db)
    row = _queue_row(s2_db, meeting.id, status=JobQueueStatus.PROCESSING, attempts=1)
    _make_stale(s2_db, row.id)

    assert recover_stale(s2_db, stale_seconds=60, max_attempts=2) == 1
    s2_db.refresh(row)
    s2_db.refresh(job)
    assert row.status == JobQueueStatus.PENDING
    assert row.error_category == "WorkerInterrupted"
    assert job.status == TranscriptionStatus.PROCESSING


def test_stale_melewati_batas_menandai_job_failed(s2_db):
    meeting, job = _meeting_and_job(s2_db)
    row = _queue_row(s2_db, meeting.id, status=JobQueueStatus.PROCESSING, attempts=3)
    _make_stale(s2_db, row.id)

    assert recover_stale(s2_db, stale_seconds=60, max_attempts=3) == 1
    s2_db.refresh(row)
    s2_db.refresh(job)
    assert row.status == JobQueueStatus.FAILED
    assert row.error_category == "MaxAttemptsExceeded"
    assert job.status == TranscriptionStatus.FAILED
    assert job.error == "Job dihentikan setelah worker terputus. Coba lagi dari UI."
    assert job.run_token is None


# ---------------------------------------------------------------------------
# Worker batch & migrasi legacy
# ---------------------------------------------------------------------------


def test_process_batch_menyelesaikan_satu_job(s2_db):
    meeting, job = _meeting_and_job(s2_db)
    row = _queue_row(s2_db, meeting.id)

    def runner(meeting_id: uuid.UUID) -> None:
        current = s2_db.query(TranscriptionJob).filter(
            TranscriptionJob.meeting_id == str(meeting_id)
        ).first()
        current.status = TranscriptionStatus.COMPLETED
        s2_db.commit()

    processed, recovered = process_batch(
        s2_db,
        runners={TRANSCRIPTION: runner},
        worker_id="worker-test",
        batch_size=1,
        stale_seconds=3600,
        max_attempts=3,
    )

    assert (processed, recovered) == (1, 0)
    s2_db.refresh(row)
    s2_db.refresh(job)
    assert row.status == JobQueueStatus.COMPLETED
    assert row.attempts == 1
    assert job.status == TranscriptionStatus.COMPLETED


def test_tabel_antrean_dibuat_juga_pada_database_legacy(monkeypatch, tmp_path):
    """DB lama yang di-stamp head tidak menjalankan 0002, jadi jalur aditif wajib."""
    legacy_db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{legacy_db.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE meetings ("
                "id VARCHAR(36) PRIMARY KEY, title VARCHAR(255), "
                "status VARCHAR(50), created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE transcript_segments ("
                "id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36), text TEXT, "
                "start_seconds FLOAT, end_seconds FLOAT, sequence INTEGER, created_at DATETIME)"
            )
        )

    monkeypatch.setattr(migration_module, "engine", engine)
    migration_module.apply_additive_migrations()

    tables = set(inspect(engine).get_table_names())
    assert "job_queue" in tables
    indexes = {item["name"] for item in inspect(engine).get_indexes("job_queue")}
    assert {"ix_job_queue_status_created_at", "ix_job_queue_meeting_id"} <= indexes
