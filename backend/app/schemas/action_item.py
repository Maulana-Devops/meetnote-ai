"""Skema Pydantic untuk action items (Sprint 8)."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ActionItemSourceRefMixin(BaseModel):
    """Referensi transkrip yang wajib ada pada setiap action item."""

    segment_ids: list[str]
    start_seconds: float
    end_seconds: float


class ActionItemSpeakerOption(BaseModel):
    """Speaker milik meeting yang boleh dipilih sebagai penanggung jawab."""

    id: uuid.UUID
    label: str


class ActionItemRead(ActionItemSourceRefMixin):
    """Satu action item sebagaimana dikirim ke frontend."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    description: str
    assignee_speaker_id: uuid.UUID | None = None
    assignee_text: str | None = None
    deadline_text: str | None = None
    due_date: datetime.date | None = None
    status: str  # OPEN | COMPLETED | CANCELLED
    is_manually_edited: bool = False
    provider: str | None = None
    model: str | None = None
    is_mock: bool = False
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ActionItemListRead(BaseModel):
    """Status job + seluruh action item milik satu meeting."""

    meeting_id: uuid.UUID
    status: str  # NOT_STARTED | PROCESSING | COMPLETED | FAILED
    meeting_status: str
    provider: str | None = None
    model: str | None = None
    is_mock: bool = False
    error: str | None = None
    items: list[ActionItemRead] = Field(default_factory=list)
    speakers: list[ActionItemSpeakerOption] = Field(default_factory=list)
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class ActionItemUpdate(BaseModel):
    """PATCH sebagian field; field yang tidak dikirim tidak diubah.

    ``None`` yang dikirimkan secara eksplisit memang dimaksudkan untuk
    menghapus nilai (mis. assignee atau due_date).
    """

    title: str | None = None
    description: str | None = None
    assignee_speaker_id: uuid.UUID | None = None
    assignee_text: str | None = None
    deadline_text: str | None = None
    due_date: datetime.date | None = None
    status: str | None = None

    model_config = ConfigDict(extra="forbid")
