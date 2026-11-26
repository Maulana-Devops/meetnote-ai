"""Pengujian Sprint 7 — ringkasan AI dengan provider mock.

Semua panggilan LLM mock/httpx disuntik lewat monkeypatch. Tidak ada API key,
jaringan cloud, database produksi, atau folder `storage/` yang disentuh.
"""

import json
import uuid

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import inspect

import app.services.summary.workflow as summary_service
from app.core.config import settings
from app.models.summary import SummaryJob, SummaryStatus
from app.services.diarization.base import DiarizationTurn
from app.services.diarization.mock import MockDiarizationProvider
from app.services.llm.base import (
    SUMMARY_JSON_SCHEMA,
    SummaryDecision,
    SummaryInput,
    SummaryInputSegment,
    SummaryResult,
    SummaryTopic,
)
from app.services.llm.errors import (
    LlmAuthenticationError,
    LlmInvalidResultError,
    LlmProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
)
from app.services.llm.mock import MockLlmProvider
from app.services.llm.openai_provider import OpenAiLlmProvider
from app.services.stt.base import SttSegment
from app.services.stt.mock import MockSttProvider

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _meeting_and_audio(client, title: str = "Rapat Ringkasan") -> str:
    created = client.post("/api/v1/meetings", json={"title": title})
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


def _transcribed_meeting(s2_client, monkeypatch) -> str:
    meeting_id = _meeting_and_audio(s2_client)
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: MockSttProvider(segments=_transcript_segments()),
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 202, response.text
    return meeting_id


def _diarize(s2_client, monkeypatch, meeting_id: str) -> None:
    turns = [
        DiarizationTurn("0", 0.0, 2.0),
        DiarizationTurn("1", 2.0, 4.0),
        DiarizationTurn("0", 4.0, 6.0),
    ]
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: MockDiarizationProvider(turns=turns),
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")
    assert response.status_code == 202, response.text


def _inject_llm(monkeypatch, provider) -> None:
    monkeypatch.setattr(
        "app.services.summary.workflow._create_provider",
        lambda *args, **kwargs: provider,
    )


def _segments(s2_client, meeting_id: str) -> list[dict]:
    return s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["segments"]


def _summary(s2_client, meeting_id: str) -> dict:
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/summary")
    assert response.status_code == 200, response.text
    return response.json()


def _generate(s2_client, meeting_id: str):
    return s2_client.post(f"/api/v1/meetings/{meeting_id}/summary")


def _valid_result(
    overview: str,
    segments: list[dict],
    *,
    end_offset: float = 0.0,
    decisions: list[SummaryDecision] | None = None,
) -> SummaryResult:
    first = segments[0]
    return SummaryResult(
        overview=overview,
        topics=[
            SummaryTopic(
                title="Topik uji",
                detail="Detail dari transkrip.",
                segment_ids=(first["id"],),
                start_seconds=first["start_seconds"],
                end_seconds=first["end_seconds"] + end_offset,
            )
        ],
        decisions=decisions or [],
        provider="mock",
        model="mock-1",
        is_mock=True,
    )


def _openai_output(payload: dict) -> dict:
    return {
        "status": "completed",
        "model": "gpt-4o-mini-2024-08-06",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps(payload, ensure_ascii=False)}
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Sukses, penyimpanan, dan referensi
# ---------------------------------------------------------------------------


def test_successful_summary_is_saved_and_persists(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 202, response.text
    detail = _summary(s2_client, meeting_id)

    assert detail["status"] == "COMPLETED"
    assert detail["is_mock"] is True
    assert detail["provider"] == "mock"
    assert detail["model"] == "mock-1"
    assert detail["overview"].startswith("[MOCK]")
    assert detail["decisions"] == []
    assert len(detail["topics"]) == 1

    valid_ids = {segment["id"] for segment in _segments(s2_client, meeting_id)}
    for item in detail["topics"] + detail["decisions"]:
        assert item["segment_ids"]
        assert set(item["segment_ids"]).issubset(valid_ids)
        assert item["start_seconds"] >= 0
        assert item["end_seconds"] >= item["start_seconds"]

    refreshed = _summary(s2_client, meeting_id)
    assert refreshed["overview"] == detail["overview"]
    assert refreshed["topics"] == detail["topics"]


def test_speaker_display_name_is_used_then_falls_back_to_label(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _diarize(s2_client, monkeypatch, meeting_id)

    speakers = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["speakers"]
    first_speaker = speakers[0]
    patched = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/speakers/{first_speaker['id']}",
        json={"display_name": "Ani (catatan pengguna)"},
    )
    assert patched.status_code == 200, patched.text

    class RecordingProvider(MockLlmProvider):
        captured: SummaryInput | None = None

        def summarize(self, data: SummaryInput) -> SummaryResult:
            self.captured = data
            return super().summarize(data)

    provider = RecordingProvider()
    _inject_llm(monkeypatch, provider)
    assert _generate(s2_client, meeting_id).status_code == 202

    assert provider.captured is not None
    assert provider.captured.segments[0].speaker_display_name == "Ani (catatan pengguna)"
    assert provider.captured.segments[1].speaker_display_name == "Speaker 2"


def test_reported_times_are_normalized_from_database(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            result=_valid_result("[MOCK] Waktu dinormalisasi.", segments, end_offset=0.3)
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    topic = _summary(s2_client, meeting_id)["topics"][0]
    assert topic["end_seconds"] == segments[0]["end_seconds"]


def test_empty_decisions_array_is_allowed(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            result=SummaryResult(
                overview="[MOCK] Tidak ada keputusan eksplisit.",
                topics=[],
                decisions=[],
                provider="mock",
                model="mock-1",
            )
        ),
    )

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 202
    assert response.json()["decisions"] == []


# ---------------------------------------------------------------------------
# Regenerasi, konflik, validasi input
# ---------------------------------------------------------------------------


def test_failed_regeneration_keeps_previous_summary(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())
    assert _generate(s2_client, meeting_id).status_code == 202
    old_overview = _summary(s2_client, meeting_id)["overview"]

    _inject_llm(
        monkeypatch,
        MockLlmProvider(error=LlmProviderError("Provider LLM gagal (uji).")),
    )
    failed = _generate(s2_client, meeting_id)
    assert failed.status_code == 202
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "FAILED"
    assert current["overview"] == old_overview
    assert "Provider LLM gagal" in current["error"]

    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(result=_valid_result("[MOCK] Ringkasan baru.", segments)),
    )
    retried = _generate(s2_client, meeting_id)
    assert retried.status_code == 202
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "COMPLETED"
    assert current["overview"] == "[MOCK] Ringkasan baru."


def test_duplicate_processing_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr("app.api.v1.summaries.run_summary", lambda meeting_id: None)

    first = _generate(s2_client, meeting_id)
    assert first.status_code == 202
    assert first.json()["status"] == "PROCESSING"

    duplicate = _generate(s2_client, meeting_id)
    assert duplicate.status_code == 409
    assert "sedang diproses" in duplicate.json()["detail"]


def test_summary_is_blocked_while_transcription_is_processing(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _meeting_and_audio(s2_client)
    monkeypatch.setattr("app.api.v1.transcriptions.run_transcription", lambda meeting_id: None)
    assert (
        s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    )

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 409
    assert "Transkripsi sedang berjalan" in response.json()["detail"]


def test_summary_is_blocked_while_diarization_is_processing(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr("app.api.v1.diarizations.run_diarization", lambda meeting_id: None)
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: MockDiarizationProvider(
            turns=[DiarizationTurn("0", 0.0, 2.0)]
        ),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 409
    assert "Diarisasi sedang berjalan" in response.json()["detail"]


def test_missing_meeting_and_missing_transcript(s2_db, s2_client, monkeypatch):
    missing = str(uuid.uuid4())
    assert _generate(s2_client, missing).status_code == 404
    assert s2_client.get(f"/api/v1/meetings/{missing}/summary").status_code == 404

    meeting_id = _meeting_and_audio(s2_client)
    response = _generate(s2_client, meeting_id)
    assert response.status_code == 409
    assert "transkripsi" in response.json()["detail"].lower()


def test_overlong_transcript_returns_422(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr(settings, "LLM_MAX_INPUT_CHARACTERS", 10)

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 422
    assert "terlalu panjang" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Validasi output LLM dan error provider
# ---------------------------------------------------------------------------


def test_foreign_segment_reference_is_rejected_and_not_saved(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    result = _valid_result("[MOCK] Referensi asing.", segments)
    result = SummaryResult(
        overview=result.overview,
        topics=[
            SummaryTopic(
                title=result.topics[0].title,
                detail=result.topics[0].detail,
                segment_ids=(str(uuid.uuid4()),),
                start_seconds=0.0,
                end_seconds=2.0,
            )
        ],
        decisions=[],
        provider="mock",
        model="mock-1",
    )
    _inject_llm(monkeypatch, MockLlmProvider(result=result))

    assert _generate(s2_client, meeting_id).status_code == 202
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "FAILED"
    assert "tidak termasuk meeting" in current["error"]
    assert current["overview"] == ""
    assert current["topics"] == []


def test_wrong_timestamp_reference_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            result=_valid_result("[MOCK] Waktu salah.", segments, end_offset=5.0)
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "FAILED"
    assert "start_seconds" in current["error"] or "end_seconds" in current["error"]
    assert current["topics"] == []


def test_missing_decisions_field_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            payload={
                "overview": "[MOCK] Respons tanpa decisions.",
                "topics": [
                    {
                        "title": "Topik",
                        "detail": "Detail",
                        "segment_ids": [segments[0]["id"]],
                        "start_seconds": segments[0]["start_seconds"],
                        "end_seconds": segments[0]["end_seconds"],
                    }
                ],
            }
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "FAILED"
    assert "decisions" in current["error"]


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (LlmAuthenticationError("Kredensial LLM ditolak."), "Kredensial"),
        (LlmTimeoutError("LLM timeout."), "timeout"),
        (LlmRateLimitError("Rate limit LLM."), "Rate limit"),
        (LlmProviderError("HTTP 500."), "HTTP 500"),
    ],
)
def test_provider_failures_mark_job_failed(
    s2_db, s2_client, monkeypatch, error, fragment
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider(error=error))

    assert _generate(s2_client, meeting_id).status_code == 202
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "FAILED"
    assert fragment.lower() in current["error"].lower()


def test_unknown_provider_is_rejected_before_job_creation(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "tidak-ada")
    # Kembalikan factory asli karena inject mock test sebelumnya tidak aktif di sini.
    monkeypatch.setattr(
        "app.services.summary.workflow._create_provider",
        lambda *args, **kwargs: summary_service.create_provider(*args, **kwargs),
    )

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 503
    assert "LLM_PROVIDER" in response.json()["detail"]
    assert _summary(s2_client, meeting_id)["status"] == "NOT_STARTED"


# ---------------------------------------------------------------------------
# Delete, recovery, dan migrasi aditif
# ---------------------------------------------------------------------------


def test_delete_summary_keeps_transcript_and_audio(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())
    assert _generate(s2_client, meeting_id).status_code == 202

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/summary")
    assert response.status_code == 200, response.text
    assert response.json()["summaries_deleted"] == 1
    assert response.json()["jobs_deleted"] == 1

    current = _summary(s2_client, meeting_id)
    assert current["status"] == "NOT_STARTED"
    assert current["overview"] == ""
    assert len(_segments(s2_client, meeting_id)) == 3
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200


def test_delete_summary_is_blocked_while_processing(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr("app.api.v1.summaries.run_summary", lambda meeting_id: None)
    assert _generate(s2_client, meeting_id).status_code == 202

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/summary")
    assert response.status_code == 409
    assert "sedang diproses" in response.json()["detail"]


def test_deleting_transcript_clears_stale_summary(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())
    assert _generate(s2_client, meeting_id).status_code == 202

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 200
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "NOT_STARTED"
    assert current["overview"] == ""


def test_restart_recovery_marks_processing_summary_as_failed(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr("app.api.v1.summaries.run_summary", lambda meeting_id: None)
    assert _generate(s2_client, meeting_id).status_code == 202

    recovered = summary_service.recover_stuck_summaries()
    assert recovered == 1
    current = _summary(s2_client, meeting_id)
    assert current["status"] == "FAILED"
    assert "dimulai ulang" in current["error"]


def test_summary_tables_are_additive(s2_db):
    tables = set(inspect(s2_db.get_bind()).get_table_names())
    assert {"meeting_summaries", "summary_jobs"}.issubset(tables)
    assert {"meetings", "audio_assets", "transcript_segments", "speakers"}.issubset(tables)

    columns = {column["name"] for column in inspect(s2_db.get_bind()).get_columns("meeting_summaries")}
    assert {"overview", "topics", "decisions", "provider", "is_mock"}.issubset(columns)
    assert not {"action_items", "assignee", "deadline"}.intersection(columns)


# ---------------------------------------------------------------------------
# Konfigurasi publik & provider OpenAI (tanpa panggilan jaringan)
# ---------------------------------------------------------------------------


def test_config_exposes_llm_info_without_secret(s2_client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("llm-rahasia-uji"))

    response = s2_client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["llm_provider"] == "mock"
    assert response.json()["llm_configured"] is True
    assert "llm-rahasia-uji" not in response.text
    assert "llm-rahasia-uji" not in repr(settings)


def test_openai_provider_sends_strict_structured_output(s2_client, monkeypatch):
    segment = SummaryInputSegment("seg-1", "Rapat dimulai.", 0.0, 2.0, "Speaker 1")
    data = SummaryInput("Rapat Uji", [segment])

    calls: list[dict] = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json=_openai_output(
                {
                    "overview": "Rapat dimulai.",
                    "topics": [
                        {
                            "title": "Pembukaan",
                            "detail": "Rapat dimulai.",
                            "segment_ids": ["seg-1"],
                            "start_seconds": 0.0,
                            "end_seconds": 2.0,
                        }
                    ],
                    "decisions": [],
                }
            ),
        )

    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("sk-uji"))
    monkeypatch.setattr(settings, "LLM_API_BASE_URL", "https://llm.test/v1")
    monkeypatch.setattr("app.services.llm.openai_provider.httpx.post", fake_post)

    result = OpenAiLlmProvider().summarize(data)

    assert calls[0]["url"] == "https://llm.test/v1/responses"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-uji"
    text_format = calls[0]["json"]["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["name"] == "meeting_summary"
    assert result.provider == "openai"
    assert result.decisions == []
    assert result.topics[0].segment_ids == ("seg-1",)

    schema_text = json.dumps(SUMMARY_JSON_SCHEMA).lower()
    assert "action" not in schema_text
    assert "assignee" not in schema_text
    assert "deadline" not in schema_text


def test_openai_provider_maps_http_errors_and_bad_json(s2_client, monkeypatch):
    data = SummaryInput(
        "Rapat Uji", [SummaryInputSegment("seg-1", "Teks.", 0.0, 1.0)]
    )
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("sk-uji"))

    def failing_post(status_code: int):
        def post(url, **kwargs):
            return httpx.Response(status_code, json={"error": "rahasia"})

        return post

    for status_code, expected in ((401, LlmAuthenticationError), (429, LlmRateLimitError)):
        monkeypatch.setattr(
            "app.services.llm.openai_provider.httpx.post", failing_post(status_code)
        )
        with pytest.raises(expected):
            OpenAiLlmProvider().summarize(data)

    def invalid_json(url, **kwargs):
        return httpx.Response(200, text="bukan-json")

    monkeypatch.setattr("app.services.llm.openai_provider.httpx.post", invalid_json)
    with pytest.raises(LlmProviderError):
        OpenAiLlmProvider().summarize(data)

    def refusal(url, **kwargs):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "ditolak"}],
                    }
                ],
            },
        )

    monkeypatch.setattr("app.services.llm.openai_provider.httpx.post", refusal)
    with pytest.raises(LlmInvalidResultError):
        OpenAiLlmProvider().summarize(data)


def test_openai_provider_maps_timeout_without_exposing_key(s2_client, monkeypatch):
    data = SummaryInput(
        "Rapat Uji", [SummaryInputSegment("seg-1", "Teks.", 0.0, 1.0)]
    )
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("sk-jangan-tampil"))

    def timeout_post(url, **kwargs):
        raise httpx.TimeoutException("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.llm.openai_provider.httpx.post", timeout_post)
    with pytest.raises(LlmTimeoutError) as exc:
        OpenAiLlmProvider().summarize(data)
    assert "sk-jangan-tampil" not in str(exc.value)
