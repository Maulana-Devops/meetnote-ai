"""Model hasil diarisasi (Sprint 5).

Tabel baru — sengaja tidak menjatuhkan atau membuat ulang tabel lama.
``speakers`` menyimpan label anonim per meeting; ``diarization_jobs`` menyimpan
status proses agar tidak tercampur dengan ``transcription_jobs``.
"""

import datetime
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.session import Base


class DiarizationStatus:
    """Status internal job diarisasi (bukan status Meeting)."""

    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Speaker(Base):
    """Speaker anonim milik satu meeting.

    Tidak ada kolom nama asli/identitas dunia nyata. ``display_name`` sengaja
    opsional dan dikosongkan agar bisa diisi pengguna di sprint berikutnya.
    """

    __tablename__ = "speakers"
    __table_args__ = (
        UniqueConstraint("meeting_id", "speaker_label", name="uq_speaker_meeting_label"),
        Index("ix_speaker_meeting_label", "meeting_id", "speaker_label"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Label deterministik: Speaker 1, Speaker 2, ... (unik per meeting).
    speaker_label: Mapped[str] = mapped_column(String(50), nullable=False)

    # Opsional, belum dipakai UI Sprint 5. Bukan identitas dari provider.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821
        "Meeting", back_populates="speakers"
    )
    segments: Mapped[list["TranscriptSegment"]] = relationship(  # noqa: F821
        "TranscriptSegment", back_populates="speaker"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Speaker meeting={self.meeting_id} label={self.speaker_label!r}>"


class DiarizationJob(Base):
    """Status satu proses diarisasi per meeting."""

    __tablename__ = "diarization_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DiarizationStatus.NOT_STARTED
    )
    # Sprint 9: token unik per percobaan (lihat TranscriptionJob.run_token).
    run_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Pesan aman untuk UI; tidak pernah memuat API key atau header mentah.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    turns_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mapped_segments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821
        "Meeting", back_populates="diarization_job"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DiarizationJob meeting={self.meeting_id} status={self.status}>"
