"""Endpoint action items Sprint 8.

POST = generate / retry / regenerate. Item hasil edit pengguna tidak dihapus
dan tidak ditimpa oleh regenerasi. Saat proses gagal, job menjadi FAILED dan
data lama tetap utuh.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...models.action_item import ActionExtractionStatus, ActionItemJob
from ...models.diarization import DiarizationJob, DiarizationStatus
from ...models.transcript import TranscriptionJob, TranscriptionStatus
from ...schemas.action_item import ActionItemListRead, ActionItemRead, ActionItemUpdate
from ...services import job_guard
from ...services.action_items.workflow import (
    clear_action_items,
    delete_action_item,
    get_action_items,
    prepare_action_items,
    run_action_items,
    update_action_item,
)
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Action Items"])


@router.post(
    "/{meeting_id}/action-items",
    response_model=ActionItemListRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_action_items(
    meeting_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ActionItemListRead:
    """Validasi lalu jalankan ekstraksi di background (202)."""
    result = prepare_action_items(db, meeting_id)
    background_tasks.add_task(run_action_items, meeting_id)
    return result


@router.get("/{meeting_id}/action-items", response_model=ActionItemListRead)
def read_action_items(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ActionItemListRead:
    """Ambil status + action item terakhir (bisa kosong). Aman untuk polling."""
    return get_action_items(db, meeting_id)


@router.delete("/{meeting_id}/action-items")
def remove_action_items(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Hapus seluruh action item + job. Transkrip, speaker, dan audio tidak dihapus."""
    job = (
        db.query(ActionItemJob)
        .filter(ActionItemJob.meeting_id == str(meeting_id))
        .first()
    )
    if job is not None and job.status == ActionExtractionStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ekstraksi action items sedang berjalan. Tunggu hingga selesai.",
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

    job_guard.ensure_no_active_jobs(db, meeting_id, exclude="action items")

    try:
        items_deleted, sources_deleted, jobs_deleted = clear_action_items(db, meeting_id)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Gagal menghapus action items."
        ) from None

    return {
        "detail": "Action items dihapus. Transkrip, speaker, dan audio tidak dihapus.",
        "meeting_id": str(meeting_id),
        "items_deleted": items_deleted,
        "sources_deleted": sources_deleted,
        "jobs_deleted": jobs_deleted,
    }


@router.patch(
    "/{meeting_id}/action-items/{item_id}",
    response_model=ActionItemRead,
)
def edit_action_item(
    meeting_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ActionItemUpdate,
    db: Session = Depends(get_db),
) -> ActionItemRead:
    """Ubah field yang diizinkan; menandai item sebagai hasil edit pengguna."""
    return update_action_item(db, meeting_id, item_id, payload)


@router.delete("/{meeting_id}/action-items/{item_id}")
def remove_action_item(
    meeting_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Hapus satu action item; item lain dan data rapat tidak berubah."""
    return delete_action_item(db, meeting_id, item_id)
