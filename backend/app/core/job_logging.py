"""Logging ringan dan aman untuk observability pipeline (Sprint 9).

Semua informasi sensitif sengaja TIDAK punya tempat di sini: tidak ada field
untuk API key, Authorization header, isi audio, transkrip, atau response mentah
provider. Penelepon hanya boleh mengirim identifier, status, kategori error, dan
durasi.

Format satu baris JSON (JSON Lines) memudahkan pencarian tanpa dependency baru:

    job_event {"event":"job_finished","job_type":"transcription",...}
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("meetnote")
# Pastikan event INFO tidak dibuang bila aplikasi belum mengonfigurasi root
# logger (mis. saat dijalankan sebagai script atau di test).
logger.setLevel(logging.INFO)


def _clean(value: Any) -> str | int | float | bool | None:
    """Terima hanya tipe primitif; jangan pernah mem-log objek mentah."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(type(value).__name__)


def _emit(prefix: str, event: str, fields: dict[str, Any]) -> None:
    payload: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        cleaned = _clean(value)
        if cleaned is not None:
            payload[key] = cleaned
    logger.info("%s %s", prefix, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def log_job_event(
    *,
    job_type: str,
    meeting_id: str,
    event: str,
    job_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: str | None = None,
    error_category: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Catat satu event job. Tidak pernah menerima pesan error bebas."""
    _emit(
        "job_event",
        event,
        {
            "job_type": job_type,
            "meeting_id": meeting_id,
            "job_id": job_id,
            "provider": provider,
            "model": model,
            "status": status,
            "error_category": error_category,
            "duration_ms": duration_ms,
        },
    )


def log_storage_event(
    *,
    event: str,
    path: str | None = None,
    reason: str | None = None,
    count: int | None = None,
) -> None:
    """Catat event storage. `path` WAJIB relatif terhadap STORAGE_DIR."""
    _emit("storage_event", event, {"path": path, "reason": reason, "count": count})


def log_recovery_event(
    *,
    job_type: str,
    recovered: int,
    event: str = "recovery_finished",
) -> None:
    """Catat hasil recovery startup (idempoten)."""
    _emit(
        "recovery_event",
        event,
        {"job_type": job_type, "recovered": recovered},
    )


def error_category(exc: BaseException) -> str:
    """Kategori error = nama kelas. Tidak mengandung pesan/secret."""
    return type(exc).__name__


class JobRunLog:
    """Pembantu start/finish + durasi untuk satu eksekusi job background."""

    def __init__(
        self,
        *,
        job_type: str,
        meeting_id: str,
        job_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.job_type = job_type
        self.meeting_id = meeting_id
        self.job_id = job_id
        self.provider = provider
        self.model = model
        self._started = time.perf_counter()

    def _base(self) -> dict[str, Any]:
        return {
            "job_type": self.job_type,
            "meeting_id": self.meeting_id,
            "job_id": self.job_id,
            "provider": self.provider,
            "model": self.model,
        }

    def started(self, event: str = "job_started") -> None:
        log_job_event(event=event, **self._base())

    def finished(self, status: str, event: str = "job_finished") -> None:
        duration_ms = int((time.perf_counter() - self._started) * 1000)
        log_job_event(event=event, status=status, duration_ms=duration_ms, **self._base())

    def failed(self, exc: BaseException, event: str = "job_failed") -> None:
        duration_ms = int((time.perf_counter() - self._started) * 1000)
        log_job_event(
            event=event,
            status="FAILED",
            error_category=error_category(exc),
            duration_ms=duration_ms,
            **self._base(),
        )
