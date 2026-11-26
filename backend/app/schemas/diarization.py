"""Skema Pydantic untuk diarisasi (Sprint 5)."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class SpeakerRead(BaseModel):
    """Speaker anonim beserta jumlah segmen yang dipetakan."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    speaker_label: str
    display_name: str | None
    created_at: datetime.datetime
    segment_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class DiarizationRead(BaseModel):
    """Status job + speaker yang dikenali untuk satu meeting."""

    meeting_id: uuid.UUID
    status: str  # NOT_STARTED | PROCESSING | COMPLETED | FAILED
    meeting_status: str
    provider: str | None
    model: str | None
    is_mock: bool = False
    error: str | None
    turns_count: int = 0
    mapped_segments: int = 0
    speakers: list[SpeakerRead] = []
    updated_at: datetime.datetime | None = None
