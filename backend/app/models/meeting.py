"""Model database Meeting.

Menyimpan satu baris data untuk setiap rapat/pertemuan yang dibuat pengguna.
Pada Sprint 1 hanya tersedia field dasar; Sprint 2 menambah relasi ke
``AudioAsset`` (metadata rekaman langsung dari browser).
"""

import datetime
import uuid

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class MeetingStatus:
    """Nilai status yang dipakai aplikasi (bukan tabel terpisah)."""

    # Meeting baru dibuat, pengguna belum menyimpan rekaman.
    PENDING = "PENDING"
    # Rekaman sudah tersimpan di storage dan siap diproses berikutnya.
    UPLOADED = "UPLOADED"
    # Sprint 4: transkripsi sedang berjalan / selesai.
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBED = "TRANSCRIBED"
    # COMPLETED adalah konstanta lama Sprint 1 (belum dipakai UI). Dipertahankan
    # agar kode lama tidak rusak; transkrip sukses memakai TRANSCRIBED.
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


from ..database.session import Base  # noqa: E402  (import setelah konstanta agar rapi)


class Meeting(Base):
    """Tabel `meetings`."""

    __tablename__ = "meetings"

    # Primary key bertipe UUID (disimpan sebagai string di SQLite)
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Judul rapat
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status rapat. Default dipertahankan UPLOADED untuk kompatibilitas
    # dengan data Sprint 1; endpoint POST memakai PENDING.
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=MeetingStatus.UPLOADED
    )

    # Timestamp pembuatan dan pembaruan terakhir
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Satu meeting hanya boleh memiliki satu rekaman (duplikat ditolak API).
    recording: Mapped["AudioAsset | None"] = relationship(
        "AudioAsset",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Sprint 4: satu meeting bisa punya banyak segmen transkrip + satu job status.
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        "TranscriptSegment",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.sequence",
    )
    transcription_job: Mapped["TranscriptionJob | None"] = relationship(
        "TranscriptionJob",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Sprint 5: speaker anonim + status diarisasi dipisah dari transkripsi.
    speakers: Mapped[list["Speaker"]] = relationship(  # noqa: F821
        "Speaker",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )
    diarization_job: Mapped["DiarizationJob | None"] = relationship(  # noqa: F821
        "DiarizationJob",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Sprint 7: ringkasan dan status job ringkasan dipisah dari transkripsi.
    summary: Mapped["MeetingSummary | None"] = relationship(  # noqa: F821
        "MeetingSummary",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )
    summary_job: Mapped["SummaryJob | None"] = relationship(  # noqa: F821
        "SummaryJob",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Sprint 8: action items dan status job ekstraksi dipisah dari ringkasan.
    action_items: Mapped[list["ActionItem"]] = relationship(  # noqa: F821
        "ActionItem",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="ActionItem.created_at",
    )
    action_item_job: Mapped["ActionItemJob | None"] = relationship(  # noqa: F821
        "ActionItemJob",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def has_recording(self) -> bool:
        """Kemudahan untuk response dashboard."""
        return self.recording is not None

    @property
    def has_transcript(self) -> bool:
        """Kemudahan untuk pengecekan UI."""
        return bool(self.transcript_segments)

    @property
    def has_diarization(self) -> bool:
        """Kemudahan untuk pengecekan UI Sprint 5."""
        return bool(self.speakers)

    @property
    def has_summary(self) -> bool:
        """Kemudahan untuk pengecekan UI Sprint 7."""
        return self.summary is not None

    @property
    def has_action_items(self) -> bool:
        """Kemudahan untuk pengecekan UI Sprint 8."""
        return bool(self.action_items)

    def __repr__(self) -> str:  # pragma: no cover - memudahkan debugging
        return f"<Meeting id={self.id} title={self.title!r} status={self.status}>"