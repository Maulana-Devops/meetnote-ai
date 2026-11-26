"""Sprint 9: perlindungan konkurensi dan identitas eksekusi job.

Dua lapisan pertahanan dipakai:

1. ``job_lock`` — mutex per (jenis job, meeting) di dalam satu proses. FastAPI
   ``BackgroundTasks`` berjalan di proses yang sama dengan endpoint, sehingga
   ini menutup race yang paling realistis: dua permintaan yang bersamaan
   mengklaim job yang sama.
2. ``run_token`` — UUID unik yang ditulis saat job diklaim. Task background
   menyimpan token di awal dan memeriksanya lagi sebelum menyimpan hasil atau
   menandai FAILED. Task lama tidak bisa menimpa job yang lebih baru.

Catatan batas: SQLite tidak menyediakan ``SELECT ... FOR UPDATE``. Antara dua
proses worker yang benar-benar terpisah, constraint UNIQUE pada kolom
``meeting_id`` tetap menjadi pagar terakhir (satu permintaan akan mendapat
409/500 yang aman). Tidak ada klaim "antrean distributed" di sini.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

_locks: dict[tuple[str, str], threading.Lock] = {}
_registry_lock = threading.Lock()


@contextmanager
def job_lock(job_type: str, meeting_id: object) -> Iterator[None]:
    """Kunci akses ke satu (job_type, meeting) dalam proses ini."""
    key = (job_type, str(meeting_id))
    with _registry_lock:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        yield


def new_run_token() -> str:
    """Token baru untuk satu percobaan eksekusi job."""
    return str(uuid.uuid4())


def try_claim_existing(
    db: Session,
    *,
    model: type,
    meeting_id: object,
    processing_status: str,
    run_token: str,
    provider: str,
    model_name: str | None,
) -> bool:
    """Klaim job yang sudah ada secara atomik.

    Mengembalikan ``True`` hanya bila UPDATE benar-benar mengubah satu baris
    yang sebelumnya bukan PROCESSING. Pemanggilan harus berada di dalam
    ``job_lock`` dan transaksi yang sama dengan commit pemanggil.
    """
    updated = (
        db.query(model)
        .filter(
            model.meeting_id == str(meeting_id),
            model.status != processing_status,
        )
        .update(
            {
                model.status: processing_status,
                model.run_token: run_token,
                model.provider: provider,
                model.model: model_name,
                model.error: None,
            },
            synchronize_session=False,
        )
    )
    return updated == 1


def is_current(
    db: Session,
    job: object,
    *,
    run_token: str | None,
    processing_status: str,
) -> bool:
    """Pastikan job masih milik eksekusi yang sama dan belum diselesaikan."""
    if job is None:
        return False
    model = type(job)
    return (
        db.query(model)
        .filter(
            model.id == job.id,
            model.status == processing_status,
            model.run_token == run_token,
        )
        .first()
        is not None
    )


def active_job_types(db: Session, meeting_id: object) -> list[str]:
    """Daftar jenis job yang sedang PROCESSING untuk satu meeting.

    Dipakai pengawal delete untuk mencegah penghapusan data saat proses
    dependen masih berjalan (partial data on cancellation).
    """
    from ..models.action_item import ActionItemJob, ActionExtractionStatus
    from ..models.diarization import DiarizationJob, DiarizationStatus
    from ..models.summary import SummaryJob, SummaryStatus
    from ..models.transcript import TranscriptionJob, TranscriptionStatus

    meeting = str(meeting_id)
    active: list[str] = []
    checks = (
        ("transkripsi", TranscriptionJob, TranscriptionStatus.PROCESSING),
        ("diarisasi", DiarizationJob, DiarizationStatus.PROCESSING),
        ("ringkasan", SummaryJob, SummaryStatus.PROCESSING),
        ("action items", ActionItemJob, ActionExtractionStatus.PROCESSING),
    )
    for label, model, status_value in checks:
        exists = (
            db.query(model)
            .filter(model.meeting_id == meeting, model.status == status_value)
            .first()
        )
        if exists is not None:
            active.append(label)
    return active


def ensure_no_active_jobs(
    db: Session,
    meeting_id: object,
    *,
    exclude: str = "",
) -> None:
    """Batalkan operasi bila ada job aktif lain. Melempar 409 bila ada."""
    from fastapi import HTTPException, status as http_status

    active = [label for label in active_job_types(db, meeting_id) if label != exclude]
    if active:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                "Proses berikut masih berjalan untuk meeting ini: "
                + ", ".join(active)
                + ". Tunggu selesai sebelum melanjutkan."
            ),
        )
