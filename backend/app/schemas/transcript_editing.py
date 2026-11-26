"""Skema Pydantic untuk edit transkrip & speaker (Sprint 6).

Request sengaja memakai tipe sederhana. Validasi teks kosong/panjang dan
referensi speaker dilakukan di service agar pesan errornya konsisten (400/404)
dan tidak membocorkan detail database. Field yang bisa dikosongkan dinyatakan
eksplisitnullable: frasa `null` bukan berarti "field tidak dikirim".
"""

import uuid

from pydantic import BaseModel


class TranscriptSegmentTextUpdate(BaseModel):
    """Teks baru untuk satu segmen. Hanya `text` yang boleh diubah."""

    text: str


class SpeakerDisplayNameUpdate(BaseModel):
    """Nama tampilan speaker. `null` mengembalikan ke label anonim."""

    display_name: str | None


class SegmentSpeakerUpdate(BaseModel):
    """Speaker baru untuk satu segmen. `null` melepaskan speaker."""

    speaker_id: uuid.UUID | None
