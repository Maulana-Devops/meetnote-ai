"""Skema Pydantic untuk ringkasan AI (Sprint 7)."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class SummarySourceRefMixin(BaseModel):
    """Referensi waktu/segmen yang wajib ada di topik dan keputusan."""

    segment_ids: list[str]
    start_seconds: float
    end_seconds: float


class SummaryTopicRead(SummarySourceRefMixin):
    title: str
    detail: str


class SummaryDecisionRead(SummarySourceRefMixin):
    text: str


class SummaryRead(BaseModel):
    """Status job + isi ringkasan terakhir untuk satu meeting."""

    meeting_id: uuid.UUID
    status: str  # NOT_STARTED | PROCESSING | COMPLETED | FAILED
    meeting_status: str
    provider: str | None
    model: str | None
    is_mock: bool = False
    error: str | None
    overview: str = ""
    topics: list[SummaryTopicRead] = Field(default_factory=list)
    decisions: list[SummaryDecisionRead] = Field(default_factory=list)
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    model_config = ConfigDict(from_attributes=True)
