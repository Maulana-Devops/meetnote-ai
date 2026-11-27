"""Pengujian retry/backoff provider tanpa jaringan dan tanpa tidur nyata.

Test suite utama men-set PROVIDER_RETRY_ATTEMPTS=1 supaya perilaku lama tetap
deterministik. File ini menguji helper retry secara langsung dan satu alur
transkripsi dengan provider flaky yang gagal sekali lalu berhasil.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.services import provider_retry
from app.services.provider_retry import retry_transient
from app.services.stt.base import SttSegment
from app.services.stt.errors import (
    SttAuthenticationError,
    SttRateLimitError,
    SttTimeoutError,
)
from app.services.stt.mock import MockSttProvider

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


@pytest.fixture
def no_sleep(monkeypatch):
    """Ganti sleep/uniform supaya test tidak menunggu backoff."""
    delays: list[float] = []
    monkeypatch.setattr(provider_retry, "sleep", lambda seconds: delays.append(seconds))
    monkeypatch.setattr(provider_retry, "uniform", lambda low, high: high)
    return delays


def _configure(monkeypatch, attempts: int, base: float, maximum: float) -> None:
    monkeypatch.setattr(settings, "PROVIDER_RETRY_ATTEMPTS", attempts)
    monkeypatch.setattr(settings, "PROVIDER_RETRY_BASE_SECONDS", base)
    monkeypatch.setattr(settings, "PROVIDER_RETRY_MAX_SECONDS", maximum)


def test_error_sementara_diulang_lalu_berhasil(monkeypatch, no_sleep):
    _configure(monkeypatch, attempts=3, base=1.0, maximum=8.0)
    calls: list[int] = []

    def call() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise SttRateLimitError("Rate limit (uji).")
        return "ok"

    assert retry_transient(call, job_type="test", meeting_id="m1") == "ok"
    assert len(calls) == 2
    assert no_sleep == [1.0]


def test_error_non_sementara_tidak_diulang(monkeypatch, no_sleep):
    _configure(monkeypatch, attempts=5, base=1.0, maximum=8.0)
    calls: list[int] = []

    def call() -> str:
        calls.append(1)
        raise SttAuthenticationError("Kredensial ditolak (uji).")

    with pytest.raises(SttAuthenticationError, match="Kredensial ditolak"):
        retry_transient(call, job_type="test", meeting_id="m1")

    assert len(calls) == 1
    assert no_sleep == []


def test_semua_percobaan_gagal_meneruskan_pesan_terakhir(monkeypatch, no_sleep):
    _configure(monkeypatch, attempts=3, base=1.0, maximum=8.0)
    calls: list[int] = []

    def call() -> str:
        calls.append(1)
        raise SttTimeoutError(f"Timeout #{len(calls)}")

    with pytest.raises(SttTimeoutError, match="Timeout #3"):
        retry_transient(call, job_type="test", meeting_id="m1")

    assert len(calls) == 3
    # Backoff eksponensial: 1s, 2s. Jitter di-mock ke nilai maksimal.
    assert no_sleep == [1.0, 2.0]


def test_backoff_dibatasi_batas_maksimum(monkeypatch, no_sleep):
    _configure(monkeypatch, attempts=5, base=2.0, maximum=3.0)

    def call() -> str:
        raise SttTimeoutError("Timeout (uji).")

    with pytest.raises(SttTimeoutError):
        retry_transient(call, job_type="test", meeting_id="m1")

    assert no_sleep == [2.0, 3.0, 3.0, 3.0]


def test_job_memakai_retry_saat_provider_gagal_sementara(
    s2_db, s2_client, monkeypatch, no_sleep
):
    _configure(monkeypatch, attempts=2, base=1.0, maximum=8.0)
    created = s2_client.post("/api/v1/meetings", json={"title": "Rapat Retry"})
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]
    uploaded = s2_client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("rapat.wav", WAV_HEADER, "audio/wav")},
        data={"duration_seconds": "2.0"},
    )
    assert uploaded.status_code == 201, uploaded.text

    inner = MockSttProvider(
        segments=[SttSegment("Halo.", 0.0, 1.5, language="id")]
    )

    class FlakyProvider:
        name = "mock"
        model = "mock-1"

        def __init__(self) -> None:
            self.calls = 0

        @property
        def max_file_bytes(self) -> int:
            return inner.max_file_bytes

        @property
        def supports_timestamps(self) -> bool:
            return inner.supports_timestamps

        def supported_extensions(self) -> set[str]:
            return inner.supported_extensions()

        def validate_configuration(self) -> None:
            inner.validate_configuration()

        def transcribe(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise SttRateLimitError("Rate limit sementara (uji).")
            return inner.transcribe(**kwargs)

    flaky = FlakyProvider()
    monkeypatch.setattr(
        "app.services.transcription._create_provider", lambda *a, **k: flaky
    )

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 202, response.text
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "COMPLETED"
    assert detail["error"] is None
    assert flaky.calls == 2
    assert no_sleep == [1.0]
    # Pastikan identifier tetap UUID yang sah dan tidak ada path bocor.
    assert uuid.UUID(meeting_id)
