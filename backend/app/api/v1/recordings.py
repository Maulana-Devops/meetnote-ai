"""Endpoint rekaman (MediaRecorder dan upload file lokal).

Alur:
1. Frontend membuat meeting lewat ``POST /meetings``.
2a. Browser merekam audio → Blob, atau pengguna memilih file audio lokal.
2b. Keduanya dikirim lewat multipart ke ``POST /meetings/{id}/recording``.
3. Backend menyimpan file ke ``STORAGE_DIR/meetings/{meeting_id}/`` dan
   metadata ke tabel ``audio_assets``.
4. ``DELETE /meetings/{id}/recording`` menghapus keduanya dan mengembalikan
   status meeting ke PENDING.

Endpoint yang sama dipakai ulang untuk Sprint 3 — tidak ada endpoint upload
duplikat. File dari pengguna tidak pernah dipakai sebagai nama file di storage.
"""

import math
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.audio import (
    detect_content_mime,
    extension_for_content_type,
    is_allowed_extension,
    normalize_content_type,
    signature_conflicts,
)
from ...core.config import settings
from ...core.storage import (
    make_safe_filename,
    meeting_directory,
    relative_storage_path,
    resolve_storage_path,
)
from ...models.audio_asset import AudioAsset
from ...models.diarization import DiarizationJob, DiarizationStatus
from ...models.meeting import Meeting, MeetingStatus
from ...models.transcript import TranscriptionJob, TranscriptionStatus
from ...schemas.audio import AudioAssetRead
from ...services import job_guard
from ...services.transcription import clear_transcription
from .meetings import get_db

router = APIRouter(prefix="/meetings", tags=["Recordings"])


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    """Ambil meeting atau lempar 404."""
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting tidak ditemukan.")
    return meeting


def _get_asset(db: Session, meeting_id: uuid.UUID) -> AudioAsset:
    """Ambil metadata rekaman atau lempar 404."""
    _get_meeting(db, meeting_id)
    asset = db.query(AudioAsset).filter(AudioAsset.meeting_id == str(meeting_id)).first()
    if asset is None:
        raise HTTPException(
            status_code=404,
            detail="Rekaman belum tersedia untuk meeting ini.",
        )
    return asset


@router.post(
    "/{meeting_id}/recording",
    response_model=AudioAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_recording(
    meeting_id: uuid.UUID,
    file: UploadFile = File(..., description="Audio hasil MediaRecorder"),
    duration_seconds: float = Form(
        0.0,
        ge=0,
        le=settings.MAX_AUDIO_DURATION_SECONDS,
        allow_inf_nan=False,
        description="Durasi rekaman (detik)",
    ),
    db: Session = Depends(get_db),
) -> AudioAsset:
    """Simpan rekaman baru untuk meeting yang sudah dibuat."""
    meeting = _get_meeting(db, meeting_id)

    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration > settings.MAX_AUDIO_DURATION_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Durasi rekaman tidak valid.",
        )

    # Satu meeting = satu rekaman. Kunci mencakup pengecekan hingga commit
    # agar dua request bersamaan tidak menulis dua file pada DB legacy yang
    # belum memiliki unique index.
    with job_guard.job_lock("recording", meeting_id):
        existing = (
            db.query(AudioAsset).filter(AudioAsset.meeting_id == str(meeting_id)).first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting ini sudah memiliki rekaman. Hapus rekaman lama terlebih dahulu.",
            )

        # Validasi MIME type dan ekstensi. Nama file pengguna hanya dibaca,
        # tidak dipakai untuk membuat path.
        mime_base = normalize_content_type(file.content_type)
        extension = extension_for_content_type(mime_base)
        if extension is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Tipe file '{mime_base or 'tidak diketahui'}' tidak didukung. "
                    "Gunakan audio/webm, audio/ogg, audio/wav, audio/mpeg, atau audio/mp4."
                ),
            )

        original_filename = os.path.basename(file.filename or "recording")
        if not is_allowed_extension(original_filename):
            raise HTTPException(
                status_code=400,
                detail="Ekstensi file tidak dikenali. Gunakan .webm, .ogg, .wav, .mp3, atau .m4a.",
            )

        # Batasi ukuran dengan membaca maksimal batas + 1 byte.
        max_bytes = settings.MAX_AUDIO_FILE_BYTES
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Ukuran rekaman melebihi batas {max_bytes} byte "
                    f"({max_bytes / (1024 * 1024):.1f} MB)."
                ),
            )

        # Signature sederhana: hanya menolak jika pola dikenali dan tidak cocok.
        # Signature yang tidak dikenali tetap diterima (lihat docs/SPRINT3.md).
        if signature_conflicts(content, mime_base):
            detected = detect_content_mime(content)
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Isi file terdeteksi sebagai {detected}, tetapi MIME dinyatakan "
                    f"{mime_base or 'tidak diketahui'}."
                ),
            )

        filename = make_safe_filename(extension)
        directory = meeting_directory(meeting_id)
        final_path = directory / filename
        temp_path = directory / f"{filename}.part"

        try:
            directory.mkdir(parents=True, exist_ok=True)
            with temp_path.open("wb") as output:
                output.write(content)
            # Atomic rename: file hanya tampak lengkap setelah ditulis semua.
            os.replace(temp_path, final_path)
        except OSError:  # pragma: no cover - kegagalan disk
            temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500,
                detail="Gagal menyimpan file audio.",
            ) from None

        asset = AudioAsset(
            meeting_id=str(meeting_id),
            original_filename=original_filename,
            storage_filename=filename,
            storage_path=relative_storage_path(meeting_id, filename),
            mime_type=mime_base,
            file_size_bytes=len(content),
            duration_seconds=duration,
        )

        db.add(asset)
        meeting.status = MeetingStatus.UPLOADED

        try:
            db.commit()
            db.refresh(asset)
        except IntegrityError as exc:  # pragma: no cover - dua upload bersamaan
            db.rollback()
            final_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting ini sudah memiliki rekaman. Hapus rekaman lama terlebih dahulu.",
            ) from exc
        except SQLAlchemyError:  # pragma: no cover - jalur error DB
            db.rollback()
            # Jangan biarkan file yatim jika metadata gagal disimpan.
            final_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500,
                detail="Gagal menyimpan metadata rekaman.",
            ) from None

        return asset


@router.get("/{meeting_id}/recording", response_model=AudioAssetRead)
def get_recording(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> AudioAsset:
    """Ambil metadata rekaman milik meeting tertentu."""
    return _get_asset(db, meeting_id)


@router.get("/{meeting_id}/recording/play")
def play_recording(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Putar file audio tanpa mengekspos direktori storage."""
    asset = _get_asset(db, meeting_id)

    try:
        path = resolve_storage_path(asset.storage_path)
    except ValueError:
        raise HTTPException(
            status_code=500, detail="Path rekaman berada di luar direktori storage; periksa konfigurasi storage."
        ) from None

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File rekaman tidak ditemukan di storage.",
        )

    return FileResponse(
        path,
        media_type=asset.mime_type,
        headers={"Content-Disposition": "inline"},
    )


@router.delete("/{meeting_id}/recording")
def delete_recording(
    meeting_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Hapus metadata + file rekaman, lalu kembalikan status ke PENDING.

    File dipindahkan ke nama sementara ``.delete`` sebelum commit. Jika commit
    gagal, file dikembalikan sehingga metadata tidak pernah kehilangan file.
    """
    meeting = _get_meeting(db, meeting_id)
    asset = db.query(AudioAsset).filter(AudioAsset.meeting_id == str(meeting_id)).first()

    if asset is None:
        raise HTTPException(
            status_code=404,
            detail="Rekaman belum tersedia untuk meeting ini.",
        )

    # Jangan hapus audio yang sedang dipakai job transkripsi background.
    active_job = (
        db.query(TranscriptionJob)
        .filter(TranscriptionJob.meeting_id == str(meeting_id))
        .first()
    )
    if active_job is not None and active_job.status == TranscriptionStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transkripsi sedang berjalan. Tunggu hingga selesai sebelum menghapus rekaman.",
        )

    active_diarization = (
        db.query(DiarizationJob)
        .filter(DiarizationJob.meeting_id == str(meeting_id))
        .first()
    )
    if (
        active_diarization is not None
        and active_diarization.status == DiarizationStatus.PROCESSING
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diarisasi sedang berjalan. Tunggu hingga selesai sebelum menghapus rekaman.",
        )

    # Rekaman juga menghapus transkrip + turunannya; blokir bila ada job aktif.
    job_guard.ensure_no_active_jobs(db, meeting_id)

    try:
        path = resolve_storage_path(asset.storage_path)
    except ValueError:
        raise HTTPException(
            status_code=500, detail="Path rekaman berada di luar direktori storage; periksa konfigurasi storage."
        ) from None

    trash_path = path.with_name(f"{path.name}.delete")

    # File bisa saja sudah hilang; itu tidak menghalangi penghapusan metadata.
    if path.exists():
        try:
            path.replace(trash_path)
        except OSError:  # pragma: no cover - kegagalan disk
            raise HTTPException(
                status_code=500,
                detail="Gagal menyiapkan penghapusan file.",
            ) from None

    try:
        # Transkrip mengikuti rekaman: buang segmen + job jika audio dihapus.
        # Fungsi ini tidak menyentuh file audio maupun baris AudioAsset.
        clear_transcription(db, meeting_id)
        meeting.status = MeetingStatus.PENDING
        db.delete(asset)
        db.commit()
    except Exception:  # pragma: no cover - jalur error DB / tak terduga
        db.rollback()
        # Kembalikan file agar metadata (yang masih ada) tetap menunjuk ke file.
        # Sprint 9: penanganan diperluas dari SQLAlchemyError ke Exception agar
        # kegagalan clear_transcription tidak meninggalkan metadata tanpa file.
        if trash_path.exists():
            try:
                trash_path.replace(path)
            except OSError:
                pass
        raise HTTPException(
            status_code=500,
            detail="Gagal menghapus metadata rekaman.",
        ) from None

    # Setelah commit sukses, sisa file sementara boleh dibersihkan.
    # Jika gagal, file yatim tidak lagi memiliki metadata — bukan inkonsistensi DB.
    try:
        trash_path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass

    return {
        "detail": "Rekaman berhasil dihapus.",
        "meeting_id": str(meeting_id),
    }