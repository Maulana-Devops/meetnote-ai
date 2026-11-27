"""Workflow diarisasi Sprint 5.

Alur mirip Sprint 5 tetapi statusnya disimpan di tabel ``diarization_jobs``:

1. ``prepare_diarization`` memvalidasi meeting, audio, transkrip selesai,
   konfigurasi, dan duplikat sebelum menjadwalkan FastAPI BackgroundTasks.
2. ``run_diarization`` membuka sesi DB sendiri, memanggil provider, memetakan
   speaker turns ke segmen yang sudah ada, lalu menyimpan Speaker + mapping.
3. Kegagalan apa pun hanya mengubah job diarisasi menjadi FAILED. Teks dan
   timestamp transkrip tidak pernah diubah atau dihapus.
"""

import uuid
from collections import defaultdict

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.job_logging import JobRunLog, log_recovery_event
from ...core.storage import resolve_storage_path
from ...database.session import SessionLocal
from ...models.audio_asset import AudioAsset
from ...models.diarization import DiarizationJob, DiarizationStatus, Speaker
from ...models.meeting import Meeting
from ...models.transcript import TranscriptSegment, TranscriptionJob, TranscriptionStatus
from ...schemas.diarization import DiarizationRead, SpeakerRead
from .. import job_guard
from ..provider_retry import retry_transient
from .base import DiarizationResult, DiarizationTurn
from .errors import (
    DiarizationError,
    DiarizationInvalidResultError,
    DiarizationUnsupportedFormatError,
)
from .registry import create_provider

# Diuji/monkeypatch di test agar provider mock bisa disuntik deterministik.
_create_provider = create_provider

_EPSILON = 1e-6


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting tidak ditemukan.")
    return meeting


def _get_job(db: Session, meeting_id: uuid.UUID) -> DiarizationJob | None:
    return (
        db.query(DiarizationJob)
        .filter(DiarizationJob.meeting_id == str(meeting_id))
        .first()
    )


def _speaker_sort_key(label: str) -> tuple[int, int, str]:
    """Urutkan 'Speaker 2' sebelum 'Speaker 10', label lain di belakang."""
    prefix = "Speaker "
    if label.startswith(prefix):
        suffix = label[len(prefix):]
        if suffix.isdigit():
            return (0, int(suffix), label)
    return (1, 0, label)


def _to_read(db: Session, meeting: Meeting, job: DiarizationJob | None) -> DiarizationRead:
    speakers = (
        db.query(Speaker)
        .filter(Speaker.meeting_id == meeting.id)
        .all()
    )
    counts = dict(
        db.query(Speaker.id, func.count(TranscriptSegment.id))
        .outerjoin(
            TranscriptSegment,
            TranscriptSegment.speaker_id == Speaker.id,
        )
        .filter(Speaker.meeting_id == meeting.id)
        .group_by(Speaker.id)
        .all()
    )
    speaker_reads = [
        SpeakerRead(
            id=uuid.UUID(speaker.id),
            meeting_id=uuid.UUID(speaker.meeting_id),
            speaker_label=speaker.speaker_label,
            display_name=speaker.display_name,
            created_at=speaker.created_at,
            segment_count=int(counts.get(speaker.id, 0)),
        )
        for speaker in sorted(speakers, key=lambda item: _speaker_sort_key(item.speaker_label))
    ]

    provider_name = job.provider if job else None
    return DiarizationRead(
        meeting_id=uuid.UUID(meeting.id),
        status=job.status if job else DiarizationStatus.NOT_STARTED,
        meeting_status=meeting.status,
        provider=provider_name,
        model=job.model if job else None,
        is_mock=(provider_name or "").lower() == "mock",
        error=job.error if job else None,
        turns_count=job.turns_count if job else 0,
        mapped_segments=job.mapped_segments if job else 0,
        speakers=speaker_reads,
        updated_at=job.updated_at if job else None,
    )


def get_diarization(db: Session, meeting_id: uuid.UUID) -> DiarizationRead:
    """Ambil status + speaker. Kosong bila belum pernah diarisasi."""
    meeting = _get_meeting(db, meeting_id)
    return _to_read(db, meeting, _get_job(db, meeting_id))


def _remove_speakers_and_assignments(db: Session, meeting_id: uuid.UUID) -> int:
    """Hapus Speaker + semua speaker_id segmen. Job sengaja tidak disentuh."""
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.meeting_id == str(meeting_id))
        .all()
    )
    for segment in segments:
        segment.speaker_id = None

    speakers = db.query(Speaker).filter(Speaker.meeting_id == str(meeting_id)).all()
    for speaker in speakers:
        db.delete(speaker)
    return len(speakers)


def clear_diarization(db: Session, meeting_id: uuid.UUID) -> tuple[int, int]:
    """Hapus Speaker + job saja. Transkrip dan audio tidak disentuh.

    Dipakai endpoint DELETE dan saat transkripsi dibuat ulang. Mengembalikan
    `(jumlah speaker dihapus, jumlah segmen yang dilepaskan)`.
    """
    _get_meeting(db, meeting_id)
    segments = (
        db.query(TranscriptSegment)
        .filter(
            TranscriptSegment.meeting_id == str(meeting_id),
            TranscriptSegment.speaker_id.isnot(None),
        )
        .all()
    )
    unassigned = len(segments)
    for segment in segments:
        segment.speaker_id = None

    speakers = db.query(Speaker).filter(Speaker.meeting_id == str(meeting_id)).all()
    for speaker in speakers:
        db.delete(speaker)

    job = _get_job(db, meeting_id)
    if job is not None:
        db.delete(job)

    return len(speakers), unassigned


def prepare_diarization(db: Session, meeting_id: uuid.UUID) -> DiarizationRead:
    """Validasi awal + buat job PROCESSING sebelum task background jalan."""
    meeting = _get_meeting(db, meeting_id)

    asset = (
        db.query(AudioAsset)
        .filter(AudioAsset.meeting_id == str(meeting_id))
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Rekaman belum tersedia untuk meeting ini.")

    try:
        audio_path = resolve_storage_path(asset.storage_path)
    except ValueError:
        raise HTTPException(
            status_code=500, detail="Path rekaman berada di luar direktori storage; periksa konfigurasi storage."
        ) from None
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="File rekaman tidak ditemukan di storage.")

    with job_guard.job_lock("diarization", meeting_id):
        job = _get_job(db, meeting_id)
        if job is not None and job.status == DiarizationStatus.PROCESSING:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Diarisasi untuk meeting ini sedang berjalan.",
            )

        transcription_job = (
            db.query(TranscriptionJob)
            .filter(TranscriptionJob.meeting_id == str(meeting_id))
            .first()
        )
        segment_count = (
            db.query(func.count(TranscriptSegment.id))
            .filter(TranscriptSegment.meeting_id == str(meeting_id))
            .scalar()
            or 0
        )
        if (
            transcription_job is None
            or transcription_job.status != TranscriptionStatus.COMPLETED
            or segment_count == 0
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Transkrip selesai belum tersedia. Jalankan transkripsi terlebih dahulu.",
            )

        try:
            provider = _create_provider()
            provider.validate_configuration()
            suffix = audio_path.suffix.lower()
            if suffix not in provider.supported_extensions():
                raise DiarizationUnsupportedFormatError(
                    f"Format '{suffix or 'tanpa ekstensi'}' tidak didukung provider diarisasi."
                )
        except DiarizationError as exc:
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc

        file_size = audio_path.stat().st_size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="File rekaman kosong — tidak bisa diarisasi.")
        if file_size > provider.max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Ukuran file {file_size} byte melebihi batas provider "
                    f"{provider.max_file_bytes} byte."
                ),
            )

        try:
            # Satu hasil diarisasi aktif per meeting. flush() dulu agar job lama
            # benar-benar terhapus sebelum unique constraint job baru dicek.
            clear_diarization(db, meeting_id)
            db.flush()

            job = DiarizationJob(
                meeting_id=str(meeting_id),
                status=DiarizationStatus.PROCESSING,
                provider=provider.name,
                model=provider.model,
                error=None,
                turns_count=0,
                mapped_segments=0,
                run_token=job_guard.new_run_token(),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Diarisasi untuk meeting ini sedang berjalan.",
            ) from exc
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(
                status_code=500, detail="Gagal menyiapkan diarisasi."
            ) from None

    # Tidak mengubah Meeting.status: status transkripsi dan diarisasi dipisah.
    return _to_read(db, meeting, job)


def _validate_turns(turns: list[DiarizationTurn]) -> list[DiarizationTurn]:
    """Validasi semua turns; satu nilai buruk membuat job gagal."""
    if not turns:
        raise DiarizationInvalidResultError(
            "Provider diarisasi mengembalikan respons kosong — tidak ada speaker yang disimpan."
        )

    validated: list[DiarizationTurn] = []
    for turn in turns:
        speaker_ref = str(turn.speaker_ref).strip()
        if not speaker_ref:
            raise DiarizationInvalidResultError(
                "Provider mengembalikan referensi speaker tidak dikenali."
            )
        if turn.start_seconds < 0 or turn.end_seconds < 0:
            raise DiarizationInvalidResultError(
                "Provider mengembalikan timestamp diarisasi negatif."
            )
        if turn.end_seconds < turn.start_seconds:
            raise DiarizationInvalidResultError(
                "Provider mengembalikan waktu akhir diarisasi sebelum waktu mulai."
            )
        validated.append(
            DiarizationTurn(speaker_ref, turn.start_seconds, turn.end_seconds)
        )
    return validated


def assign_speaker_labels(turns: list[DiarizationTurn]) -> dict[str, str]:
    """Buat label anonim deterministik dari referensi provider.

    Referensi numerik diurutkan sebagai angka (2 sebelum 10), lalu label
    "Speaker 1..n". Tidak ada dua referensi yang boleh mendapat label sama.
    """

    def key(ref: str) -> tuple[int, int, str]:
        if ref.isdigit():
            return (0, int(ref), ref)
        return (1, 0, ref)

    references = sorted({turn.speaker_ref for turn in turns}, key=key)
    return {ref: f"Speaker {index}" for index, ref in enumerate(references, start=1)}


def map_turns_to_segments(
    segments: list[TranscriptSegment],
    turns: list[DiarizationTurn],
    labels: dict[str, str],
    *,
    min_overlap_ratio: float | None = None,
    min_overlap_seconds: float | None = None,
) -> dict[str, str]:
    """Petakan segmen ke referensi speaker dengan overlap temporal terbesar.

    Strategi (didokumentasikan di docs/SPRINT5.md):

    * overlap = irisan `[start, end]` segmen dan turn;
    * overlap dijumlahkan per referensi speaker (mendukung overlapping speech);
    * pemenang harus melebihi ambang rasio durasi segmen dan ambang detik;
    * dua referensi dengan overlap terbaik sama → **ambiguous**, tidak dipetakan;
    * segmen tanpa timestamp asli / durasi nol → tidak dipetakan;
    * teks dan timestamp segmen tidak pernah diubah.
    """
    ratio = (
        settings.DIARIZATION_MIN_OVERLAP_RATIO
        if min_overlap_ratio is None
        else min_overlap_ratio
    )
    seconds = (
        settings.DIARIZATION_MIN_OVERLAP_SECONDS
        if min_overlap_seconds is None
        else min_overlap_seconds
    )

    valid_turns = [
        turn for turn in turns if turn.end_seconds > turn.start_seconds
    ]
    mapping: dict[str, str] = {}

    for segment in segments:
        duration = segment.end_seconds - segment.start_seconds
        if duration <= _EPSILON:
            # Termasuk segmen text-only Sprint 4 yang timestampnya 0/0.
            continue

        overlap_by_ref: dict[str, float] = defaultdict(float)
        for turn in valid_turns:
            overlap = min(segment.end_seconds, turn.end_seconds) - max(
                segment.start_seconds, turn.start_seconds
            )
            if overlap <= _EPSILON:
                continue
            overlap_by_ref[turn.speaker_ref] += overlap

        if not overlap_by_ref:
            continue

        best = max(overlap_by_ref.values())
        winners = [
            ref for ref, value in overlap_by_ref.items() if abs(value - best) <= _EPSILON
        ]
        if len(winners) != 1:
            continue  # Ambiguous — jangan mengarang speaker.

        required = max(ratio * duration, seconds)
        if best + _EPSILON < required:
            continue

        winner = winners[0]
        if winner in labels:
            mapping[str(segment.id)] = winner

    return mapping


def _mark_failed(
    meeting_id: uuid.UUID,
    message: str,
    run_token: str | None = None,
) -> None:
    """Tandai FAILED hanya untuk eksekusi yang masih aktif (Sprint 9)."""
    db = SessionLocal()
    try:
        job = (
            db.query(DiarizationJob)
            .filter(
                DiarizationJob.meeting_id == str(meeting_id),
                DiarizationJob.status == DiarizationStatus.PROCESSING,
                DiarizationJob.run_token == run_token,
            )
            .first()
        )
        if job is None:
            return
        job.status = DiarizationStatus.FAILED
        job.error = message
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    finally:
        db.close()


def run_diarization(meeting_id: uuid.UUID) -> None:
    """Background task: panggil provider, petakan speaker, simpan hasil."""
    db = SessionLocal()
    run_log: JobRunLog | None = None
    try:
        meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
        if meeting is None:
            return

        job = _get_job(db, meeting_id)
        if job is None or job.status != DiarizationStatus.PROCESSING:
            return

        run_token = job.run_token
        run_log = JobRunLog(
            job_type="diarization",
            meeting_id=str(meeting_id),
            job_id=job.id,
            provider=job.provider,
            model=job.model,
        )
        run_log.started()

        asset = (
            db.query(AudioAsset)
            .filter(AudioAsset.meeting_id == str(meeting_id))
            .first()
        )
        if asset is None:
            _mark_failed(
                meeting_id,
                "Rekaman tidak ditemukan saat diarisasi dimulai.",
                run_token,
            )
            run_log.failed(RuntimeError("asset_missing"))
            return

        try:
            audio_path = resolve_storage_path(asset.storage_path)
        except ValueError:
            _mark_failed(
                meeting_id,
                "Path rekaman berada di luar direktori storage; periksa konfigurasi storage.",
                run_token,
            )
            run_log.failed(RuntimeError("invalid_storage_path"))
            return
        if not audio_path.is_file():
            _mark_failed(
                meeting_id,
                "File audio tidak ditemukan di storage saat diarisasi.",
                run_token,
            )
            run_log.failed(RuntimeError("audio_missing"))
            return

        segments = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.meeting_id == str(meeting_id))
            .order_by(TranscriptSegment.sequence.asc())
            .all()
        )
        if not segments:
            _mark_failed(
                meeting_id,
                "Transkrip tidak ditemukan saat diarisasi dimulai.",
                run_token,
            )
            run_log.failed(RuntimeError("segments_missing"))
            return

        try:
            provider = _create_provider(job.provider or settings.DIARIZATION_PROVIDER)
            result: DiarizationResult = retry_transient(
                lambda: provider.diarize(
                    audio_path=audio_path,
                    filename=asset.storage_filename,
                    mime_type=asset.mime_type,
                ),
                job_type="diarization",
                meeting_id=str(meeting_id),
            )
            turns = _validate_turns(result.turns)
            labels = assign_speaker_labels(turns)
            mapping = map_turns_to_segments(segments, turns, labels)
        except DiarizationError as exc:
            db.rollback()
            _mark_failed(meeting_id, str(exc), run_token)
            run_log.failed(exc)
            return
        except Exception as exc:
            db.rollback()
            _mark_failed(
                meeting_id,
                "Terjadi kegagalan tak terduga saat diarisasi.",
                run_token,
            )
            run_log.failed(exc)
            return

        if not job_guard.is_current(
            db,
            job,
            run_token=run_token,
            processing_status=DiarizationStatus.PROCESSING,
        ):
            db.rollback()
            run_log.finished("SUPERSEDED", event="job_skipped")
            return

        try:
            # Buang hasil lama tetapi pertahankan job yang sedang berjalan.
            _remove_speakers_and_assignments(db, meeting_id)

            speaker_by_ref: dict[str, Speaker] = {}
            for ref, label in labels.items():
                speaker = Speaker(
                    id=str(uuid.uuid4()),
                    meeting_id=str(meeting_id),
                    speaker_label=label,
                    display_name=None,
                )
                db.add(speaker)
                speaker_by_ref[ref] = speaker

            for segment in segments:
                ref = mapping.get(str(segment.id))
                segment.speaker_id = speaker_by_ref[ref].id if ref else None

            job.status = DiarizationStatus.COMPLETED
            job.error = None
            job.turns_count = len(turns)
            job.mapped_segments = len(mapping)
            db.commit()
            run_log.finished(DiarizationStatus.COMPLETED)
        except Exception as exc:
            db.rollback()
            _mark_failed(
                meeting_id,
                "Gagal menyimpan hasil diarisasi ke database.",
                run_token,
            )
            run_log.failed(exc)

    finally:
        db.close()


def recover_stuck_diarizations() -> int:
    """Tandai job PROCESSING yang tertinggal setelah restart sebagai FAILED."""
    db = SessionLocal()
    recovered = 0
    try:
        stuck = (
            db.query(DiarizationJob)
            .filter(DiarizationJob.status == DiarizationStatus.PROCESSING)
            .all()
        )
        for job in stuck:
            job.status = DiarizationStatus.FAILED
            job.error = (
                "Proses diarisasi terhenti karena aplikasi dimulai ulang. "
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
    log_recovery_event(job_type="diarization", recovered=recovered)
    return recovered
