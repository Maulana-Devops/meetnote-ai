"""Skema Pydantic untuk metadata audio."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class AudioAssetRead(BaseModel):
    """Informasi rekaman yang dikembalikan ke frontend.

    ``storage_path`` sengaja tidak diekspos; client memakai ``playback_url``.
    """

    id: uuid.UUID
    meeting_id: uuid.UUID
    original_filename: str
    storage_filename: str
    mime_type: str
    file_size_bytes: int
    duration_seconds: float
    created_at: datetime.datetime
    playback_url: str

    model_config = ConfigDict(from_attributes=True)