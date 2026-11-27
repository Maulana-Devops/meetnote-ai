"""Workflow action items Sprint 8.

Alur:

1. ``prepare_action_items`` memvalidasi meeting, transkrip selesai, ketiadaan job
   STT/diarisasi aktif, provider, batas input, dan duplikat sebelum membuat job
   PROCESSING. Action item lama sengaja dipertahankan sampai hasil baru valid.
2. ``run_action_items`` berjalan di FastAPI BackgroundTasks dengan sesi DB
   sendiri. Respons provider divalidasi (segmen, waktu, speaker) lalu ditulis
   dalam SATU transaksi: item AI lama diganti, item hasil edit pengguna tetap.
3. Kegagalan apa pun hanya mengubah job menjadi FAILED. Transkrip, audio,
   speaker, ringkasan, dan action item lama tidak pernah dihapus.

Regenerasi gagal tidak mengubah data lama karena validasi terjadi sebelum
transaksi penulisan dan commit yang gagal di-rollback.
"""

import math
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status as http_status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from ...core.config import settings
from ...core.job_logging import JobRunLog, log_recovery_event
from ...database.session import SessionLocal
from ...models.action_item import (
    ActionExtractionStatus,
    ActionItem,
    ActionItemJob,
    ActionItemSource,
    ActionItemStatus,
)
from ...models.diarization import DiarizationJob, DiarizationStatus, Speaker
from ...models.meeting import Meeting
from ...models.transcript import TranscriptSegment, TranscriptionJob, TranscriptionStatus
from ...schemas.action_item import (
    ActionItemListRead,
    ActionItemRead,
    ActionItemSpeakerOption,
    ActionItemUpdate,
)
from .. import job_guard
from ..llm.base import (
    ActionItemExtractionResult,
    ActionItemInput,
    ActionItemInputSegment,
    ExtractedActionItem,
    format_action_items_input,
)
from ..llm.errors import LlmError, LlmInvalidResultError
from ..llm.registry import create_provider

# Seam yang sama dengan Sprint 4/5/7 agar test bisa menyuntik provider mock.
_create_provider = create_provider

_TIME_TOLERANCE_SECONDS = 0.5
_MAX_TEXT_LENGTH = 255
_MAX_DESCRIPTION_LENGTH = 2000


@dataclass(frozen=True)
class _NormalizedItem:
    """Hasil AI setelah referensi dan waktu dinormalisasi dari database."""

    source: ExtractedActionItem
    assignee_speaker_id: str | None
    segment_ids: tuple[str, ...]
    start_seconds: float
    end_seconds: float


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting tidak ditemukan.")
    return meeting


def _get_job(db: Session, meeting_id: uuid.UUID) -> ActionItemJob | None:
    return (
        db.query(ActionItemJob)
        .filter(ActionItemJob.meeting_id == str(meeting_id))
        .first()
    )


def _get_items(db: Session, meeting_id: uuid.UUID) -> list[ActionItem]:
    return (
        db.query(ActionItem)
        .options(joinedload(ActionItem.sources))
        .filter(ActionItem.meeting_id == str(meeting_id))
        .order_by(ActionItem.created_at.asc())
        .all()
    )


def _get_segments(db: Session, meeting_id: uuid.UUID) -> list[TranscriptSegment]:
    return (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.meeting_id == str(meeting_id))
        .order_by(TranscriptSegment.sequence.asc())
        .all()
    )


def _get_speakers(db: Session, meeting_id: uuid.UUID) -> list[Speaker]:
    return (
        db.query(Speaker)
        .filter(Speaker.meeting_id == str(meeting_id))
        .order_by(Speaker.speaker_label.asc())
        .all()
    )


def _speaker_labels(speakers: list[Speaker]) -> dict[str, str]:
    """Petakan label tampilan ke id speaker; label ganda dianggap ambigu."""
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for speaker in speakers:
        label = (speaker.display_name or speaker.speaker_label or "").strip()
        if not label:
            continue
        if label in mapping:
            ambiguous.add(label)
        else:
            mapping[label] = str(speaker.id)
    for label in ambiguous:
        mapping.pop(label, None)
    return mapping


def _speaker_options(speakers: list[Speaker]) -> list[ActionItemSpeakerOption]:
    return [
        ActionItemSpeakerOption(
            id=uuid.UUID(str(speaker.id)),
            label=str(speaker.display_name or speaker.speaker_label or speaker.id),
        )
        for speaker in speakers
    ]


def _ensure_no_active_upstream_jobs(db: Session, meeting_id: uuid.UUID) -> None:
    """Ekstraksi tidak boleh berjalan bersamaan dengan STT/diarisasi."""
    for job_model, message in (
        (TranscriptionJob, "Transkripsi sedang berjalan. Tunggu hingga selesai."),
        (DiarizationJob, "Diarisasi sedang berjalan. Tunggu hingga selesai."),
    ):
        active = (
            db.query(job_model)
            .filter(job_model.meeting_id == str(meeting_id))
            .first()
        )
        if (
            active is not None
            and active.status
            in (TranscriptionStatus.PROCESSING, DiarizationStatus.PROCESSING)
        ):
            raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=message)


def _build_input(
    meeting: Meeting,
    segments: list[TranscriptSegment],
    speakers: list[Speaker],
) -> ActionItemInput:
    """Siapkan teks transkrip, speaker, dan batas karakter backend."""
    rows = [
        ActionItemInputSegment(
            id=str(segment.id),
            text=str(segment.text),
            start_seconds=float(segment.start_seconds),
            end_seconds=float(segment.end_seconds),
            speaker_display_name=(
                segment.speaker_display_name or segment.speaker_label or None
            ),
        )
        for segment in segments
    ]
    data = ActionItemInput(
        meeting_title=str(meeting.title),
        segments=rows,
        output_language=settings.LLM_OUTPUT_LANGUAGE.strip() or None,
        available_speaker_labels=tuple(_speaker_labels(speakers).keys()),
    )
    rendered = format_action_items_input(data)
    if len(rendered) > settings.LLM_MAX_INPUT_CHARACTERS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Transkrip terlalu panjang untuk ekstraksi sekali jalan "
                f"({len(rendered)} > {settings.LLM_MAX_INPUT_CHARACTERS} karakter)."
            ),
        )
    return data


def _item_to_read(item: ActionItem) -> ActionItemRead:
    sources = sorted(item.sources, key=lambda source: source.sequence)
    return ActionItemRead(
        id=uuid.UUID(str(item.id)),
        meeting_id=uuid.UUID(str(item.meeting_id)),
        title=str(item.title),
        description=str(item.description or ""),
        assignee_speaker_id=(
            uuid.UUID(str(item.assignee_speaker_id)) if item.assignee_speaker_id else None
        ),
        assignee_text=item.assignee_text,
        deadline_text=item.deadline_text,
        due_date=item.due_date,
        status=str(item.status),
        is_manually_edited=bool(item.is_manually_edited),
        segment_ids=[str(source.segment_id) for source in sources],
        start_seconds=float(item.start_seconds),
        end_seconds=float(item.end_seconds),
        provider=item.provider,
        model=item.model,
        is_mock=bool(item.is_mock),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _to_read(db: Session, meeting: Meeting, job: ActionItemJob | None) -> ActionItemListRead:
    items = _get_items(db, meeting.id)
    speakers = _get_speakers(db, meeting.id)
    provider = job.provider if job and job.provider else (
        items[0].provider if items else None
    )
    model = job.model if job and job.model else (items[0].model if items else None)
    return ActionItemListRead(
        meeting_id=uuid.UUID(meeting.id),
        status=job.status if job else ActionExtractionStatus.NOT_STARTED,
        meeting_status=meeting.status,
        provider=provider,
        model=model,
        is_mock=any(bool(item.is_mock) for item in items),
        error=job.error if job else None,
        items=[_item_to_read(item) for item in items],
        speakers=_speaker_options(speakers),
        created_at=job.created_at if job else None,
        updated_at=job.updated_at if job else None,
    )


def get_action_items(db: Session, meeting_id: uuid.UUID) -> ActionItemListRead:
    """Ambil status + action item terakhir. Aman untuk polling."""
    meeting = _get_meeting(db, meeting_id)
    return _to_read(db, meeting, _get_job(db, meeting_id))


def clear_action_items(db: Session, meeting_id: uuid.UUID) -> tuple[int, int, int]:
    """Hapus action item + job saja. Audio, transkrip, dan speaker tidak disentuh."""
    _get_meeting(db, meeting_id)
    items = _get_items(db, meeting_id)
    job = _get_job(db, meeting_id)
    source_count = sum(len(item.sources) for item in items)
    for item in items:
        db.delete(item)
    if job is not None:
        db.delete(job)
    return len(items), source_count, (1 if job is not None else 0)


def prepare_action_items(db: Session, meeting_id: uuid.UUID) -> ActionItemListRead:
    """Validasi awal + buat job PROCESSING sebelum task background jalan."""
    meeting = _get_meeting(db, meeting_id)

    # Sprint 9: cek + klaim atomik per meeting dalam satu mutex.
    with job_guard.job_lock("action_items", meeting_id):
        job = _get_job(db, meeting_id)
        if job is not None and job.status == ActionExtractionStatus.PROCESSING:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ekstraksi action items untuk meeting ini sedang berjalan.",
            )

        _ensure_no_active_upstream_jobs(db, meeting_id)

        transcription_job = (
            db.query(TranscriptionJob)
            .filter(TranscriptionJob.meeting_id == str(meeting_id))
            .first()
        )
        segments = _get_segments(db, meeting_id)
        if (
            transcription_job is None
            or transcription_job.status != TranscriptionStatus.COMPLETED
            or not segments
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Transkrip selesai belum tersedia. Jalankan transkripsi terlebih dahulu.",
            )

        try:
            provider = _create_provider()
            provider.validate_configuration()
        except LlmError as exc:
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc

        _build_input(meeting, segments, _get_speakers(db, meeting_id))

        run_token = job_guard.new_run_token()
        try:
            if job is None:
                job = ActionItemJob(
                    meeting_id=str(meeting_id),
                    status=ActionExtractionStatus.PROCESSING,
                    provider=provider.name,
                    model=provider.model,
                    error=None,
                    run_token=run_token,
                )
                db.add(job)
            else:
                claimed = job_guard.try_claim_existing(
                    db,
                    model=ActionItemJob,
                    meeting_id=meeting_id,
                    processing_status=ActionExtractionStatus.PROCESSING,
                    run_token=run_token,
                    provider=provider.name,
                    model_name=provider.model,
                )
                if not claimed:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail="Ekstraksi action items untuk meeting ini sedang berjalan.",
                    )
            db.commit()
            db.refresh(job)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ekstraksi action items untuk meeting ini sedang berjalan.",
            ) from exc
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(
                status_code=500, detail="Gagal menyiapkan ekstraksi action items."
            ) from None

    return _to_read(db, meeting, job)


def _validate_result(
    result: ActionItemExtractionResult,
    segments: list[TranscriptSegment],
    speakers: list[Speaker],
) -> list[_NormalizedItem]:
    """Validasi referensi, waktu, dan speaker sebelum apa pun disimpan."""
    by_id = {str(segment.id): segment for segment in segments}
    label_to_speaker = _speaker_labels(speakers)

    normalized: list[_NormalizedItem] = []
    for item in result.items:
        segment_ids = item.segment_ids
        if not segment_ids:
            raise LlmInvalidResultError("Action item tidak memiliki referensi segmen.")
        if len(set(segment_ids)) != len(segment_ids):
            raise LlmInvalidResultError("Action item memiliki ID segmen duplikat.")

        referenced: list[TranscriptSegment] = []
        for segment_id in segment_ids:
            segment = by_id.get(segment_id)
            if segment is None:
                # Referensi invalid = AI output error. Jangan pernah disimpan.
                raise LlmInvalidResultError(
                    "Action item merujuk segmen yang tidak termasuk meeting ini."
                )
            referenced.append(segment)

        actual_start = min(float(segment.start_seconds) for segment in referenced)
        actual_end = max(float(segment.end_seconds) for segment in referenced)
        for reported, actual, field in (
            (item.start_seconds, actual_start, "start_seconds"),
            (item.end_seconds, actual_end, "end_seconds"),
        ):
            if not math.isfinite(reported) or abs(reported - actual) > _TIME_TOLERANCE_SECONDS:
                raise LlmInvalidResultError(
                    f"Action item memiliki {field} yang tidak cocok dengan transkrip."
                )

        assignee_speaker_id: str | None = None
        if item.assignee_speaker_label is not None:
            assignee_speaker_id = label_to_speaker.get(item.assignee_speaker_label)
            if assignee_speaker_id is None:
                raise LlmInvalidResultError(
                    "Action item memetakan penanggung jawab ke speaker yang tidak tersedia."
                )

        normalized.append(
            _NormalizedItem(
                source=item,
                assignee_speaker_id=assignee_speaker_id,
                segment_ids=segment_ids,
                start_seconds=actual_start,
                end_seconds=actual_end,
            )
        )
    return normalized


def _mark_failed(
    meeting_id: uuid.UUID,
    message: str,
    run_token: str | None = None,
) -> None:
    """Tandai FAILED hanya untuk eksekusi yang masih aktif (Sprint 9)."""
    db = SessionLocal()
    try:
        job = (
            db.query(ActionItemJob)
            .filter(
                ActionItemJob.meeting_id == str(meeting_id),
                ActionItemJob.status == ActionExtractionStatus.PROCESSING,
                ActionItemJob.run_token == run_token,
            )
            .first()
        )
        if job is None:
            return
        job.status = ActionExtractionStatus.FAILED
        job.error = message
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    finally:
        db.close()


def run_action_items(meeting_id: uuid.UUID) -> None:
    """Background task: panggil LLM, validasi, lalu simpan action items."""
    db = SessionLocal()
    run_log: JobRunLog | None = None
    try:
        meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
        if meeting is None:
            return

        job = _get_job(db, meeting_id)
        if job is None or job.status != ActionExtractionStatus.PROCESSING:
            return

        run_token = job.run_token
        run_log = JobRunLog(
            job_type="action_items",
            meeting_id=str(meeting_id),
            job_id=job.id,
            provider=job.provider,
            model=job.model,
        )
        run_log.started()

        segments = _get_segments(db, meeting_id)
        if not segments:
            _mark_failed(
                meeting_id,
                "Transkrip tidak ditemukan saat ekstraksi dimulai.",
                run_token,
            )
            run_log.failed(RuntimeError("segments_missing"))
            return

        speakers = _get_speakers(db, meeting_id)
        try:
            data = _build_input(meeting, segments, speakers)
            provider = _create_provider(job.provider or settings.LLM_PROVIDER)
            result: ActionItemExtractionResult = provider.extract_action_items(data)
            normalized = _validate_result(result, segments, speakers)
        except LlmError as exc:
            db.rollback()
            _mark_failed(meeting_id, str(exc), run_token)
            run_log.failed(exc)
            return
        except HTTPException as exc:
            db.rollback()
            _mark_failed(meeting_id, str(exc.detail), run_token)
            run_log.failed(exc)
            return
        except Exception as exc:
            db.rollback()
            _mark_failed(
                meeting_id,
                "Terjadi kegagalan tak terduga saat mengekstrak action items.",
                run_token,
            )
            run_log.failed(exc)
            return

        if not job_guard.is_current(
            db,
            job,
            run_token=run_token,
            processing_status=ActionExtractionStatus.PROCESSING,
        ):
            db.rollback()
            run_log.finished("SUPERSEDED", event="job_skipped")
            return

        # Hanya item AI lama yang diganti. Item hasil edit pengguna dipertahankan.
        try:
            for old in _get_items(db, meeting_id):
                if not bool(old.is_manually_edited):
                    db.delete(old)

            for entry in normalized:
                source = entry.source
                db.add(
                    ActionItem(
                        meeting_id=str(meeting_id),
                        title=source.title,
                        description=source.description,
                        assignee_speaker_id=entry.assignee_speaker_id,
                        assignee_text=source.assignee_text,
                        deadline_text=source.deadline_text,
                        due_date=source.due_date,
                        status=ActionItemStatus.OPEN,
                        start_seconds=entry.start_seconds,
                        end_seconds=entry.end_seconds,
                        provider=result.provider,
                        model=result.model,
                        is_mock=bool(result.is_mock),
                        sources=[
                            ActionItemSource(segment_id=segment_id, sequence=index)
                            for index, segment_id in enumerate(entry.segment_ids)
                        ],
                    )
                )

            job.status = ActionExtractionStatus.COMPLETED
            job.error = None
            job.provider = result.provider
            job.model = result.model
            db.commit()
            run_log.finished(ActionExtractionStatus.COMPLETED)
        except Exception as exc:
            db.rollback()
            _mark_failed(
                meeting_id,
                "Gagal menyimpan action items ke database.",
                run_token,
            )
            run_log.failed(exc)
    finally:
        db.close()


def update_action_item(
    db: Session,
    meeting_id: uuid.UUID,
    item_id: uuid.UUID,
    update: ActionItemUpdate,
) -> ActionItemRead:
    """PATCH field yang diizinkan; selalu menandai hasil edit pengguna."""
    _get_meeting(db, meeting_id)
    item = (
        db.query(ActionItem)
        .filter(
            ActionItem.id == str(item_id),
            ActionItem.meeting_id == str(meeting_id),
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Action item tidak ditemukan.")

    fields = update.model_fields_set

    if "title" in fields:
        if update.title is None or not update.title.strip():
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Judul action item tidak boleh kosong.",
            )
        title = update.title.strip()
        if len(title) > _MAX_TEXT_LENGTH:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Judul maksimal {_MAX_TEXT_LENGTH} karakter.",
            )
        item.title = title

    if "description" in fields:
        description = (update.description or "").strip()
        if len(description) > _MAX_DESCRIPTION_LENGTH:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Deskripsi maksimal {_MAX_DESCRIPTION_LENGTH} karakter.",
            )
        item.description = description

    if "assignee_speaker_id" in fields:
        if update.assignee_speaker_id is None:
            item.assignee_speaker_id = None
        else:
            speaker = (
                db.query(Speaker)
                .filter(
                    Speaker.id == str(update.assignee_speaker_id),
                    Speaker.meeting_id == str(meeting_id),
                )
                .first()
            )
            if speaker is None:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Speaker penanggung jawab harus berasal dari meeting yang sama.",
                )
            item.assignee_speaker_id = str(update.assignee_speaker_id)

    for field_name in ("assignee_text", "deadline_text"):
        if field_name in fields:
            value = getattr(update, field_name)
            cleaned = value.strip() if isinstance(value, str) else ""
            if len(cleaned) > _MAX_TEXT_LENGTH:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field_name} maksimal {_MAX_TEXT_LENGTH} karakter.",
                )
            setattr(item, field_name, cleaned or None)

    if "due_date" in fields:
        item.due_date = update.due_date

    if "status" in fields:
        if update.status not in ActionItemStatus.ALL:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Status harus OPEN, COMPLETED, atau CANCELLED.",
            )
        item.status = update.status

    item.is_manually_edited = True

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Gagal menyimpan perubahan action item."
        ) from None

    return _item_to_read(item)


def delete_action_item(db: Session, meeting_id: uuid.UUID, item_id: uuid.UUID) -> dict:
    """Hapus satu action item milik meeting ini saja."""
    _get_meeting(db, meeting_id)
    item = (
        db.query(ActionItem)
        .filter(
            ActionItem.id == str(item_id),
            ActionItem.meeting_id == str(meeting_id),
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Action item tidak ditemukan.")

    source_count = len(item.sources)
    try:
        db.delete(item)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Gagal menghapus action item."
        ) from None

    return {
        "detail": "Action item dihapus.",
        "meeting_id": str(meeting_id),
        "item_id": str(item_id),
        "sources_deleted": source_count,
    }


def recover_stuck_action_items() -> int:
    """Tandai job PROCESSING yang tertinggal setelah restart sebagai FAILED."""
    db = SessionLocal()
    recovered = 0
    try:
        stuck = (
            db.query(ActionItemJob)
            .filter(ActionItemJob.status == ActionExtractionStatus.PROCESSING)
            .all()
        )
        for job in stuck:
            job.status = ActionExtractionStatus.FAILED
            job.error = (
                "Proses ekstraksi action items terhenti karena aplikasi dimulai ulang. "
                "Silakan coba lagi."
            )
            job.run_token = None
            recovered += 1
        if recovered:
            db.commit()
    except SQLAlchemyError:
        db.rollback()
        return 0
    finally:
        db.close()
    log_recovery_event(job_type="action_items", recovered=recovered)
    return recovered
