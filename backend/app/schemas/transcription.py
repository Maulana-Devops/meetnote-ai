"""Skema Pydantic untuk transkripsi (Sprint 4)."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class TranscriptSegmentRead(BaseModel):
    """Satu segmen transkrip yang dikirim ke frontend."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    text: str
    start_seconds: float
    end_seconds: float
    sequence: int
    created_at: datetime.datetime
    # Sprint 5: opsional; None berarti tidak ada mapping speaker yang andal.
    speaker_id: uuid.UUID | None = None
    speaker_label: str | None = None
    # Sprint 6: nama yang diketik pengguna. Tidak pernah ditebak dari audio;
    # UI memakai ini bila ada dan jatuh ke `speaker_label` bila null.
    speaker_display_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TranscriptionRead(BaseModel):
    """Status transkripsi + seluruh segmen milik meeting."""

    meeting_id: uuid.UUID
    status: str  # NOT_STARTED | PROCESSING | COMPLETED | FAILED
    meeting_status: str  # status pada tabel meetings
    provider: str | None
    model: str | None
    has_timestamps: bool
    error: str | None
    full_text: str
    segments: list[TranscriptSegmentRead]
    updated_at: datetime.datetime | None = None
