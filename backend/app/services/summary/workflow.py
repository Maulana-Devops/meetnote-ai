"""Workflow ringkasan AI Sprint 7.

Alur:

1. ``prepare_summary`` memvalidasi meeting, transkrip selesai, ketiadaan job
   STT/diarisasi aktif, konfigurasi provider, dan duplikat sebelum membuat job
   PROCESSING. Ringkasan lama sengaja dipertahankan sampai hasil baru valid.
2. ``run_summary`` berjalan di FastAPI BackgroundTasks dengan sesi DB sendiri.
   Provider dipanggil, respons divalidasi, referensi segmen dicek terhadap
   database, lalu ringkasan disimpan dan job ditandai COMPLETED.
3. Kegagalan apa pun hanya mengubah job menjadi FAILED. Transkrip, audio,
   speaker, dan ringkasan lama tidak pernah dihapus.

Tidak ada action item, assignee, atau deadline dalam kontrak Sprint 7.
"""

import math
import uuid

from fastapi import HTTPException, status as http_status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from ...core.config import settings
from ...core.job_logging import JobRunLog, log_recovery_event
from ...database.session import SessionLocal
from ...models.diarization import DiarizationJob, DiarizationStatus
from ...models.meeting import Meeting
from ...models.summary import MeetingSummary, SummaryJob, SummaryStatus
from ...models.transcript import TranscriptSegment, TranscriptionJob, TranscriptionStatus
from ...schemas.summary import SummaryRead
from .. import job_guard
from ..llm.base import (
    SummaryDecision,
    SummaryInput,
    SummaryInputSegment,
    SummaryResult,
    SummaryTopic,
    format_transcript,
)
from ..llm.errors import LlmError, LlmInvalidResultError
from ..llm.registry import create_provider
from ..provider_retry import retry_transient

# Diuji/monkeypatch di test agar provider mock bisa disuntik deterministik.
_create_provider = create_provider

# Toleransi kecil untuk perbandingan timestamp yang dilaporkan model dengan
# timestamp asli di database. Waktu yang disimpan selalu diambil dari database.
_TIME_TOLERANCE_SECONDS = 0.5


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting tidak ditemukan.")
    return meeting


def _get_job(db: Session, meeting_id: uuid.UUID) -> SummaryJob | None:
    return (
        db.query(SummaryJob).filter(SummaryJob.meeting_id == str(meeting_id)).first()
    )


def _get_summary(db: Session, meeting_id: uuid.UUID) -> MeetingSummary | None:
    return (
        db.query(MeetingSummary)
        .filter(MeetingSummary.meeting_id == str(meeting_id))
        .first()
    )


def _get_segments(db: Session, meeting_id: uuid.UUID) -> list[TranscriptSegment]:
    return (
        db.query(TranscriptSegment)
        .options(joinedload(TranscriptSegment.speaker))
        .filter(TranscriptSegment.meeting_id == str(meeting_id))
        .order_by(TranscriptSegment.sequence.asc())
        .all()
    )


def _ensure_no_active_upstream_jobs(db: Session, meeting_id: uuid.UUID) -> None:
    """Ringkasan tidak boleh berjalan bersamaan dengan STT/diarisasi."""
    transcription_job = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == str(meeting_id))
        .first()
    )
    if (
        transcription_job is not None
        and transcription_job.status == TranscriptionStatus.PROCESSING
    ):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Transkripsi sedang berjalan. Tunggu hingga selesai.",
        )

    diarization_job = (
        db.query(DiarizationJob)
        .filter(DiarizationJob.meeting_id == str(meeting_id))
        .first()
    )
    if (
        diarization_job is not None
        and diarization_job.status == DiarizationStatus.PROCESSING
    ):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Diarisasi sedang berjalan. Tunggu hingga selesai.",
        )


def _build_input(
    meeting: Meeting,
    segments: list[TranscriptSegment],
) -> SummaryInput:
    """Siapkan teks transkrip dan terapkan batas karakter backend."""
    rows = [
        SummaryInputSegment(
            id=str(segment.id),
            text=str(segment.text),
            start_seconds=float(segment.start_seconds),
            end_seconds=float(segment.end_seconds),
            # Sprint 6: display_name buatan pengguna lebih diutamakan;
            # jika tidak ada, pakai label anonim seperti "Speaker 1".
            speaker_display_name=(
                segment.speaker_display_name or segment.speaker_label or None
            ),
        )
        for segment in segments
    ]
    output_language = settings.LLM_OUTPUT_LANGUAGE.strip() or None
    data = SummaryInput(
        meeting_title=str(meeting.title),
        segments=rows,
        output_language=output_language,
    )
    rendered = format_transcript(data)
    if len(rendered) > settings.LLM_MAX_INPUT_CHARACTERS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Transkrip terlalu panjang untuk ringkasan sekali jalan "
                f"({len(rendered)} > {settings.LLM_MAX_INPUT_CHARACTERS} karakter)."
            ),
        )
    return data


def _to_read(
    db: Session,
    meeting: Meeting,
    job: SummaryJob | None,
) -> SummaryRead:
    summary = _get_summary(db, meeting.id)
    provider = job.provider if job and job.provider else (
        summary.provider if summary else None
    )
    model = job.model if job and job.model else (summary.model if summary else None)
    return SummaryRead(
        meeting_id=uuid.UUID(meeting.id),
        status=job.status if job else SummaryStatus.NOT_STARTED,
        meeting_status=meeting.status,
        provider=provider,
        model=model,
        is_mock=bool(summary.is_mock) if summary else False,
        error=job.error if job else None,
        overview=str(summary.overview) if summary else "",
        topics=list(summary.topics) if summary else [],
        decisions=list(summary.decisions) if summary else [],
        created_at=summary.created_at if summary else None,
        updated_at=summary.updated_at if summary else (job.updated_at if job else None),
    )


def get_summary(db: Session, meeting_id: uuid.UUID) -> SummaryRead:
    """Ambil status + ringkasan terakhir. Aman untuk polling."""
    meeting = _get_meeting(db, meeting_id)
    return _to_read(db, meeting, _get_job(db, meeting_id))


def clear_summary(db: Session, meeting_id: uuid.UUID) -> tuple[int, int]:
    """Hapus ringkasan + job saja. Audio, transkrip, dan speaker tidak disentuh."""
    _get_meeting(db, meeting_id)
    summary = _get_summary(db, meeting_id)
    job = _get_job(db, meeting_id)
    if summary is not None:
        db.delete(summary)
    if job is not None:
        db.delete(job)
    return (1 if summary is not None else 0, 1 if job is not None else 0)


def prepare_summary(db: Session, meeting_id: uuid.UUID) -> SummaryRead:
    """Validasi awal + buat job PROCESSING sebelum task background jalan.

    POST dipakai untuk generate, retry setelah FAILED, dan regenerate setelah
    COMPLETED. Regenerasi tidak menghapus ringkasan lama; ringkasan lama baru
    diganti di ``run_summary`` setelah hasil baru divalidasi.
    """
    meeting = _get_meeting(db, meeting_id)

    # Sprint 9: seluruh urutan cek + klaim berada dalam satu mutex per meeting.
    # Tanpa ini dua request bisa sama-sama melihat COMPLETED/FAILED lalu
    # menjadwalkan dua task provider yang menimpa satu sama lain.
    with job_guard.job_lock("summary", meeting_id):
        job = _get_job(db, meeting_id)
        if job is not None and job.status == SummaryStatus.PROCESSING:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ringkasan untuk meeting ini sedang diproses.",
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

        # Batas input dicek di request thread supaya error 422 langsung terlihat UI.
        _build_input(meeting, segments)

        run_token = job_guard.new_run_token()
        try:
            if job is None:
                job = SummaryJob(
                    meeting_id=str(meeting_id),
                    status=SummaryStatus.PROCESSING,
                    provider=provider.name,
                    model=provider.model,
                    error=None,
                    run_token=run_token,
                )
                db.add(job)
            else:
                claimed = job_guard.try_claim_existing(
                    db,
                    model=SummaryJob,
                    meeting_id=meeting_id,
                    processing_status=SummaryStatus.PROCESSING,
                    run_token=run_token,
                    provider=provider.name,
                    model_name=provider.model,
                )
                if not claimed:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail="Ringkasan untuk meeting ini sedang diproses.",
                    )
            db.commit()
            db.refresh(job)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ringkasan untuk meeting ini sedang diproses.",
            ) from exc
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(
                status_code=500, detail="Gagal menyiapkan ringkasan."
            ) from None

    return _to_read(db, meeting, job)


def _validate_references(
    result: SummaryResult,
    segments: list[TranscriptSegment],
) -> tuple[list[SummaryTopic], list[SummaryDecision]]:
    """Pastikan setiap referensi milik meeting ini dan waktu cocok."""
    by_id = {str(segment.id): segment for segment in segments}

    def resolve(segment_ids: tuple[str, ...], start: float, end: float, label: str):
        if not segment_ids:
            raise LlmInvalidResultError(f"{label} tidak memiliki referensi segmen.")
        if len(set(segment_ids)) != len(segment_ids):
            raise LlmInvalidResultError(f"{label} memiliki ID segmen duplikat.")

        referenced = []
        for segment_id in segment_ids:
            segment = by_id.get(segment_id)
            if segment is None:
                # Invalid reference = AI output error. Jangan pernah disimpan.
                raise LlmInvalidResultError(
                    f"{label} merujuk segmen yang tidak termasuk meeting ini."
                )
            referenced.append(segment)

        actual_start = min(float(segment.start_seconds) for segment in referenced)
        actual_end = max(float(segment.end_seconds) for segment in referenced)
        for reported, actual, field in (
            (start, actual_start, "start_seconds"),
            (end, actual_end, "end_seconds"),
        ):
            if not math.isfinite(reported) or abs(reported - actual) > _TIME_TOLERANCE_SECONDS:
                raise LlmInvalidResultError(
                    f"{label} memiliki {field} yang tidak cocok dengan transkrip."
                )
        return tuple(segment_ids), actual_start, actual_end

    topics: list[SummaryTopic] = []
    for topic in result.topics:
        ids, start, end = resolve(
            topic.segment_ids,
            topic.start_seconds,
            topic.end_seconds,
            "Topik",
        )
        topics.append(
            SummaryTopic(
                title=topic.title,
                detail=topic.detail,
                segment_ids=ids,
                start_seconds=start,
                end_seconds=end,
            )
        )

    decisions: list[SummaryDecision] = []
    for decision in result.decisions:
        ids, start, end = resolve(
            decision.segment_ids,
            decision.start_seconds,
            decision.end_seconds,
            "Keputusan",
        )
        decisions.append(
            SummaryDecision(
                text=decision.text,
                segment_ids=ids,
                start_seconds=start,
                end_seconds=end,
            )
        )

    return topics, decisions


def _serialize_topics(topics: list[SummaryTopic]) -> list[dict]:
    return [
        {
            "title": topic.title,
            "detail": topic.detail,
            "segment_ids": list(topic.segment_ids),
            "start_seconds": topic.start_seconds,
            "end_seconds": topic.end_seconds,
        }
        for topic in topics
    ]


def _serialize_decisions(decisions: list[SummaryDecision]) -> list[dict]:
    return [
        {
            "text": decision.text,
            "segment_ids": list(decision.segment_ids),
            "start_seconds": decision.start_seconds,
            "end_seconds": decision.end_seconds,
        }
        for decision in decisions
    ]


def _mark_failed(
    meeting_id: uuid.UUID,
    message: str,
    run_token: str | None = None,
) -> None:
    """Tandai FAILED hanya untuk eksekusi yang masih aktif (Sprint 9)."""
    db = SessionLocal()
    try:
        job = (
            db.query(SummaryJob)
            .filter(
                SummaryJob.meeting_id == str(meeting_id),
                SummaryJob.status == SummaryStatus.PROCESSING,
                SummaryJob.run_token == run_token,
            )
            .first()
        )
        if job is None:
            return
        job.status = SummaryStatus.FAILED
        job.error = message
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    finally:
        db.close()


def run_summary(meeting_id: uuid.UUID) -> None:
    """Background task: panggil LLM, validasi, lalu simpan ringkasan."""
    db = SessionLocal()
    run_log: JobRunLog | None = None
    try:
        meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
        if meeting is None:
            return

        job = _get_job(db, meeting_id)
        if job is None or job.status != SummaryStatus.PROCESSING:
            return

        run_token = job.run_token
        run_log = JobRunLog(
            job_type="summary",
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
                "Transkrip tidak ditemukan saat ringkasan dimulai.",
                run_token,
            )
            run_log.failed(RuntimeError("segments_missing"))
            return

        try:
            data = _build_input(meeting, segments)
            provider = _create_provider(job.provider or settings.LLM_PROVIDER)
            result: SummaryResult = retry_transient(
                lambda: provider.summarize(data),
                job_type="summary",
                meeting_id=str(meeting_id),
            )
            topics, decisions = _validate_references(result, segments)
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
                "Terjadi kegagalan tak terduga saat membuat ringkasan.",
                run_token,
            )
            run_log.failed(exc)
            return

        if not job_guard.is_current(
            db,
            job,
            run_token=run_token,
            processing_status=SummaryStatus.PROCESSING,
        ):
            db.rollback()
            run_log.finished("SUPERSEDED", event="job_skipped")
            return

        try:
            summary = _get_summary(db, meeting_id)
            if summary is None:
                summary = MeetingSummary(meeting_id=str(meeting_id))
                db.add(summary)
            summary.overview = result.overview
            summary.topics = _serialize_topics(topics)
            summary.decisions = _serialize_decisions(decisions)
            summary.provider = result.provider
            summary.model = result.model
            summary.is_mock = bool(result.is_mock)

            job.status = SummaryStatus.COMPLETED
            job.error = None
            job.provider = result.provider
            job.model = result.model
            db.commit()
            run_log.finished(SummaryStatus.COMPLETED)
        except Exception as exc:
            db.rollback()
            _mark_failed(
                meeting_id,
                "Gagal menyimpan ringkasan ke database.",
                run_token,
            )
            run_log.failed(exc)
    finally:
        db.close()


def recover_stuck_summaries() -> int:
    """Tandai job PROCESSING yang tertinggal setelah restart sebagai FAILED."""
    db = SessionLocal()
    recovered = 0
    try:
        stuck = (
            db.query(SummaryJob)
            .filter(SummaryJob.status == SummaryStatus.PROCESSING)
            .all()
        )
        for job in stuck:
            job.status = SummaryStatus.FAILED
            job.error = (
                "Proses ringkasan terhenti karena aplikasi dimulai ulang. "
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
    log_recovery_event(job_type="summary", recovered=recovered)
    return recovered
