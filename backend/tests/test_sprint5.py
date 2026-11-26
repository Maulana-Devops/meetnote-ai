"""Pengujian Sprint 5 — speaker diarisasi dengan provider mock.

Tidak ada panggilan jaringan: provider mock disuntik lewat monkeypatch pada
`app.services.diarization.workflow._create_provider`.
"""

import uuid

from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

import app.services.diarization.workflow as diarization_service
import app.services.transcription as transcription_service
from app.core.config import settings
from app.core.storage import storage_root
from app.models.diarization import DiarizationJob, Speaker
from app.models.transcript import TranscriptSegment
from app.services.diarization.base import DiarizationTurn
from app.services.diarization.errors import (
    DiarizationProviderError,
    DiarizationTimeoutError,
)
from app.services.diarization.mock import MockDiarizationProvider
from app.services.diarization.workflow import (
    assign_speaker_labels,
    map_turns_to_segments,
)
from app.services.stt.base import SttSegment
from app.services.stt.mock import MockSttProvider

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


def _create_meeting_with_audio(client) -> str:
    created = client.post("/api/v1/meetings", json={"title": "Rapat Diarisasi"})
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]

    uploaded = client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("rapat.wav", WAV_HEADER, "audio/wav")},
        data={"duration_seconds": "6.0"},
    )
    assert uploaded.status_code == 201, uploaded.text
    return meeting_id


def _transcript_segments() -> list[SttSegment]:
    return [
        SttSegment("Halo semua.", 0.0, 2.0),
        SttSegment("Mulai rapat.", 2.0, 4.0),
        SttSegment("Terima kasih.", 4.0, 6.0),
    ]


def _transcribed_meeting(
    s2_client,
    monkeypatch,
    segments: list[SttSegment] | None = None,
) -> str:
    meeting_id = _create_meeting_with_audio(s2_client)
    provider = MockSttProvider(
        segments=segments if segments is not None else _transcript_segments()
    )
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: provider,
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 202, response.text
    return meeting_id


def _inject_diarization(monkeypatch, provider: MockDiarizationProvider) -> None:
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: provider,
    )


def _basic_turns() -> list[DiarizationTurn]:
    return [
        DiarizationTurn("0", 0.0, 2.0),
        DiarizationTurn("1", 2.0, 4.0),
        DiarizationTurn("0", 4.0, 6.0),
    ]


def _seg(sequence: int, start: float, end: float, text: str = "Teks") -> TranscriptSegment:
    return TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=str(uuid.uuid4()),
        text=text,
        start_seconds=start,
        end_seconds=end,
        sequence=sequence,
    )


# ---------------------------------------------------------------------------
# Sukses, label, dan relasi
# ---------------------------------------------------------------------------


def test_successful_diarization_with_anonymous_labels(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 202, response.text
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()
    assert detail["status"] == "COMPLETED"
    assert detail["provider"] == "mock"
    assert detail["is_mock"] is True
    assert detail["turns_count"] == 3
    assert detail["mapped_segments"] == 3
    assert [speaker["speaker_label"] for speaker in detail["speakers"]] == [
        "Speaker 1",
        "Speaker 2",
    ]

    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert [segment["speaker_label"] for segment in transcript["segments"]] == [
        "Speaker 1",
        "Speaker 2",
        "Speaker 1",
    ]
    # Teks dan timestamp asli tidak berubah saat diarisasi.
    assert transcript["segments"][0]["text"].startswith("[MOCK]")
    assert transcript["segments"][0]["start_seconds"] == 0.0
    assert transcript["segments"][0]["end_seconds"] == 2.0


def test_speaker_to_segment_relationship_is_persisted(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    segments = (
        s2_db.query(TranscriptSegment)
        .filter(TranscriptSegment.meeting_id == meeting_id)
        .order_by(TranscriptSegment.sequence)
        .all()
    )
    speakers = (
        s2_db.query(Speaker)
        .filter(Speaker.meeting_id == meeting_id)
        .all()
    )
    assert len(speakers) == 2
    assert all(segment.speaker_id is not None for segment in segments)
    assert {segment.speaker.speaker_label for segment in segments} == {
        "Speaker 1",
        "Speaker 2",
    }
    assert s2_db.query(DiarizationJob).filter_by(meeting_id=meeting_id).one().status == "COMPLETED"


def test_speaker_labels_are_deterministic_for_numeric_provider_refs(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(
        s2_client,
        monkeypatch,
        [
            SttSegment("A.", 0.0, 1.0),
            SttSegment("B.", 1.0, 2.0),
            SttSegment("C.", 2.0, 3.0),
        ],
    )
    turns = [
        DiarizationTurn("10", 0.0, 1.0),
        DiarizationTurn("2", 1.0, 2.0),
        DiarizationTurn("1", 2.0, 3.0),
    ]
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=turns))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    # 1, 2, 10 diurutkan sebagai angka, bukan string ("1", "10", "2").
    assert [speaker["speaker_label"] for speaker in detail["speakers"]] == [
        "Speaker 1",
        "Speaker 2",
        "Speaker 3",
    ]
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert [segment["speaker_label"] for segment in transcript["segments"]] == [
        "Speaker 3",
        "Speaker 2",
        "Speaker 1",
    ]


def test_assign_speaker_labels_unit():
    turns = [DiarizationTurn("10", 0, 1), DiarizationTurn("2", 1, 2)]
    assert assign_speaker_labels(turns) == {"2": "Speaker 1", "10": "Speaker 2"}


# ---------------------------------------------------------------------------
# Mapping temporal
# ---------------------------------------------------------------------------


def test_no_overlap_leaves_segments_unassigned(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(
        monkeypatch,
        MockDiarizationProvider(turns=[DiarizationTurn("0", 10.0, 12.0)]),
    )

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "COMPLETED"
    assert detail["mapped_segments"] == 0
    assert all(segment["speaker_label"] is None for segment in transcript["segments"])


def test_below_overlap_threshold_is_unassigned(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(
        s2_client,
        monkeypatch,
        [SttSegment("Satu segmen panjang.", 0.0, 6.0)],
    )
    # Segmen 0-6, turn 0-2 → overlap 2 detik < 50% durasi segmen.
    _inject_diarization(
        monkeypatch,
        MockDiarizationProvider(turns=[DiarizationTurn("0", 0.0, 2.0)]),
    )

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert transcript["segments"][0]["speaker_label"] is None


def test_ambiguous_overlap_is_not_guessed(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(
        s2_client,
        monkeypatch,
        [SttSegment("Satu segmen panjang.", 0.0, 6.0)],
    )
    turns = [
        DiarizationTurn("0", 0.0, 3.0),
        DiarizationTurn("1", 3.0, 6.0),
    ]
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=turns))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert detail["status"] == "COMPLETED"
    assert detail["mapped_segments"] == 0
    assert transcript["segments"][0]["speaker_label"] is None


def test_overlapping_speech_uses_strongest_overlap(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(
        s2_client,
        monkeypatch,
        [SttSegment("Percakapan bersamaan.", 0.0, 6.0)],
    )
    turns = [
        DiarizationTurn("0", 0.0, 5.0),
        DiarizationTurn("1", 2.0, 6.0),
    ]
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=turns))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert transcript["segments"][0]["speaker_label"] == "Speaker 1"


def test_missing_timestamps_are_left_unassigned(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    # Unit test untuk segmen text-only Sprint 4 (timestamp 0/0).
    segment = _seg(1, 0.0, 0.0, "Tanpa timestamp")
    mapping = map_turns_to_segments(
        [segment],
        _basic_turns(),
        assign_speaker_labels(_basic_turns()),
    )
    assert mapping == {}


# ---------------------------------------------------------------------------
# Validasi & error
# ---------------------------------------------------------------------------


def test_invalid_negative_timestamp_fails_job(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    turns = [DiarizationTurn("0", -1.0, 2.0)]
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=turns))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "FAILED"
    assert "negatif" in detail["error"]


def test_invalid_end_before_start_fails_job(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    turns = [DiarizationTurn("0", 4.0, 2.0)]
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=turns))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "FAILED"
    assert "waktu akhir" in detail["error"]


def test_unknown_speaker_reference_fails_job(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    turns = [DiarizationTurn("", 0.0, 2.0)]
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=turns))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "FAILED"
    assert "referensi speaker" in detail["error"]


def test_empty_provider_response_fails_job(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=[]))

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "FAILED"
    assert "kosong" in detail["error"]


def test_missing_completed_transcript_is_rejected(s2_db, s2_client):
    meeting_id = _create_meeting_with_audio(s2_client)

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 409
    assert "Transkrip" in response.json()["detail"]


def test_missing_audio_asset_is_rejected(s2_db, s2_client):
    created = s2_client.post("/api/v1/meetings", json={"title": "Tanpa audio"})
    meeting_id = created.json()["id"]

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 404
    assert "rekaman" in response.json()["detail"].lower()


def test_missing_audio_file_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    asset = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").json()
    stored = storage_root() / "meetings" / meeting_id / asset["storage_filename"]
    stored.unlink()

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 404
    assert "file rekaman" in response.json()["detail"].lower()


def test_meeting_not_found(s2_db, s2_client):
    response = s2_client.post(f"/api/v1/meetings/{uuid.uuid4()}/diarization")
    assert response.status_code == 404


def test_duplicate_request_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    # Task tidak dijalankan sehingga job tetap PROCESSING.
    monkeypatch.setattr("app.api.v1.diarizations.run_diarization", lambda meeting_id: None)

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    duplicate = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert duplicate.status_code == 409
    assert "sedang berjalan" in duplicate.json()["detail"]


def test_provider_failure_marks_job_failed(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(
        monkeypatch,
        MockDiarizationProvider(error=DiarizationProviderError("Gagal dari provider.")),
    )

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "FAILED"
    assert detail["error"] == "Gagal dari provider."


def test_provider_timeout_marks_job_failed(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(
        monkeypatch,
        MockDiarizationProvider(error=DiarizationTimeoutError("Provider timeout.")),
    )

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "FAILED"
    assert "timeout" in detail["error"].lower()


def test_failed_job_can_be_retried(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(
        monkeypatch,
        MockDiarizationProvider(error=DiarizationProviderError("Gagal sementara.")),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["status"] == "FAILED"

    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert detail["status"] == "COMPLETED"
    assert detail["error"] is None


def test_unsupported_format_is_rejected_before_job(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    provider = MockDiarizationProvider(
        turns=_basic_turns(),
        supported_extensions={".flac"},
    )
    _inject_diarization(monkeypatch, provider)

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 415
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["status"] == "NOT_STARTED"


def test_database_failure_returns_500(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))

    def fail(*args, **kwargs):
        raise SQLAlchemyError("database down")

    monkeypatch.setattr("app.services.diarization.workflow.clear_diarization", fail)

    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 500
    assert "Gagal menyiapkan diarisasi" in response.json()["detail"]


def test_recover_stuck_diarizations(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    monkeypatch.setattr("app.api.v1.diarizations.run_diarization", lambda meeting_id: None)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    recovered = diarization_service.recover_stuck_diarizations()
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert recovered == 1
    assert detail["status"] == "FAILED"
    assert "dimulai ulang" in detail["error"]


# ---------------------------------------------------------------------------
# Delete & interaksi dengan fitur lama
# ---------------------------------------------------------------------------


def test_delete_diarization_keeps_transcript_and_audio(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    before = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    asset = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").json()
    stored = storage_root() / "meetings" / meeting_id / asset["storage_filename"]

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/diarization")

    assert response.status_code == 200, response.text
    assert response.json()["speakers_deleted"] == 2
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["status"] == "NOT_STARTED"

    after = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert after["full_text"] == before["full_text"]
    assert [item["text"] for item in after["segments"]] == [
        item["text"] for item in before["segments"]
    ]
    assert all(item["speaker_label"] is None for item in after["segments"])
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200
    assert stored.is_file()


def test_delete_recording_blocked_while_diarizing(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    monkeypatch.setattr("app.api.v1.diarizations.run_diarization", lambda meeting_id: None)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    asset = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").json()
    stored = storage_root() / "meetings" / meeting_id / asset["storage_filename"]

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 409
    assert "Diarisasi sedang berjalan" in response.json()["detail"]
    assert stored.is_file()


def test_delete_transcript_blocked_while_diarizing(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    monkeypatch.setattr("app.api.v1.diarizations.run_diarization", lambda meeting_id: None)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 409
    assert "Diarisasi sedang berjalan" in response.json()["detail"]


def test_retranscribing_clears_stale_diarization(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["status"] == "COMPLETED"

    new_segments = [SttSegment("Transkrip baru.", 0.0, 6.0)]
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: MockSttProvider(segments=new_segments),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202

    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    diarization = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()

    assert len(transcript["segments"]) == 1
    assert transcript["segments"][0]["speaker_label"] is None
    assert diarization["status"] == "NOT_STARTED"
    assert diarization["speakers"] == []


def test_deleting_recording_clears_diarization(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_diarization(monkeypatch, MockDiarizationProvider(turns=_basic_turns()))
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 200, response.text
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()
    assert detail["status"] == "NOT_STARTED"
    assert detail["speakers"] == []


# ---------------------------------------------------------------------------
# Konfigurasi publik & keamanan
# ---------------------------------------------------------------------------


def test_config_exposes_diarization_info_without_secret(s2_client):
    response = s2_client.get("/api/v1/config")

    assert response.status_code == 200
    data = response.json()
    assert data["diarization_provider"] == "mock"
    assert data["diarization_configured"] is True
    assert "DIARIZATION_API_KEY" not in response.text
    assert "sk-" not in response.text


def test_api_key_is_masked_in_repr_and_config(s2_client, monkeypatch):
    monkeypatch.setattr(settings, "DIARIZATION_API_KEY", SecretStr("sk-rahasia-diarisasi"))

    assert "sk-rahasia-diarisasi" not in repr(settings)
    response = s2_client.get("/api/v1/config")
    assert "sk-rahasia-diarisasi" not in response.text


def test_workflow_does_not_import_transcription_service_at_module_scope():
    # Status diarisasi memang disimpan terpisah; modul workflow tidak boleh
    # mengimpor workflow transkripsi secara melingkar.
    assert not hasattr(diarization_service, "prepare_transcription")
    assert not hasattr(transcription_service, "prepare_diarization")


# ---------------------------------------------------------------------------
# Kontrak provider Deepgram (unit, tanpa jaringan)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Merekam satu POST lalu mengembalikan response yang diatur test."""

    last_call: dict | None = None

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, params, headers, content):
        _FakeClient.last_call = {
            "url": url,
            "params": params,
            "headers": headers,
            "body": b"".join(content),
        }
        return self._response


def _configure_deepgram(monkeypatch, tmp_path):
    import app.services.diarization.deepgram_provider as deepgram

    audio_path = tmp_path / "rapat.wav"
    audio_path.write_bytes(WAV_HEADER)

    monkeypatch.setattr(settings, "DIARIZATION_API_KEY", SecretStr("sk-test-deepgram"))
    monkeypatch.setattr(settings, "DIARIZATION_API_BASE_URL", "https://api.deepgram.com/v1")
    monkeypatch.setattr(settings, "DIARIZATION_MODEL", "nova-3")
    monkeypatch.setattr(settings, "DIARIZATION_DIARIZE_MODEL", "latest")
    monkeypatch.setattr(settings, "DIARIZATION_TIMEOUT_SECONDS", 42.0)
    return audio_path, deepgram


def test_deepgram_request_matches_verified_docs(monkeypatch, tmp_path):
    audio_path, deepgram = _configure_deepgram(monkeypatch, tmp_path)
    response = _FakeResponse(
        200,
        {
            "metadata": {"diarize_info": {"model": "latest"}},
            "results": {
                "utterances": [
                    {"start": 0.0, "end": 2.0, "speaker": 0, "transcript": "Halo"},
                ]
            },
        },
    )
    captured_timeouts = []
    monkeypatch.setattr(
        deepgram.httpx,
        "Client",
        lambda **kwargs: (captured_timeouts.append(kwargs.get("timeout")) or _FakeClient(response)),
    )

    provider = deepgram.DeepgramDiarizationProvider()
    result = provider.diarize(audio_path, "rapat.wav", "audio/wav")

    call = _FakeClient.last_call
    assert call["url"] == "https://api.deepgram.com/v1/listen"
    assert call["params"] == {
        "model": "nova-3",
        "diarize_model": "latest",
        "utterances": "true",
    }
    assert call["headers"]["Authorization"] == "Token sk-test-deepgram"
    assert call["headers"]["Content-Type"] == "audio/wav"
    assert call["body"] == WAV_HEADER
    assert captured_timeouts == [42.0]
    assert result.provider == "deepgram"
    assert result.turns == [DiarizationTurn("0", 0.0, 2.0)]


def test_deepgram_falls_back_to_words_when_no_utterances(monkeypatch, tmp_path):
    audio_path, deepgram = _configure_deepgram(monkeypatch, tmp_path)
    response = _FakeResponse(
        200,
        {
            "metadata": {"diarize_info": {}},
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "words": [
                                    {"word": "a", "start": 0.0, "end": 0.5, "speaker": 1, "speaker_confidence": 0.9},
                                    {"word": "b", "start": 0.5, "end": 1.0, "speaker": 1, "speaker_confidence": 0.9},
                                    {"word": "c", "start": 1.0, "end": 1.5, "speaker": 0, "speaker_confidence": 0.9},
                                ]
                            }
                        ]
                    }
                ]
            },
        },
    )
    monkeypatch.setattr(deepgram.httpx, "Client", lambda **kwargs: _FakeClient(response))

    result = deepgram.DeepgramDiarizationProvider().diarize(
        audio_path, "rapat.wav", "audio/wav"
    )

    # Kata berurutan dengan speaker sama digabung; urutan tetap chronological.
    assert result.turns == [
        DiarizationTurn("1", 0.0, 1.0),
        DiarizationTurn("0", 1.0, 1.5),
    ]


def test_deepgram_auth_error_is_sanitized(monkeypatch, tmp_path):
    audio_path, deepgram = _configure_deepgram(monkeypatch, tmp_path)
    monkeypatch.setattr(
        deepgram.httpx,
        "Client",
        lambda **kwargs: _FakeClient(_FakeResponse(401)),
    )

    try:
        deepgram.DeepgramDiarizationProvider().diarize(audio_path, "rapat.wav", "audio/wav")
    except Exception as exc:
        assert "kredensial" in str(exc)
        assert "sk-test-deepgram" not in str(exc)
    else:
        raise AssertionError("401 harus memunculkan error")


def test_deepgram_requires_diarize_info(monkeypatch, tmp_path):
    audio_path, deepgram = _configure_deepgram(monkeypatch, tmp_path)
    response = _FakeResponse(200, {"results": {"utterances": []}})
    monkeypatch.setattr(deepgram.httpx, "Client", lambda **kwargs: _FakeClient(response))

    try:
        deepgram.DeepgramDiarizationProvider().diarize(audio_path, "rapat.wav", "audio/wav")
    except Exception as exc:
        assert "diarize_info" in str(exc)
    else:
        raise AssertionError("Respons tanpa diarize_info harus ditolak")
