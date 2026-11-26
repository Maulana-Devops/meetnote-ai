"""Endpoint transkripsi Sprint 4.

POST memakai FastAPI BackgroundTasks: response 202 dikirim lebih dulu, lalu
provider dipanggil di luar thread request. Tidak ada Redis/Celery — batasan
pendekatan ini didokumentasikan di docs/SPRINT4.md.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...models.diarization import DiarizationJob, DiarizationStatus
from ...models.transcript import TranscriptionJob, TranscriptionStatus
from ...schemas.transcription import TranscriptionRead
from ...services import job_guard
from ...services.transcription import (
    clear_transcription,
    get_transcription,
    prepare_transcription,
    run_transcription,
)
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Transcription"])


@router.post(
    "/{meeting_id}/transcription",
    response_model=TranscriptionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_transcription(
    meeting_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TranscriptionRead:
    """Validasi lalu jalankan transkripsi di background."""
    result = prepare_transcription(db, meeting_id)
    background_tasks.add_task(run_transcription, meeting_id)
    return result


@router.get("/{meeting_id}/transcription", response_model=TranscriptionRead)
def read_transcription(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TranscriptionRead:
    """Ambil status dan segmen transkrip (bisa kosong)."""
    return get_transcription(db, meeting_id)


@router.delete("/{meeting_id}/transcription")
def remove_transcription(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Hapus segmen + job transkripsi. Audio dan AudioAsset tetap ada."""
    job = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == str(meeting_id))
        .first()
    )
    if job is not None and job.status == TranscriptionStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transkripsi sedang berjalan. Tunggu hingga selesai.",
        )

    diarization_job = (
        db.query(DiarizationJob)
        .filter(DiarizationJob.meeting_id == str(meeting_id))
        .first()
    )
    if (
        diarization_job is not None
        and diarization_job.status == DiarizationStatus.PROCESSING
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diarisasi sedang berjalan. Tunggu hingga selesai sebelum menghapus transkrip.",
        )

    # Sprint 9: clear_transcription() juga menghapus ringkasan dan action items.
    # Tolak penghapusan bila job dependen masih berjalan agar tidak terjadi
    # data parsial saat task background selesai setelah penghapusan.
    job_guard.ensure_no_active_jobs(db, meeting_id, exclude="transkripsi")

    try:
        removed = clear_transcription(db, meeting_id)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Gagal menghapus transkripsi."
        ) from None

    return {
        "detail": "Transkripsi berhasil dihapus. Audio tidak dihapus.",
        "meeting_id": str(meeting_id),
        "segments_deleted": removed,
    }
