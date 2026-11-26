"""Model hasil transkripsi (Sprint 4).

Tabel baru — sengaja TIDAK mengubah tabel ``meetings`` dan ``audio_assets``.
Dua tabel dipakai:

* ``transcript_segments`` — baris transkrip dengan urutan dan timestamp.
* ``transcription_jobs``  — status proses + error, satu baris per meeting.

Memisahkan status proses dari ``meetings.status`` membuat GET transcription
tetap bisa menampilkan error walaupun status meeting sudah diubah.
"""

import datetime
import uuid

from sqlalchemy import (
    Boolean,
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


class TranscriptionStatus:
    """Status internal job transkripsi (bukan status Meeting)."""

    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TranscriptSegment(Base):
    """Satu segmen teks dengan timestamp relatif terhadap audio."""

    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("meeting_id", "sequence", name="uq_transcript_meeting_sequence"),
        Index("ix_transcript_meeting_sequence", "meeting_id", "sequence"),
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

    # Teks persis dari provider — tidak ada teks fiksi yang dibuat aplikasi.
    text: Mapped[str] = mapped_column(Text, nullable=False)

    start_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    end_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    # Urutan deterministik dari provider atau nomor urut hasil normalisasi.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Sprint 5: opsional. Segment lama tetap valid dengan NULL.
    speaker_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("speakers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821 - forward ref
        "Meeting", back_populates="transcript_segments"
    )
    speaker: Mapped["Speaker | None"] = relationship(  # noqa: F821
        "Speaker", back_populates="segments", foreign_keys=[speaker_id]
    )

    @property
    def speaker_label(self) -> str | None:
        """Label anonim untuk UI; None berarti tidak ada mapping andal."""
        return self.speaker.speaker_label if self.speaker is not None else None

    @property
    def speaker_display_name(self) -> str | None:
        """Nama yang diberikan pengguna, bukan identitas dari audio.

        Sprint 6: UI menampilkan ini bila ada, jika tidak memakai
        ``speaker_label``. Properti ini tidak menambah kolom database —
        nilainya berasal dari relasi ``speaker`` yang sudah ada.
        """
        return self.speaker.display_name if self.speaker is not None else None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TranscriptSegment meeting={self.meeting_id} seq={self.sequence}>"


class TranscriptionJob(Base):
    """Status satu proses transkripsi per meeting."""

    __tablename__ = "transcription_jobs"

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
        String(20), nullable=False, default=TranscriptionStatus.NOT_STARTED
    )
    # Sprint 9: token unik per percobaan. Background task yang tertinggal tidak
    # boleh menimpa hasil/gagal job yang lebih baru.
    run_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Pesan error aman untuk ditampilkan (tidak mengandung API key).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # False berarti provider hanya mengembalikan teks utuh tanpa timestamp asli.
    has_timestamps: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821 - forward ref
        "Meeting", back_populates="transcription_job"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TranscriptionJob meeting={self.meeting_id} status={self.status}>"
