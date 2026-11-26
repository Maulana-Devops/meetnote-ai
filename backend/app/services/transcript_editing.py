"""Edit transkrip dan speaker buatan pengguna (Sprint 6).

Ketika berjalan di samping hasil otomatis Sprint 4/5. Tidak ada provider yang
dipanggil, tidak ada transkripsi ulang, dan tidak ada penulisan ulang oleh AI:
endpoint di sini hanya mengubah kolom yang memang disebut pengguna.

Aturan penting:

* kepemilikan selalu dicek lewat pasangan ``meeting_id`` + id objek, sehingga
  id dari meeting lain tidak bisa dipakai untuk meeting ini;
* teks/nama dibersihkan (trim) lalu divalidasi panjangnya di sini, bukan di
  skema Pydantic, agar semua kegagalan input menghasilkan 400 yang seragam;
* perubahan yang identik dengan data lama tidak di-commit;
* pesan 500 sengaja generik — detail SQLAlchemy tidak pernah dikirim ke UI.

Tidak ada kolom baru untuk menandai "manual vs otomatis". Lihat
``docs/SPRINT6.md`` bagian 9 untuk alasannya.
"""

import uuid

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.diarization import DiarizationJob, DiarizationStatus, Speaker
from ..models.meeting import Meeting, MeetingStatus
from ..models.transcript import TranscriptSegment, TranscriptionJob, TranscriptionStatus
from ..schemas.diarization import SpeakerRead
from ..schemas.transcription import TranscriptSegmentRead

# Batas wajar untuk satu segmen dan untuk nama yang diketik pengguna.
# 255 mengikuti panjang kolom `speakers.display_name` yang sudah ada.
MAX_SEGMENT_TEXT_CHARS = 10_000
MAX_SPEAKER_DISPLAY_NAME_CHARS = 255


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if meeting is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Meeting tidak ditemukan.",
        )
    return meeting


def _ensure_no_active_jobs(db: Session, meeting: Meeting) -> None:
    """Edit ditolak saat hasilnya bisa ditimpa job background."""
    transcription = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == meeting.id)
        .first()
    )
    diarization = (
        db.query(DiarizationJob)
        .filter(DiarizationJob.meeting_id == meeting.id)
        .first()
    )
    if (
        meeting.status == MeetingStatus.TRANSCRIBING
        or (transcription is not None and transcription.status == TranscriptionStatus.PROCESSING)
        or (diarization is not None and diarization.status == DiarizationStatus.PROCESSING)
    ):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                "Transkripsi atau diarisasi sedang berjalan. "
                "Tunggu hingga selesai sebelum mengedit."
            ),
        )


def _get_segment(
    db: Session, meeting_id: uuid.UUID, segment_id: uuid.UUID
) -> TranscriptSegment:
    segment = (
        db.query(TranscriptSegment)
        .filter(
            TranscriptSegment.id == str(segment_id),
            TranscriptSegment.meeting_id == str(meeting_id),
        )
        .first()
    )
    if segment is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Segmen transkrip tidak ditemukan pada meeting ini.",
        )
    return segment


def _get_speaker(
    db: Session, meeting_id: uuid.UUID, speaker_id: uuid.UUID
) -> Speaker:
    """Cari speaker yang benar-benar milik meeting ini.

    Satu pesan untuk speaker tidak ada maupun speaker meeting lain: tidak ada
    informasi kepemilikan lintas meeting yang bocor lewat response.
    """
    speaker = (
        db.query(Speaker)
        .filter(
            Speaker.id == str(speaker_id),
            Speaker.meeting_id == str(meeting_id),
        )
        .first()
    )
    if speaker is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Speaker tidak ditemukan pada meeting ini.",
        )
    return speaker


def _validate_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Teks segmen tidak boleh kosong.",
        )
    if len(cleaned) > MAX_SEGMENT_TEXT_CHARS:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Teks segmen terlalu panjang (maksimal "
                f"{MAX_SEGMENT_TEXT_CHARS} karakter)."
            ),
        )
    return cleaned


def _validate_display_name(display_name: str | None) -> str | None:
    """None = kembalikan ke label anonim; string kosong ditolak."""
    if display_name is None:
        return None
    cleaned = display_name.strip()
    if not cleaned:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                "Nama tampilan tidak boleh kosong. "
                "Kirim null untuk kembali memakai label anonim."
            ),
        )
    if len(cleaned) > MAX_SPEAKER_DISPLAY_NAME_CHARS:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Nama tampilan terlalu panjang (maksimal "
                f"{MAX_SPEAKER_DISPLAY_NAME_CHARS} karakter)."
            ),
        )
    return cleaned


def _commit_or_500(db: Session, message: str) -> None:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        # Jangan sertakan `exc`: bisa memuat detail database/internal.
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message,
        ) from exc


def _speaker_read(db: Session, speaker: Speaker) -> SpeakerRead:
    """Baca speaker + jumlah segmen dengan cara yang sama seperti GET diarisasi."""
    segment_count = (
        db.query(func.count(TranscriptSegment.id))
        .filter(TranscriptSegment.speaker_id == speaker.id)
        .scalar()
        or 0
    )
    return SpeakerRead(
        id=uuid.UUID(speaker.id),
        meeting_id=uuid.UUID(speaker.meeting_id),
        speaker_label=speaker.speaker_label,
        display_name=speaker.display_name,
        created_at=speaker.created_at,
        segment_count=int(segment_count),
    )


def update_segment_text(
    db: Session,
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    text: str,
) -> TranscriptSegmentRead:
    """Ubah hanya `text`. ID, timestamp, sequence, dan speaker dipertahankan."""
    meeting = _get_meeting(db, meeting_id)
    _ensure_no_active_jobs(db, meeting)
    segment = _get_segment(db, meeting_id, segment_id)

    cleaned = _validate_text(text)
    if cleaned != segment.text:
        segment.text = cleaned
        _commit_or_500(db, "Gagal menyimpan perubahan teks segmen.")

    return TranscriptSegmentRead.model_validate(segment)


def update_speaker_display_name(
    db: Session,
    meeting_id: uuid.UUID,
    speaker_id: uuid.UUID,
    display_name: str | None,
) -> SpeakerRead:
    """Ubah nama tampilan user, atau hapus dengan `null`.

    `speaker_label` tidak pernah diubah supaya mapping anonim tetap stabil.
    """
    meeting = _get_meeting(db, meeting_id)
    _ensure_no_active_jobs(db, meeting)
    speaker = _get_speaker(db, meeting_id, speaker_id)

    cleaned = _validate_display_name(display_name)
    if cleaned != speaker.display_name:
        speaker.display_name = cleaned
        _commit_or_500(db, "Gagal menyimpan nama tampilan speaker.")

    return _speaker_read(db, speaker)


def assign_segment_speaker(
    db: Session,
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    speaker_id: uuid.UUID | None,
) -> TranscriptSegmentRead:
    """Petakan segmen ke speaker satu meeting yang sama, atau lepaskan."""
    meeting = _get_meeting(db, meeting_id)
    _ensure_no_active_jobs(db, meeting)
    segment = _get_segment(db, meeting_id, segment_id)

    speaker = _get_speaker(db, meeting_id, speaker_id) if speaker_id is not None else None
    target_id = speaker.id if speaker is not None else None

    if segment.speaker_id != target_id:
        # Set relasi (bukan hanya FK) agar response langsung memakai speaker baru.
        segment.speaker = speaker
        _commit_or_500(db, "Gagal mengubah speaker segmen.")

    return TranscriptSegmentRead.model_validate(segment)
