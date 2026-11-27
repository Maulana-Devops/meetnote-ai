"""Endpoint ringkasan AI Sprint 7.

POST = generate / retry / regenerate. Jika ringkasan sudah ada, hasil lama
tetap tampil dan baru diganti setelah hasil baru tervalidasi. Saat proses gagal,
job menjadi FAILED dan ringkasan lama tidak berubah.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...models.diarization import DiarizationJob, DiarizationStatus
from ...models.summary import SummaryJob, SummaryStatus
from ...models.transcript import TranscriptionJob, TranscriptionStatus
from ...schemas.summary import SummaryRead
from ...services import job_guard
from ...services.job_queue import SUMMARY, dispatch_job
from ...services.summary.workflow import (
    clear_summary,
    get_summary,
    prepare_summary,
    run_summary,
)
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Summary"])


@router.post(
    "/{meeting_id}/summary",
    response_model=SummaryRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_summary(
    meeting_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SummaryRead:
    """Validasi lalu jalankan ringkasan di background (202)."""
    result = prepare_summary(db, meeting_id)
    dispatch_job(db, background_tasks, SUMMARY, meeting_id, run_summary)
    return result


@router.get("/{meeting_id}/summary", response_model=SummaryRead)
def read_summary(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SummaryRead:
    """Ambil status + ringkasan terakhir (bisa kosong). Aman untuk polling."""
    return get_summary(db, meeting_id)


@router.delete("/{meeting_id}/summary")
def remove_summary(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Hapus ringkasan + job. Transkrip, speaker, dan audio tidak dihapus."""
    summary_job = (
        db.query(SummaryJob)
        .filter(SummaryJob.meeting_id == str(meeting_id))
        .first()
    )
    if summary_job is not None and summary_job.status == SummaryStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ringkasan sedang diproses. Tunggu hingga selesai.",
        )

    for job_model, message in (
        (TranscriptionJob, "Transkripsi sedang berjalan. Tunggu hingga selesai."),
        (DiarizationJob, "Diarisasi sedang berjalan. Tunggu hingga selesai."),
    ):
        active = (
            db.query(job_model)
            .filter(job_model.meeting_id == str(meeting_id))
            .first()
        )
        if (
            active is not None
            and active.status
            in (TranscriptionStatus.PROCESSING, DiarizationStatus.PROCESSING)
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

    job_guard.ensure_no_active_jobs(db, meeting_id, exclude="ringkasan")

    try:
        summaries_deleted, jobs_deleted = clear_summary(db, meeting_id)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Gagal menghapus ringkasan."
        ) from None

    return {
        "detail": "Ringkasan dihapus. Transkrip dan audio tidak dihapus.",
        "meeting_id": str(meeting_id),
        "summaries_deleted": summaries_deleted,
        "jobs_deleted": jobs_deleted,
    }
