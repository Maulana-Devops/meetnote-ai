"""Endpoint diarisasi Sprint 5.

POST memakai FastAPI BackgroundTasks seperti transkripsi Sprint 4: response
202 dikirim lebih dulu, lalu provider dipanggil di luar thread request. Status
disimpan di ``diarization_jobs`` dan tidak mengubah status transkripsi.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...models.diarization import DiarizationJob, DiarizationStatus
from ...models.transcript import TranscriptionJob, TranscriptionStatus
from ...schemas.diarization import DiarizationRead
from ...services.diarization.workflow import (
    clear_diarization,
    get_diarization,
    prepare_diarization,
    run_diarization,
)
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Diarization"])


@router.post(
    "/{meeting_id}/diarization",
    response_model=DiarizationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_diarization(
    meeting_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> DiarizationRead:
    """Validasi lalu jalankan diarisasi di background."""
    result = prepare_diarization(db, meeting_id)
    background_tasks.add_task(run_diarization, meeting_id)
    return result


@router.get("/{meeting_id}/diarization", response_model=DiarizationRead)
def read_diarization(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DiarizationRead:
    """Ambil status + speaker (bisa kosong). Aman untuk polling."""
    return get_diarization(db, meeting_id)


@router.delete("/{meeting_id}/diarization")
def remove_diarization(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Hapus speaker + job diarisasi. Transkrip dan audio tidak dihapus."""
    job = (
        db.query(DiarizationJob)
        .filter(DiarizationJob.meeting_id == str(meeting_id))
        .first()
    )
    if job is not None and job.status == DiarizationStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diarisasi sedang berjalan. Tunggu hingga selesai.",
        )

    transcription_job = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == str(meeting_id))
        .first()
    )
    if (
        transcription_job is not None
        and transcription_job.status == TranscriptionStatus.PROCESSING
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transkripsi sedang berjalan. Tunggu hingga selesai.",
        )

    try:
        speakers_deleted, segments_unassigned = clear_diarization(db, meeting_id)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Gagal menghapus hasil diarisasi."
        ) from None

    return {
        "detail": "Diarisasi dihapus. Transkrip dan audio tidak dihapus.",
        "meeting_id": str(meeting_id),
        "speakers_deleted": speakers_deleted,
        "segments_unassigned": segments_unassigned,
    }
