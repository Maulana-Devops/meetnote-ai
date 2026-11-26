"""Endpoint edit transkrip & speaker (Sprint 6).

Semua endpoint memakai PATCH: hanya field yang disebut pengguna yang diubah.
Tidak ada provider yang dipanggil dan tidak ada job background baru.
Validasi kepemilikan, panjang, dan transaksi ada di
``services/transcript_editing.py`` supaya endpoint tetap tipis.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...schemas.diarization import SpeakerRead
from ...schemas.transcription import TranscriptSegmentRead
from ...schemas.transcript_editing import (
    SegmentSpeakerUpdate,
    SpeakerDisplayNameUpdate,
    TranscriptSegmentTextUpdate,
)
from ...services.transcript_editing import (
    assign_segment_speaker,
    update_segment_text,
    update_speaker_display_name,
)
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Transcript Editing"])


@router.patch(
    "/{meeting_id}/transcript/{segment_id}/speaker",
    response_model=TranscriptSegmentRead,
)
def set_segment_speaker(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    payload: SegmentSpeakerUpdate,
    db: Session = Depends(get_db),
) -> TranscriptSegmentRead:
    """Terapkan speaker ID milik meeting yang sama, atau `null`."""
    return assign_segment_speaker(db, meeting_id, segment_id, payload.speaker_id)


@router.patch(
    "/{meeting_id}/transcript/{segment_id}",
    response_model=TranscriptSegmentRead,
)
def edit_segment_text(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    payload: TranscriptSegmentTextUpdate,
    db: Session = Depends(get_db),
) -> TranscriptSegmentRead:
    """Ubah teks satu segmen tanpa menyentuh timestamp atau speaker."""
    return update_segment_text(db, meeting_id, segment_id, payload.text)


@router.patch(
    "/{meeting_id}/speakers/{speaker_id}",
    response_model=SpeakerRead,
)
def edit_speaker_display_name(
    meeting_id: uuid.UUID,
    speaker_id: uuid.UUID,
    payload: SpeakerDisplayNameUpdate,
    db: Session = Depends(get_db),
) -> SpeakerRead:
    """Ubah nama buatan pengguna, atau `null` untuk memakai label anonim."""
    return update_speaker_display_name(db, meeting_id, speaker_id, payload.display_name)
