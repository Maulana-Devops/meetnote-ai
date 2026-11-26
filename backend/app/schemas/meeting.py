"""Skema Pydantic untuk Meeting."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from .audio import AudioAssetRead


class MeetingBase(BaseModel):
    """Field bersama untuk Meeting."""

    title: str = Field(..., min_length=1, max_length=255, description="Judul rapat")


class MeetingCreate(MeetingBase):
    """Payload untuk membuat Meeting baru."""


class MeetingRead(MeetingBase):
    """Representasi Meeting yang dikembalikan ke client."""

    id: uuid.UUID
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    # Sprint 2: ringkasan rekaman untuk dashboard.
    has_recording: bool = False
    recording: AudioAssetRead | None = None

    # `from_attributes=True` memungkinkan konversi dari objek SQLAlchemy.
    model_config = ConfigDict(from_attributes=True)