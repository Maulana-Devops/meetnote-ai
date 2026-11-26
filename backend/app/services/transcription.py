"""Workflow transkripsi Sprint 4.

Alur:
1. ``prepare_transcription`` (request thread) memvalidasi semua yang bisa
   dicek cepat, lalu menandai meeting TRANSCRIBING dan job PROCESSING.
2. ``run_transcription`` dijalankan FastAPI BackgroundTasks dengan sessi DB
   sendiri, memanggil provider, lalu menyimpan segmen.
3. Kegagalan apa pun mengubah status menjadi FAILED — tidak pernah diam-diam
   dianggap sukses dengan transkrip kosong.
"""

import uuid

from fastapi import HTTPException, status as http_status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.job_logging import JobRunLog, log_recovery_event
from ..core.storage import resolve_storage_path
from ..database.session import SessionLocal
from ..models.audio_asset import AudioAsset
from ..models.meeting import Meeting, MeetingStatus
from ..models.transcript import TranscriptSegment, TranscriptionJob, TranscriptionStatus
from ..schemas.transcription import TranscriptionRead
from . import job_guard
from .diarization.workflow import clear_diarization
from .stt.base import SttResult, SttSegment, audio_source_ref
from .stt.errors import (
    SttError,
    SttInvalidResultError,
    SttUnsupportedFormatError,
)
from .stt.registry import create_provider

# Diuji/monkeypatch di test agar provider mock bisa disuntik deterministik.
_create_provider = create_provider


def _raise_http_from_stt(exc: SttError) -> None:
    """Terjemahkan error provider menjadi HTTP error yang konsisten."""
    raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting tidak ditemukan.")
    return meeting


def _get_segments(db: Session, meeting_id: uuid.UUID) -> list[TranscriptSegment]:
    return (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.meeting_id == str(meeting_id))
        .order_by(TranscriptSegment.sequence.asc())
        .all()
    )


def _to_read(db: Session, meeting: Meeting, job: TranscriptionJob | None) -> TranscriptionRead:
    # Query langsung (bukan relasi yang mungkin ter-cache) agar urutan dan
    # isi selalu sesuai data terbaru setelah commit.
    segments = _get_segments(db, uuid.UUID(meeting.id))
    return TranscriptionRead(
        meeting_id=uuid.UUID(meeting.id),
        status=job.status if job else TranscriptionStatus.NOT_STARTED,
        meeting_status=meeting.status,
        provider=job.provider if job else None,
        model=job.model if job else None,
        has_timestamps=job.has_timestamps if job else False,
        error=job.error if job else None,
        full_text="\n".join(segment.text for segment in segments),
        segments=segments,
        updated_at=job.updated_at if job else None,
    )


def get_transcription(db: Session, meeting_id: uuid.UUID) -> TranscriptionRead:
    """Ambil status + segmen. Kosong bila belum pernah ditranskripsi."""
    meeting = _get_meeting(db, meeting_id)
    job = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == str(meeting_id))
        .first()
    )
    return _to_read(db, meeting, job)


def clear_transcription(db: Session, meeting_id: uuid.UUID) -> int:
    """Hapus segmen + job saja. Audio dan AudioAsset tidak disentuh.

    Dipakai endpoint DELETE transcription dan saat rekaman dihapus (Sprint 3).
    Mengembalikan jumlah segmen yang dihapus.
    """
    meeting = _get_meeting(db, meeting_id)
    segments = _get_segments(db, meeting_id)
    for segment in segments:
        db.delete(segment)

    job = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == str(meeting_id))
        .first()
    )
    if job is not None:
        db.delete(job)

    # Speaker tidak bisa tetap melekat pada segmen yang akan dihapus. Retry
    # transkripsi juga otomatis membatalkan hasil diarisasi lama.
    clear_diarization(db, meeting_id)

    # Sprint 7: referensi ringkasan akan invalid bila transkripnya hilang.
    # Import lokal mencegah siklus modul dengan workflow summary.
    from .summary.workflow import clear_summary

    clear_summary(db, meeting_id)

    # Sprint 8: referensi action items juga invalid bila segmennya hilang.
    from .action_items.workflow import clear_action_items

    clear_action_items(db, meeting_id)

    # Jangan timpa status yang tidak berkaitan dengan transkripsi.
    if meeting.status in (
        MeetingStatus.TRANSCRIBING,
        MeetingStatus.TRANSCRIBED,
        MeetingStatus.FAILED,
    ):
        meeting.status = MeetingStatus.UPLOADED

    return len(segments)


def prepare_transcription(db: Session, meeting_id: uuid.UUID) -> TranscriptionRead:
    """Validasi awal + tandai proses akan dimulai."""
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
        # Jangan bocorkan path absolut/relative storage ke klien.
        raise HTTPException(
            status_code=500, detail="Path rekaman berada di luar direktori storage; periksa konfigurasi storage."
        ) from None
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="File rekaman tidak ditemukan di storage.")

    with job_guard.job_lock("transcription", meeting_id):
        job = (
            db.query(TranscriptionJob)
            .filter(TranscriptionJob.meeting_id == str(meeting_id))
            .first()
        )
        # Cegah dua proses aktif untuk meeting yang sama. Pemeriksaan ini
        # berada di dalam mutex; Sprint 9 menambahkan mutex untuk menutup
        # race check-then-act pada dua request yang bersamaan.
        if (job and job.status == TranscriptionStatus.PROCESSING) or (
            meeting.status == MeetingStatus.TRANSCRIBING
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Transkripsi untuk meeting ini sedang berjalan.",
            )

        try:
            provider = _create_provider()
            provider.validate_configuration()

            suffix = audio_path.suffix.lower()
            if suffix not in provider.supported_extensions():
                raise SttUnsupportedFormatError(
                    f"Format '{suffix or 'tanpa ekstensi'}' tidak didukung provider STT."
                )
        except SttError as exc:
            _raise_http_from_stt(exc)

        file_size = audio_path.stat().st_size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="File rekaman kosong — tidak bisa ditranskripsi.")
        if file_size > provider.max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Ukuran file {file_size} byte melebihi batas provider "
                    f"{provider.max_file_bytes} byte."
                ),
            )

        try:
            # Hapus transkrip lama sebelum proses baru (satu transkrip aktif).
            clear_transcription(db, meeting_id)
            # Paksa DELETE terlebih dahulu. Tanpa flush, SQLAlchemy menggabungkan
            # DELETE + INSERT dalam satu flush dan bisa menabrak unique constraint
            # transcription_jobs.meeting_id saat transkrip lama masih ada.
            db.flush()
            meeting.status = MeetingStatus.TRANSCRIBING
            job = TranscriptionJob(
                meeting_id=str(meeting_id),
                status=TranscriptionStatus.PROCESSING,
                provider=provider.name,
                model=provider.model,
                error=None,
                has_timestamps=False,
                run_token=job_guard.new_run_token(),
            )
            db.add(job)
            db.commit()
            db.refresh(meeting)
            db.refresh(job)
        except IntegrityError as exc:
            # Dua worker proses yang benar-benar terpisah bisa menabrak UNIQUE.
            # Ini konflik, bukan kegagalan internal — jangan bocorkan SQL.
            db.rollback()
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Transkripsi untuk meeting ini sedang berjalan.",
            ) from exc
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(
                status_code=500, detail="Gagal menyiapkan transkripsi."
            ) from None

    return _to_read(db, meeting, job)


def _validate_and_normalize(result: SttResult) -> tuple[list[SttSegment], bool]:
    """Validasi hasil provider; tidak pernah mengarang teks."""
    if not result.has_content:
        raise SttInvalidResultError(
            "Provider STT mengembalikan transkrip kosong — tidak ada teks yang disimpan."
        )

    valid: list[SttSegment] = []
    for segment in result.segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.start_seconds < 0 or segment.end_seconds < 0:
            raise SttInvalidResultError("Provider mengembalikan timestamp negatif.")
        if segment.end_seconds < segment.start_seconds:
            raise SttInvalidResultError(
                "Provider mengembalikan waktu akhir sebelum waktu mulai."
            )
        valid.append(
            SttSegment(
                text=text,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                language=segment.language,
                source_ref=segment.source_ref
                or audio_source_ref(segment.start_seconds, segment.end_seconds),
            )
        )

    # Urutan deterministik: awal, lalu akhir, lalu urutan asli (stable sort).
    valid.sort(key=lambda item: (item.start_seconds, item.end_seconds))

    if not valid:
        # Provider hanya memberi teks utuh. Simpan satu segmen tanpa timestamp
        # asli; UI akan menampilkan "tanpa timestamp", bukan angka palsu.
        text = result.text.strip()
        if not text:
            raise SttInvalidResultError("Provider STT tidak mengembalikan teks.")
        valid = [SttSegment(text=text, start_seconds=0.0, end_seconds=0.0)]

    return valid, bool(result.segments) and result.has_timestamps


def _mark_failed(
    meeting_id: uuid.UUID,
    message: str,
    run_token: str | None = None,
) -> None:
    """Tandai FAILED dengan sesi baru, hanya untuk eksekusi yang masih aktif.

    Sprint 9: tanpa pencocokan ``run_token``, task lama dapat menandai FAILED
    job yang lebih baru (dan pada transkripsi juga menimpa status meeting).
    """
    db = SessionLocal()
    try:
        job = (
            db.query(TranscriptionJob)
            .filter(
                TranscriptionJob.meeting_id == str(meeting_id),
                TranscriptionJob.status == TranscriptionStatus.PROCESSING,
                TranscriptionJob.run_token == run_token,
            )
            .first()
        )
        if job is None:
            return
        job.status = TranscriptionStatus.FAILED
        job.error = message
        meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
        if meeting is not None and meeting.status == MeetingStatus.TRANSCRIBING:
            meeting.status = MeetingStatus.FAILED
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    finally:
        db.close()


def run_transcription(meeting_id: uuid.UUID) -> None:
    """Task background: panggil provider lalu simpan segmen.

    Fungsi ini sengaja membuka sesi database sendiri karena sesi request sudah
    ditutup sebelum background task dijalankan server.
    """
    db = SessionLocal()
    run_log: JobRunLog | None = None
    try:
        meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
        if meeting is None:
            return

        job = (
            db.query(TranscriptionJob)
            .filter(TranscriptionJob.meeting_id == str(meeting_id))
            .first()
        )
        if job is None or job.status != TranscriptionStatus.PROCESSING:
            return

        run_token = job.run_token
        run_log = JobRunLog(
            job_type="transcription",
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
                "Rekaman tidak ditemukan saat transkripsi dimulai.",
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
                "File audio tidak ditemukan di storage saat transkripsi.",
                run_token,
            )
            run_log.failed(RuntimeError("audio_missing"))
            return

        try:
            provider = _create_provider(job.provider or settings.STT_PROVIDER)
            result = provider.transcribe(
                audio_path=audio_path,
                filename=asset.storage_filename,
                mime_type=asset.mime_type,
            )
            segments, has_timestamps = _validate_and_normalize(result)
        except SttError as exc:
            db.rollback()
            _mark_failed(meeting_id, str(exc), run_token)
            run_log.failed(exc)
            return
        except Exception as exc:
            # Jangan rekam detail tak terduga yang mungkin memuat data sensitif.
            db.rollback()
            _mark_failed(meeting_id, "Terjadi kegagalan tak terduga saat transkripsi.", run_token)
            run_log.failed(exc)
            return

        # Sprint 9: pastikan job ini masih yang aktif sebelum menulis hasil.
        # Task lama yang tertinggal tidak boleh menimpa retry yang lebih baru.
        if not job_guard.is_current(
            db,
            job,
            run_token=run_token,
            processing_status=TranscriptionStatus.PROCESSING,
        ):
            db.rollback()
            run_log.finished("SUPERSEDED", event="job_skipped")
            return

        try:
            db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == str(meeting_id)
            ).delete(synchronize_session=False)

            for sequence, segment in enumerate(segments, start=1):
                db.add(
                    TranscriptSegment(
                        meeting_id=str(meeting_id),
                        text=segment.text,
                        start_seconds=segment.start_seconds,
                        end_seconds=segment.end_seconds,
                        sequence=sequence,
                    )
                )

            job.status = TranscriptionStatus.COMPLETED
            job.error = None
            job.has_timestamps = has_timestamps
            if meeting.status == MeetingStatus.TRANSCRIBING:
                meeting.status = MeetingStatus.TRANSCRIBED
            db.commit()
            run_log.finished(TranscriptionStatus.COMPLETED)
        except Exception as exc:
            db.rollback()
            _mark_failed(
                meeting_id,
                "Gagal menyimpan hasil transkripsi ke database.",
                run_token,
            )
            run_log.failed(exc)

    finally:
        db.close()


def recover_stuck_transcriptions() -> int:
    """Panggil saat startup: process yang terputus saat restart ditandai FAILED.

    Background task in-process tidak bertahan saat aplikasi mati. Tanpa ini,
    meeting bisa tetap TRANSCRIBING selamanya.
    """
    db = SessionLocal()
    recovered = 0
    changed = False
    message = (
        "Proses transkripsi terhenti karena aplikasi dimulai ulang. "
        "Silakan coba lagi."
    )
    try:
        stuck = (
            db.query(TranscriptionJob)
            .filter(TranscriptionJob.status == TranscriptionStatus.PROCESSING)
            .all()
        )
        for job in stuck:
            job.status = TranscriptionStatus.FAILED
            job.error = message
            # Token dihapus supaya task lama yang masih hidup tidak bisa
            # menulis hasil atau FAILED setelah recovery.
            job.run_token = None
            meeting = db.query(Meeting).filter(Meeting.id == job.meeting_id).first()
            if meeting is not None and meeting.status == MeetingStatus.TRANSCRIBING:
                meeting.status = MeetingStatus.FAILED
            recovered += 1

        # Sprint 9: selaraskan meeting yang TRANSCRIBING tanpa job PROCESSING.
        # Job COMPLETED tidak pernah diubah menjadi FAILED dan hasilnya aman.
        stranded = (
            db.query(Meeting)
            .filter(Meeting.status == MeetingStatus.TRANSCRIBING)
            .all()
        )
        for meeting in stranded:
            job = (
                db.query(TranscriptionJob)
                .filter(TranscriptionJob.meeting_id == meeting.id)
                .first()
            )
            if job is not None and job.status == TranscriptionStatus.COMPLETED:
                meeting.status = MeetingStatus.TRANSCRIBED
                changed = True
            elif job is None or job.status != TranscriptionStatus.PROCESSING:
                meeting.status = MeetingStatus.FAILED
                changed = True

        if recovered or changed:
            db.commit()
    except SQLAlchemyError:
        db.rollback()
        return 0
    finally:
        db.close()
    log_recovery_event(job_type="transcription", recovered=recovered)
    return recovered
