"""Pengujian Sprint 4 — speech-to-text dengan provider mock.

Tidak ada panggilan jaringan: provider mock disuntik lewat monkeypatch pada
`app.services.transcription._create_provider`.
"""

import uuid

from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

import app.services.transcription as transcription_service
from app.core.config import settings
from app.core.storage import storage_root
from app.models.transcript import TranscriptSegment, TranscriptionJob
from app.services.stt.base import SttSegment
from app.services.stt.errors import (
    SttAuthenticationError,
    SttConfigurationError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
)
from app.services.stt.mock import MockSttProvider

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


def _meeting_and_audio(client) -> str:
    created = client.post("/api/v1/meetings", json={"title": "Rapat STT"})
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]

    uploaded = client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("rapat.wav", WAV_HEADER, "audio/wav")},
        data={"duration_seconds": "6.0"},
    )
    assert uploaded.status_code == 201, uploaded.text
    return meeting_id


def _inject(monkeypatch, provider: MockSttProvider) -> None:
    # run_transcription memanggil _create_provider(nama_provider), jadi helper
    # harus menerima argumen walaupun provider mock mengabaikannya.
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: provider,
    )


def _segments() -> list[SttSegment]:
    return [
        SttSegment("Halo semua.", 0.0, 2.0),
        SttSegment("Mulai rapat.", 2.0, 4.0),
        SttSegment("Terima kasih.", 4.0, 6.0),
    ]


# ---------------------------------------------------------------------------
# Sukses & segmen
# ---------------------------------------------------------------------------


def test_successful_transcription(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=[_segments()[0]]))

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 202, response.text
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert detail["status"] == "COMPLETED"
    assert detail["meeting_status"] == "TRANSCRIBED"
    assert detail["provider"] == "mock"
    assert detail["has_timestamps"] is True
    assert detail["error"] is None
    assert len(detail["segments"]) == 1
    # Mock ditandai jelas — tidak menyamar sebagai transkrip sungguhan.
    assert detail["segments"][0]["text"].startswith("[MOCK]")


def test_multiple_segments_and_ordering(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    # Sengaja dibalik urutannya untuk menguji sorting deterministik.
    reversed_segments = list(reversed(_segments()))
    _inject(monkeypatch, MockSttProvider(segments=reversed_segments))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert len(detail["segments"]) == 3
    assert [item["sequence"] for item in detail["segments"]] == [1, 2, 3]
    assert [item["start_seconds"] for item in detail["segments"]] == [0.0, 2.0, 4.0]
    assert [item["end_seconds"] for item in detail["segments"]] == [2.0, 4.0, 6.0]
    assert "Halo" in detail["full_text"]


def test_text_only_result_has_no_fake_timestamps(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(text="Teks tanpa timestamp."))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["has_timestamps"] is False
    assert len(detail["segments"]) == 1
    assert detail["segments"][0]["start_seconds"] == 0.0
    assert detail["segments"][0]["end_seconds"] == 0.0


def test_retrieving_saved_transcript(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=_segments()))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    first = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    second = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert first == second
    assert len(second["segments"]) == 3


def test_transcription_not_started_returns_empty_list(s2_db, s2_client):
    meeting_id = _meeting_and_audio(s2_client)

    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "NOT_STARTED"
    assert detail["segments"] == []
    assert detail["full_text"] == ""


# ---------------------------------------------------------------------------
# Validasi & kegagalan
# ---------------------------------------------------------------------------


def test_invalid_timestamps_fail_transcription(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    bad = [SttSegment("Akhir sebelum awal.", 5.0, 1.0)]
    _inject(monkeypatch, MockSttProvider(segments=bad))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert detail["meeting_status"] == "FAILED"
    assert "waktu akhir" in detail["error"]
    assert detail["segments"] == []


def test_meeting_not_found(s2_db, s2_client):
    response = s2_client.post(f"/api/v1/meetings/{uuid.uuid4()}/transcription")
    assert response.status_code == 404


def test_missing_audio_asset(s2_db, s2_client):
    created = s2_client.post("/api/v1/meetings", json={"title": "Tanpa rekaman"})
    meeting_id = created.json()["id"]

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 404
    assert "rekaman" in response.json()["detail"].lower()


def test_missing_audio_file(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=[_segments()[0]]))

    asset = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").json()
    stored = storage_root() / "meetings" / meeting_id / asset["storage_filename"]
    stored.unlink()

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 404
    assert "file rekaman" in response.json()["detail"].lower()


def test_duplicate_request_prevention(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=[_segments()[0]]))
    # Biarkan job tetap PROCESSING supaya permintaan kedua bertabrakan.
    monkeypatch.setattr("app.api.v1.transcriptions.run_transcription", lambda meeting_id: None)

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    duplicate = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert duplicate.status_code == 409
    assert "sedang berjalan" in duplicate.json()["detail"]


def test_delete_recording_blocked_while_transcribing(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=[_segments()[0]]))
    monkeypatch.setattr("app.api.v1.transcriptions.run_transcription", lambda meeting_id: None)

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202

    asset = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").json()
    stored = storage_root() / "meetings" / meeting_id / asset["storage_filename"]

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 409
    assert "Transkripsi sedang berjalan" in response.json()["detail"]
    assert stored.is_file()
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200


def test_provider_authentication_failure(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(
        monkeypatch,
        MockSttProvider(error=SttAuthenticationError("Kredensial STT ditolak (uji).")),
    )

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert detail["error"] == "Kredensial STT ditolak (uji)."


def test_provider_timeout(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(error=SttTimeoutError("Timeout (uji).")))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert detail["error"] == "Timeout (uji)."


def test_provider_rate_limit(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(error=SttRateLimitError("Rate limit (uji).")))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert detail["error"] == "Rate limit (uji)."


def test_empty_provider_response_fails(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    # Mock tanpa teks/segmen sengaja menolak membuat transkrip palsu.
    _inject(monkeypatch, MockSttProvider())

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert "kosong" in detail["error"].lower()
    assert detail["segments"] == []


def test_missing_provider_configuration_returns_controlled_error(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)

    class BrokenConfigProvider(MockSttProvider):
        def validate_configuration(self):
            raise SttConfigurationError("STT_API_KEY belum diisi.")

    _inject(monkeypatch, BrokenConfigProvider(segments=[_segments()[0]]))

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 503
    assert "STT_API_KEY" in response.json()["detail"]
    # Meeting tidak boleh tertahan TRANSCRIBING saat validasi gagal.
    meetings = s2_client.get("/api/v1/meetings").json()
    assert next(m for m in meetings if m["id"] == meeting_id)["status"] == "UPLOADED"


# ---------------------------------------------------------------------------
# Hapus transkrip (audio harus tetap ada)
# ---------------------------------------------------------------------------


def test_delete_transcript_keeps_audio(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=_segments()))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202

    asset = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").json()
    stored = storage_root() / "meetings" / meeting_id / asset["storage_filename"]
    assert stored.is_file()

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 200
    assert response.json()["segments_deleted"] == 3
    assert stored.is_file()

    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert detail["status"] == "NOT_STARTED"
    assert detail["segments"] == []

    # AudioAsset masih bisa diputar/diambil metadata.
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording/play").status_code == 200

    meetings = s2_client.get("/api/v1/meetings").json()
    assert next(m for m in meetings if m["id"] == meeting_id)["status"] == "UPLOADED"


def test_delete_recording_also_clears_transcript(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=_segments()))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202

    assert s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200

    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert detail["segments"] == []
    assert detail["status"] == "NOT_STARTED"


def test_transcription_can_be_retried_after_failure(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(error=SttTimeoutError("Timeout (uji).")))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["status"] == "FAILED"

    _inject(monkeypatch, MockSttProvider(segments=[_segments()[0]]))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "COMPLETED"
    assert detail["error"] is None
    assert s2_db.query(TranscriptSegment).count() == 1
    assert s2_db.query(TranscriptionJob).count() == 1


# ---------------------------------------------------------------------------
# Konfigurasi publik: tidak ada secret yang bocor
# ---------------------------------------------------------------------------


def test_config_exposes_stt_info_without_secret(s2_client):
    response = s2_client.get("/api/v1/config")

    assert response.status_code == 200
    data = response.json()
    assert data["stt_provider"] == "mock"
    assert data["stt_configured"] is True
    assert "STT_API_KEY" not in response.text
    assert "sk-" not in response.text


def test_api_key_is_masked_in_repr_and_config(s2_client, monkeypatch):
    monkeypatch.setattr(settings, "STT_API_KEY", SecretStr("sk-rahasia-uji"))

    assert "sk-rahasia-uji" not in repr(settings)
    response = s2_client.get("/api/v1/config")
    assert "sk-rahasia-uji" not in response.text


# ---------------------------------------------------------------------------
# Transisi status & kegagalan tambahan
# ---------------------------------------------------------------------------


def test_status_transitions_uploaded_to_transcribing_to_transcribed(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _meeting_and_audio(s2_client)
    real_run = transcription_service.run_transcription
    _inject(monkeypatch, MockSttProvider(segments=[_segments()[0]]))
    # Tahan task agar status TRANSCRIBING bisa diamati sebelum provider selesai.
    monkeypatch.setattr("app.api.v1.transcriptions.run_transcription", lambda meeting_id: None)

    before = next(m for m in s2_client.get("/api/v1/meetings").json() if m["id"] == meeting_id)
    assert before["status"] == "UPLOADED"

    started = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert started.status_code == 202
    assert started.json()["meeting_status"] == "TRANSCRIBING"
    assert started.json()["status"] == "PROCESSING"

    during = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert during["status"] == "PROCESSING"

    # Jalankan fungsi aslinya secara sinkron untuk menyelesaikan transisi.
    real_run(uuid.UUID(meeting_id))

    after = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert after["status"] == "COMPLETED"
    assert after["meeting_status"] == "TRANSCRIBED"


def test_negative_timestamp_fails_transcription(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(monkeypatch, MockSttProvider(segments=[SttSegment("Negatif.", -1.0, 2.0)]))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert "negatif" in detail["error"].lower()
    assert detail["segments"] == []


def test_provider_server_error_fails_transcription(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    _inject(
        monkeypatch,
        MockSttProvider(error=SttProviderError("Provider STT gagal (HTTP 500).")),
    )

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "FAILED"
    assert "HTTP 500" in detail["error"]


def test_unsupported_provider_format_is_rejected_before_start(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)

    class NoFormatProvider(MockSttProvider):
        def supported_extensions(self):
            return set()

    _inject(monkeypatch, NoFormatProvider(segments=[_segments()[0]]))

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 415
    assert "tidak didukung" in response.json()["detail"].lower()
    assert s2_db.query(TranscriptionJob).count() == 0
    meetings = s2_client.get("/api/v1/meetings").json()
    assert next(m for m in meetings if m["id"] == meeting_id)["status"] == "UPLOADED"


def test_database_failure_returns_500_without_stuck_status(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)

    def boom(*args, **kwargs):
        raise SQLAlchemyError("database uji gagal")

    monkeypatch.setattr("app.services.transcription.clear_transcription", boom)

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 500
    assert "Gagal menyiapkan transkripsi" in response.json()["detail"]
    meetings = s2_client.get("/api/v1/meetings").json()
    assert next(m for m in meetings if m["id"] == meeting_id)["status"] == "UPLOADED"
