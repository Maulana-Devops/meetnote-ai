"""Endpoint Meeting.

Sprint 1: daftar meeting.
Sprint 2: membuat meeting baru. Endpoint rekaman berada di ``recordings.py``.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...database.session import SessionLocal
from ...models.meeting import Meeting, MeetingStatus
from ...schemas.meeting import MeetingCreate, MeetingRead

router = APIRouter(prefix="/meetings", tags=["Meetings"])


def get_db():
    """Dependency yang menyediakan sesi database."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[MeetingRead])
def list_meetings(db: Session = Depends(get_db)) -> list[MeetingRead]:
    """Ambil semua meeting, urutkan dari yang terbaru."""
    try:
        meetings = db.query(Meeting).order_by(Meeting.created_at.desc()).all()
        return [MeetingRead.model_validate(m) for m in meetings]
    except Exception:  # pragma: no cover - penanganan error umum
        raise HTTPException(
            status_code=500,
            detail="Gagal mengambil daftar meeting.",
        ) from None


@router.post(
    "",
    response_model=MeetingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db)) -> MeetingRead:
    """Buat meeting baru dengan status awal PENDING."""
    meeting = Meeting(title=payload.title.strip(), status=MeetingStatus.PENDING)

    try:
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
    except SQLAlchemyError:  # pragma: no cover - jalur error DB
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Gagal membuat meeting.",
        ) from None

    return MeetingRead.model_validate(meeting)