"""Model metadata audio hasil rekaman.

File audio disimpan di filesystem (lihat ``core.storage``), bukan di kolom
database. Tabel ini hanya menyimpan metadata dan path relatif.
"""

import datetime
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.session import Base


class AudioAsset(Base):
    """Tabel `audio_assets` (relasi satu-ke-satu dengan Meeting)."""

    __tablename__ = "audio_assets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    meeting_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Nama asli dari browser hanya untuk informasi, bukan untuk path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Nama file aman yang benar-benar ditulis ke disk.
    storage_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Path relatif terhadap STORAGE_DIR, bukan path absolut.
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(  # noqa: F821 - forward ref
        "Meeting", back_populates="recording"
    )

    @property
    def playback_url(self) -> str:
        """URL relatif untuk memutar file (tidak membocorkan path storage)."""
        return f"/api/v1/meetings/{self.meeting_id}/recording/play"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AudioAsset id={self.id} meeting_id={self.meeting_id}>"