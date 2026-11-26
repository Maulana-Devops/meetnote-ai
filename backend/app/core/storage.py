"""Helper path penyimpanan audio.

Semua file audio berada di bawah ``settings.STORAGE_DIR``. Fungsi di sini
memastikan path yang dipakai selalu berada di dalam direktori tersebut,
sehingga nama file dari pengguna tidak bisa dipakai untuk path traversal.
"""

import uuid
from pathlib import Path

from .config import settings


def storage_root() -> Path:
    """Direktori storage yang sudah di-resolve ke path absolut."""
    return Path(settings.STORAGE_DIR).resolve()


def meeting_directory(meeting_id: uuid.UUID) -> Path:
    """Folder penyimpanan untuk satu meeting."""
    return storage_root() / "meetings" / str(meeting_id)


def relative_storage_path(meeting_id: uuid.UUID, filename: str) -> str:
    """Path relatif yang disimpan di database (bukan path absolut)."""
    return f"meetings/{meeting_id}/{filename}"


def resolve_storage_path(relative_path: str) -> Path:
    """Ubah path relatif menjadi absolut, tolak jika keluar dari storage."""
    root = storage_root()
    candidate = (root / relative_path).resolve()

    if not candidate.is_relative_to(root):
        raise ValueError("Path berada di luar direktori storage.")

    return candidate


def make_safe_filename(extension: str) -> str:
    """Buat nama file baru yang tidak bergantung pada input pengguna."""
    return f"recording-{uuid.uuid4().hex}{extension}"


def audit_storage(db) -> dict:
    """Audit konsistensi storage SECARA READ-ONLY (Sprint 9).

    Tidak ada file yang dihapus, dipindah, atau diubah. Semua path yang
    dikembalikan bersifat relatif terhadap ``STORAGE_DIR`` agar direktori
    absolut tidak bocor ke API/log. File sementara (``.part``) dan trash
    (``.delete``) sengaja dipisah dari "orphan" karena keduanya dapat muncul
    saat proses crash dan keputusan penghapusan diserahkan ke pengguna.
    """
    from sqlalchemy.orm import Session

    from ..models.audio_asset import AudioAsset
    from .job_logging import log_storage_event

    if not isinstance(db, Session):  # pragma: no cover - pemangilan internal
        raise TypeError("audit_storage membutuhkan Session SQLAlchemy.")

    root = storage_root()
    referenced: set[str] = set()
    invalid_metadata_paths = 0
    for (relative_path,) in db.query(AudioAsset.storage_path).all():
        try:
            resolved = resolve_storage_path(relative_path)
        except ValueError:
            # Jangan kembalikan path mentah dari DB (bisa memuat info sensitif).
            invalid_metadata_paths += 1
            continue
        if resolved.is_relative_to(root):
            referenced.add(resolved.relative_to(root).as_posix())

    actual: set[str] = set()
    if root.is_dir():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                actual.add(resolved.relative_to(root).as_posix())
            except OSError:  # pragma: no cover - file menghilang saat scan
                continue

    temp_files = sorted(p for p in actual if p.endswith(".part"))
    trash_files = sorted(p for p in actual if p.endswith(".delete"))
    content_files = actual - set(temp_files) - set(trash_files)
    orphans = sorted(content_files - referenced)
    missing_files = sorted(referenced - actual)

    for reason, paths in (
        ("orphan_file", orphans),
        ("temp_file", temp_files),
        ("trash_file", trash_files),
        ("metadata_without_file", missing_files),
    ):
        for relative in paths:
            log_storage_event(event="storage_anomaly", path=relative, reason=reason)

    return {
        "storage_root_configured": True,
        "files_total": len(actual),
        "metadata_total": db.query(AudioAsset.id).count(),
        "orphan_files": orphans,
        "temp_files": temp_files,
        "trash_files": trash_files,
        "metadata_without_file": missing_files,
        "invalid_metadata_paths": invalid_metadata_paths,
        "note": "Audit read-only; tidak ada file yang dihapus otomatis.",
    }