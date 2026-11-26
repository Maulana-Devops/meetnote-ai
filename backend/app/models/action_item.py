"""Model action items (Sprint 8).

Tiga tabel BARU, sengaja tidak mengubah atau menjatuhkan tabel lama:

* ``action_items``        — satu baris per action item yang berhasil diekstrak;
* ``action_item_sources`` — referensi segmen dengan foreign key sungguhan;
* ``action_item_jobs``    — status proses ekstraksi, terpisah dari STT/diarisasi/
                            ringkasan.

Regenerasi tidak menghapus data lama sampai hasil baru divalidasi. Item yang
pernah disunting pengguna ditandai ``is_manually_edited`` dan dipertahankan.
"""

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.session import Base


class ActionItemStatus:
    """Status item yang dapat diubah pengguna."""

    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    ALL = (OPEN, COMPLETED, CANCELLED)


class ActionExtractionStatus:
    """Status internal job ekstraksi action items (bukan status item)."""

    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ActionItem(Base):
    """Satu tugas/tindak lanjut yang didukung oleh transkrip."""

    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Penanggung jawab: hanya diisi jika eksplisit dan dapat dipetakan ke
    # speaker milik meeting yang sama. assignee_text menyimpan frasa tekstual.
    assignee_speaker_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("speakers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assignee_text: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Frasa asli dari transkrip; due_date hanya untuk tanggal yang tidak ambigu.
    deadline_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActionItemStatus.OPEN
    )

    # Waktu agregat dinormalisasi dari segmen di database (bukan dari AI).
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # True setelah pengguna mengedit field/status — dipertahankan saat regenerasi.
    is_manually_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821
        "Meeting", back_populates="action_items"
    )
    assignee_speaker: Mapped["Speaker | None"] = relationship(  # noqa: F821
        "Speaker", foreign_keys=[assignee_speaker_id]
    )
    sources: Mapped[list["ActionItemSource"]] = relationship(
        "ActionItemSource",
        back_populates="action_item",
        cascade="all, delete-orphan",
        order_by="ActionItemSource.sequence",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ActionItem meeting={self.meeting_id} title={self.title!r}>"


class ActionItemSource(Base):
    """Satu segmen transkrip yang mendukung action item (referensi nyata)."""

    __tablename__ = "action_item_sources"

    action_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("action_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    segment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("transcript_segments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    action_item: Mapped["ActionItem"] = relationship(
        "ActionItem", back_populates="sources"
    )
    segment: Mapped["TranscriptSegment"] = relationship(  # noqa: F821
        "TranscriptSegment", foreign_keys=[segment_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ActionItemSource item={self.action_item_id} segment={self.segment_id}>"


class ActionItemJob(Base):
    """Status satu proses ekstraksi action items per meeting."""

    __tablename__ = "action_item_jobs"

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
        String(20), nullable=False, default=ActionExtractionStatus.NOT_STARTED
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
        "Meeting", back_populates="action_item_job"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ActionItemJob meeting={self.meeting_id} status={self.status}>"
