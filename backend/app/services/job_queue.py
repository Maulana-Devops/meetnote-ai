"""Antrean job berbasis database untuk proses worker terpisah.

Modul ini sengaja tidak tahu cara memanggil provider. Ia hanya:
1. membuat baris ``job_queue`` saat endpoint memilih ``JOB_RUNNER=worker``;
2. mengklaim satu baris secara atomik;
3. membaca status akhir dari tabel job yang sudah ada;
4. mengubah baris antrean menjadi COMPLETED/FAILED;
5. membersihkan klaim yang ditinggalkan worker yang mati.

Semua perubahan bersifat aditif: tabel job lama, audio, dan transkrip tidak
pernah dihapus atau ditimpa.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Callable

from fastapi import BackgroundTasks
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.action_item import ActionExtractionStatus, ActionItemJob
from ..models.diarization import DiarizationJob, DiarizationStatus
from ..models.job_queue import JobQueue, JobQueueStatus
from ..models.summary import SummaryJob, SummaryStatus
from ..models.transcript import TranscriptionJob, TranscriptionStatus

TRANSCRIPTION = "transcription"
DIARIZATION = "diarization"
SUMMARY = "summary"
ACTION_ITEMS = "action_items"

# (model job, status PROCESSING, status selesai, status gagal)
_JOB_TARGETS: dict[str, tuple[Any, str, str, str]] = {
    TRANSCRIPTION: (
        TranscriptionJob,
        TranscriptionStatus.PROCESSING,
        TranscriptionStatus.COMPLETED,
        TranscriptionStatus.FAILED,
    ),
    DIARIZATION: (
        DiarizationJob,
        DiarizationStatus.PROCESSING,
        DiarizationStatus.COMPLETED,
        DiarizationStatus.FAILED,
    ),
    SUMMARY: (
        SummaryJob,
        SummaryStatus.PROCESSING,
        SummaryStatus.COMPLETED,
        SummaryStatus.FAILED,
    ),
    ACTION_ITEMS: (
        ActionItemJob,
        ActionExtractionStatus.PROCESSING,
        ActionExtractionStatus.COMPLETED,
        ActionExtractionStatus.FAILED,
    ),
}

_FAILURE_MESSAGE = "Job dihentikan setelah worker terputus. Coba lagi dari UI."
logger = logging.getLogger(__name__)


def _now() -> datetime.datetime:
    """UTC naive agar sejenis dengan CURRENT_TIMESTAMP SQLite."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def dispatch_job(
    db: Session,
    background_tasks: BackgroundTasks,
    job_type: str,
    meeting_id: uuid.UUID,
    runner: Callable[[uuid.UUID], None],
) -> JobQueue | None:
    """Jadwalkan job sesuai mode yang dikonfigurasi.

    Mode ``background`` mempertahankan perilaku lama. Mode ``worker`` menulis
    satu baris antrean dengan ``run_token`` dari tabel job yang baru diklaim.
    """
    if settings.JOB_RUNNER != "worker":
        background_tasks.add_task(runner, meeting_id)
        return None

    model, processing_status, _, _ = _JOB_TARGETS[job_type]
    job = (
        db.query(model)
        .filter(
            model.meeting_id == str(meeting_id),
            model.status == processing_status,
        )
        .first()
    )
    if job is None:
        # Tidak boleh terjadi: prepare_* gagal sebelum endpoint ini dipanggil.
        raise RuntimeError("Job PROCESSING tidak ditemukan saat membuat antrean.")

    row = JobQueue(
        job_type=job_type,
        meeting_id=str(meeting_id),
        run_token=job.run_token,
        status=JobQueueStatus.PENDING,
        attempts=0,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        # Fail-closed: prepare_* sudah menandai job PROCESSING. Tanpa baris
        # antrean, worker tidak akan pernah menyelesaikannya, jadi tandai FAILED
        # agar pengguna bisa mencoba lagi dari UI.
        db.rollback()
        job.status = _JOB_TARGETS[job_type][3]
        job.error = _FAILURE_MESSAGE
        job.run_token = None
        db.commit()
        raise
    return row


def claim_next(db: Session, worker_id: str) -> JobQueue | None:
    """Ambil satu baris PENDING paling lama secara atomik.

    ``UPDATE ... WHERE status='PENDING'`` berada dalam satu transaksi. Bila dua
    worker bersamaan, hanya satu yang benar-benar mengubah baris; yang lain
    mendapat ``updated == 0`` dan mencari baris berikutnya.
    """
    try:
        candidate = (
            db.query(JobQueue)
            .filter(JobQueue.status == JobQueueStatus.PENDING)
            .order_by(JobQueue.created_at.asc(), JobQueue.id.asc())
            .first()
        )
        if candidate is None:
            return None

        updated = (
            db.query(JobQueue)
            .filter(
                JobQueue.id == candidate.id,
                JobQueue.status == JobQueueStatus.PENDING,
            )
            .update(
                {
                    JobQueue.status: JobQueueStatus.PROCESSING,
                    JobQueue.attempts: JobQueue.attempts + 1,
                    JobQueue.worker_id: worker_id[:100],
                    JobQueue.updated_at: _now(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
    except OperationalError as exc:
        # SQLite "database is locked" bersifat sementara. Jangan matikan worker;
        # proses lain mungkin sedang menulis. Putaran berikutnya mencoba lagi.
        db.rollback()
        logger.warning("queue_claim_busy error_category=%s", type(exc).__name__)
        return None

    if updated != 1:
        db.rollback()
        return None
    return db.get(JobQueue, candidate.id)


def mark_finished(
    db: Session,
    row_id: str,
    status: str,
    *,
    error_category: str | None = None,
) -> None:
    """Tutup baris antrean. Hanya menerima kategori error, bukan pesan bebas."""
    (
        db.query(JobQueue)
        .filter(JobQueue.id == row_id)
        .update(
            {
                JobQueue.status: status,
                JobQueue.error_category: error_category[:100] if error_category else None,
                JobQueue.updated_at: _now(),
            },
            synchronize_session=False,
        )
    )
    db.commit()


def outcome_from_job(db: Session, row: JobQueue) -> tuple[str, str | None]:
    """Baca status akhir dari tabel job asli.

    ``run_*`` sengaja menelan exception dan menandai job FAILED sendiri, jadi
    status antrean tidak boleh diambil dari return value fungsi tersebut.
    """
    model, _, completed_status, failed_status = _JOB_TARGETS[row.job_type]
    query = db.query(model).filter(model.meeting_id == row.meeting_id)
    if row.run_token is not None:
        query = query.filter(model.run_token == row.run_token)
    job = query.first()

    if job is None:
        return JobQueueStatus.FAILED, "JobNotFound"
    if job.status == completed_status:
        return JobQueueStatus.COMPLETED, None
    if job.status == failed_status:
        return JobQueueStatus.FAILED, "JobFailed"
    # Masih PROCESSING/NOT_STARTED setelah runner selesai = keadaan tak terduga.
    return JobQueueStatus.FAILED, "JobIncomplete"


def _fail_linked_job(db: Session, row: JobQueue) -> None:
    """Tandai job terkait sebagai FAILED tanpa menyentuh job yang lebih baru."""
    model, processing_status, _, failed_status = _JOB_TARGETS[row.job_type]
    query = db.query(model).filter(
        model.meeting_id == row.meeting_id,
        model.status == processing_status,
    )
    if row.run_token is not None:
        query = query.filter(model.run_token == row.run_token)
    query.update(
        {
            model.status: failed_status,
            model.error: _FAILURE_MESSAGE,
            model.run_token: None,
            model.updated_at: _now(),
        },
        synchronize_session=False,
    )


def recover_stale(
    db: Session,
    *,
    stale_seconds: float,
    max_attempts: int,
) -> int:
    """Bersihkan klaim yang ditinggalkan worker mati.

    Baris dengan attempts di bawah batas dikembalikan ke PENDING dan memakai
    ``run_token`` yang sama (job asli masih PROCESSING). Baris yang sudah
    melewati batas ditandai FAILED dan job terkait ikut ditandai FAILED.
    """
    cutoff = _now() - datetime.timedelta(seconds=stale_seconds)
    rows = (
        db.query(JobQueue)
        .filter(
            JobQueue.status == JobQueueStatus.PROCESSING,
            JobQueue.updated_at < cutoff,
        )
        .all()
    )
    now = _now()
    for row in rows:
        if row.attempts < max_attempts:
            row.status = JobQueueStatus.PENDING
            row.error_category = "WorkerInterrupted"
            row.worker_id = None
            row.updated_at = now
        else:
            row.status = JobQueueStatus.FAILED
            row.error_category = "MaxAttemptsExceeded"
            row.updated_at = now
            _fail_linked_job(db, row)
    if rows:
        db.commit()
    return len(rows)
