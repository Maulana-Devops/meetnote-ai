"""Retry/backoff untuk kegagalan provider yang bersifat sementara.

Helper ini dipakai oleh job background (bukan oleh handler request) karena ia
bisa menunggu antar percobaan. Hanya error yang jelas-jelas sementara yang
diulang: rate limit (429), timeout, dan gangguan server provider (5xx/respons
tak terduga). Error konfigurasi, autentikasi, format tidak didukung, dan
validasi hasil TIDAK diulang.

Tidak ada pesan error, header, atau isi response yang dibuat di sini. Event
log hanya memuat kategori error (nama kelas), sehingga tidak ada secret yang
masuk ke log maupun ke ``job.error``.
"""

from __future__ import annotations

from collections.abc import Callable
from random import uniform
from time import sleep
from typing import TypeVar

from ..core.config import settings
from ..core.job_logging import error_category, log_job_event
from .diarization.errors import (
    DiarizationProviderError,
    DiarizationRateLimitError,
    DiarizationTimeoutError,
)
from .llm.errors import LlmProviderError, LlmRateLimitError, LlmTimeoutError
from .stt.errors import SttProviderError, SttRateLimitError, SttTimeoutError

T = TypeVar("T")

_TRANSIENT_ERRORS = (
    SttRateLimitError,
    SttTimeoutError,
    SttProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
    LlmProviderError,
    DiarizationRateLimitError,
    DiarizationTimeoutError,
    DiarizationProviderError,
)

# Jitter mencegah banyak job yang gagal bersamaan bangun di detik yang sama.
_JITTER_MIN = 0.5
_JITTER_MAX = 1.0


def retry_transient(
    call: Callable[[], T],
    *,
    job_type: str,
    meeting_id: str,
) -> T:
    """Panggil ``call`` hingga berhasil atau attempts habis.

    Pengecualian non-sementara diteruskan apa adanya pada percobaan pertama.
    Bila semua percobaan gagal, exception terakhir diteruskan sehingga pesan
    error di workflow tetap konsisten dengan perilaku sebelumnya.
    """
    attempts = max(1, settings.PROVIDER_RETRY_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except _TRANSIENT_ERRORS as exc:
            if attempt >= attempts:
                raise
            backoff = min(
                settings.PROVIDER_RETRY_MAX_SECONDS,
                settings.PROVIDER_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
            )
            delay = backoff * uniform(_JITTER_MIN, _JITTER_MAX)
            log_job_event(
                job_type=job_type,
                meeting_id=meeting_id,
                event="provider_retry",
                status="retry",
                error_category=error_category(exc),
            )
            sleep(delay)
    raise AssertionError("retry_transient: tidak ada percobaan yang dijalankan")
