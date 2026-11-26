"""Model ringkasan AI (Sprint 7).

Dua tabel BARU, sengaja tidak mengubah atau menjatuhkan tabel lama:

* ``meeting_summaries`` — satu ringkasan terakhir per meeting;
* ``summary_jobs``      — status proses ringkasan, terpisah dari STT/diarisasi.

Saat regenerasi gagal, baris ringkasan lama tidak dihapus. Job menyimpan error
yang aman ditampilkan ke frontend.
"""

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.session import Base


class SummaryStatus:
    """Status internal job ringkasan (bukan status Meeting)."""

    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeetingSummary(Base):
    """Ringkasan terakhir yang berhasil dibuat untuk satu meeting."""

    __tablename__ = "meeting_summaries"

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

    overview: Mapped[str] = mapped_column(Text, nullable=False)
    # Disimpan sebagai JSON array of object; tiap item memuat referensi segmen.
    topics: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    decisions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # True hanya untuk provider mock; UI menampilkan penanda [MOCK].
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821
        "Meeting", back_populates="summary"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MeetingSummary meeting={self.meeting_id} provider={self.provider!r}>"


class SummaryJob(Base):
    """Status satu proses ringkasan per meeting."""

    __tablename__ = "summary_jobs"

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
        String(20), nullable=False, default=SummaryStatus.NOT_STARTED
    )
    # Sprint 9: token unik per percobaan (lihat TranscriptionJob.run_token).
    run_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Pesan aman untuk UI; tidak pernah memuat API key atau response mentah.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821
        "Meeting", back_populates="summary_job"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SummaryJob meeting={self.meeting_id} status={self.status}>"
