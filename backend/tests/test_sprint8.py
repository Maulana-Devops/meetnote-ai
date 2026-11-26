"""Pengujian Sprint 8 — action items dengan provider LLM mock.

Tidak ada API key, jaringan cloud, database produksi, atau folder `storage/`
yang disentuh. Provider dan HTTP client selalu disuntik lewat monkeypatch.
"""

import datetime
import json

import httpx
import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

import app.api.v1.action_items as action_items_api
import app.services.action_items.workflow as action_service
import app.services.summary.workflow as summary_service
from app.models.action_item import (
    ActionExtractionStatus,
    ActionItemJob,
    ActionItemStatus,
)
from app.models.diarization import DiarizationJob, DiarizationStatus
from app.models.summary import SummaryStatus
from app.models.transcript import TranscriptionJob, TranscriptionStatus
from app.services.diarization.base import DiarizationTurn
from app.services.diarization.mock import MockDiarizationProvider
from app.services.llm.base import (
    ACTION_ITEMS_JSON_SCHEMA,
    ActionItemExtractionResult,
    ActionItemInput,
    ExtractedActionItem,
)
from app.services.llm.errors import (
    LlmInvalidResultError,
    LlmProviderError,
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


def _meeting_and_audio(client, title: str = "Rapat Action Items") -> str:
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
        SttSegment("Saya akan mengirim laporan.", 0.0, 2.0),
        SttSegment("Tim jaringan perlu memeriksa server.", 2.0, 4.0),
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
        DiarizationTurn("Speaker 1", 0.0, 2.0),
        DiarizationTurn("Speaker 2", 2.0, 4.0),
        DiarizationTurn("Speaker 1", 4.0, 6.0),
    ]
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: MockDiarizationProvider(turns=turns),
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")
    assert response.status_code == 202, response.text


def _inject_llm(monkeypatch, provider) -> None:
    monkeypatch.setattr(
        "app.services.action_items.workflow._create_provider",
        lambda *args, **kwargs: provider,
    )


def _segments(s2_client, meeting_id: str) -> list[dict]:
    return s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["segments"]


def _items(s2_client, meeting_id: str) -> dict:
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/action-items")
    assert response.status_code == 200, response.text
    return response.json()


def _generate(s2_client, meeting_id: str):
    return s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items")


def _extracted(segments: list[dict], **overrides) -> ExtractedActionItem:
    first = segments[0]
    values = {
        "title": "Mengirim laporan proyek",
        "description": "Laporan perkembangan proyek dikirim ke tim.",
        "assignee_speaker_label": None,
        "assignee_text": None,
        "deadline_text": None,
        "due_date": None,
        "segment_ids": (first["id"],),
        "start_seconds": first["start_seconds"],
        "end_seconds": first["end_seconds"],
    }
    values.update(overrides)
    return ExtractedActionItem(**values)


def _result(items: list[ExtractedActionItem]) -> ActionItemExtractionResult:
    return ActionItemExtractionResult(
        items=items, provider="mock", model="mock-1", is_mock=True
    )


def _payload(segments: list[dict], **overrides) -> dict:
    first = segments[0]
    item = {
        "title": "Mengirim laporan proyek",
        "description": "Laporan perkembangan proyek dikirim ke tim.",
        "assignee_speaker_label": None,
        "assignee_text": None,
        "deadline_text": None,
        "due_date": None,
        "segment_ids": [first["id"]],
        "start_seconds": first["start_seconds"],
        "end_seconds": first["end_seconds"],
    }
    item.update(overrides)
    return {"action_items": [item]}


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
# Extraction
# ---------------------------------------------------------------------------


def test_valid_action_items_are_saved_and_persist(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 202, response.text
    detail = _items(s2_client, meeting_id)

    assert detail["status"] == "COMPLETED"
    assert detail["is_mock"] is True
    assert detail["provider"] == "mock"
    assert len(detail["items"]) == 1
    item = detail["items"][0]
    assert item["status"] == ActionItemStatus.OPEN
    assert item["is_manually_edited"] is False
    assert item["title"].startswith("[MOCK]")

    valid_ids = {segment["id"] for segment in _segments(s2_client, meeting_id)}
    assert item["segment_ids"]
    assert set(item["segment_ids"]).issubset(valid_ids)
    assert item["start_seconds"] >= 0
    assert item["end_seconds"] >= item["start_seconds"]

    refreshed = _items(s2_client, meeting_id)
    assert refreshed["items"] == detail["items"]


def test_no_action_items_is_a_valid_result(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider(action_result=_result([])))

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "COMPLETED"
    assert detail["items"] == []


def test_no_assignee_and_no_deadline_are_null(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _diarize(s2_client, monkeypatch, meeting_id)
    _inject_llm(monkeypatch, MockLlmProvider())

    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    assert item["assignee_speaker_id"] is None
    assert item["assignee_text"] is None
    assert item["deadline_text"] is None
    assert item["due_date"] is None


def test_textual_deadline_is_kept_with_null_due_date(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [_extracted(segments, deadline_text="hari Jumat", due_date=None)]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    assert item["deadline_text"] == "hari Jumat"
    assert item["due_date"] is None


def test_explicit_due_date_is_parsed(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    due = datetime.date(2026, 11, 27)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [
                    _extracted(
                        segments,
                        deadline_text="27 November 2026",
                        due_date=due,
                    )
                ]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    assert item["deadline_text"] == "27 November 2026"
    assert item["due_date"] == due.isoformat()


def test_invalid_due_date_format_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(action_payload=_payload(segments, due_date="besok")),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == []
    assert "tanggal" in detail["error"]


def test_valid_speaker_mapping_sets_assignee_speaker_id(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _diarize(s2_client, monkeypatch, meeting_id)
    segments = _segments(s2_client, meeting_id)
    speakers = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["speakers"]
    speaker = speakers[0]
    label = speaker["display_name"] or speaker["speaker_label"]

    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result([_extracted(segments, assignee_speaker_label=label)])
        ),
    )
    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    assert item["assignee_speaker_id"] == speaker["id"]


def test_invalid_speaker_label_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _diarize(s2_client, monkeypatch, meeting_id)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [_extracted(segments, assignee_speaker_label="Speaker 99")]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == []
    assert "speaker" in detail["error"].lower()


def test_assignee_text_without_speaker_mapping_is_kept(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [
                    _extracted(
                        segments,
                        assignee_text="Ani (disebut dalam rapat)",
                        assignee_speaker_label=None,
                    )
                ]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    assert item["assignee_text"] == "Ani (disebut dalam rapat)"
    assert item["assignee_speaker_id"] is None


def test_cross_meeting_segment_reference_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    other_id = _transcribed_meeting(s2_client, monkeypatch)
    other_segment = _segments(s2_client, other_id)[0]
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [
                    _extracted(
                        segments,
                        segment_ids=(other_segment["id"],),
                        start_seconds=other_segment["start_seconds"],
                        end_seconds=other_segment["end_seconds"],
                    )
                ]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == []
    assert "segmen" in detail["error"].lower()


def test_empty_segment_reference_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(action_payload=_payload(segments, segment_ids=[])),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == []


def test_timestamp_mismatch_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [_extracted(segments, end_seconds=segments[0]["end_seconds"] + 5)]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == []
    assert "waktu" in detail["error"].lower() or "seconds" in detail["error"].lower()


def test_timestamps_are_normalized_from_database(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [
                    _extracted(
                        segments,
                        start_seconds=segments[0]["start_seconds"] + 0.2,
                        end_seconds=segments[0]["end_seconds"] - 0.2,
                    )
                ]
            )
        ),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    assert item["start_seconds"] == segments[0]["start_seconds"]
    assert item["end_seconds"] == segments[0]["end_seconds"]


def test_invalid_json_output_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(action_payload={"action_items": "bukan array"}),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    assert _items(s2_client, meeting_id)["status"] == "FAILED"


def test_unknown_field_in_output_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(action_payload=_payload(segments, prioritas="tinggi")),
    )

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert "prioritas" in detail["error"]


@pytest.mark.parametrize(
    "error,expected_word",
    [
        (LlmTimeoutError("Provider LLM tidak merespons."), "merespons"),
        (LlmProviderError("Provider LLM gagal."), "gagal"),
    ],
)
def test_provider_errors_mark_job_failed_without_items(
    s2_db, s2_client, monkeypatch, error, expected_word
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider(action_error=error))

    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == []
    assert expected_word in detail["error"]


def test_openai_provider_sends_action_items_strict_schema(s2_client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import settings

    seen: list[dict] = []

    def fake_post(url, **kwargs):
        seen.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json=_openai_output({"action_items": []}),
        )

    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("sk-rahasia"))
    monkeypatch.setattr(settings, "LLM_API_BASE_URL", "https://llm.test/v1")
    monkeypatch.setattr("app.services.llm.openai_provider.httpx.post", fake_post)

    data = ActionItemInput(
        "Rapat Uji",
        [],
        available_speaker_labels=("Speaker 1",),
    )
    result = OpenAiLlmProvider().extract_action_items(data)

    assert seen[0]["url"] == "https://llm.test/v1/responses"
    assert seen[0]["headers"]["Authorization"] == "Bearer sk-rahasia"
    text_format = seen[0]["json"]["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["name"] == "action_items"
    assert text_format["schema"] == ACTION_ITEMS_JSON_SCHEMA
    assert "Speaker 1" in seen[0]["json"]["input"][1]["content"]
    assert result.items == []
    assert result.provider == "openai"

    schema_text = json.dumps(ACTION_ITEMS_JSON_SCHEMA).lower()
    assert "assignee" in schema_text
    assert "deadline" in schema_text
    assert "additionalproperties" in schema_text


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------


def _one_item(s2_client, monkeypatch) -> tuple[str, dict]:
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())
    assert _generate(s2_client, meeting_id).status_code == 202
    return meeting_id, _items(s2_client, meeting_id)["items"][0]


def _patch(s2_client, meeting_id: str, item_id: str, body: dict):
    return s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/action-items/{item_id}", json=body
    )


def test_edit_title(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    response = _patch(s2_client, meeting_id, item["id"], {"title": "Judul baru"})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Judul baru"
    assert response.json()["is_manually_edited"] is True


def test_edit_description(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    response = _patch(s2_client, meeting_id, item["id"], {"description": "Rincian baru"})
    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Rincian baru"


def test_edit_assignee_speaker(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _diarize(s2_client, monkeypatch, meeting_id)
    _inject_llm(monkeypatch, MockLlmProvider())
    assert _generate(s2_client, meeting_id).status_code == 202
    item = _items(s2_client, meeting_id)["items"][0]
    speaker = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["speakers"][0]

    response = _patch(
        s2_client, meeting_id, item["id"], {"assignee_speaker_id": speaker["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["assignee_speaker_id"] == speaker["id"]


def test_edit_assignee_and_deadline(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    response = _patch(
        s2_client,
        meeting_id,
        item["id"],
        {
            "assignee_text": "Tim jaringan",
            "deadline_text": "hari Jumat",
            "due_date": "2026-11-27",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignee_text"] == "Tim jaringan"
    assert body["deadline_text"] == "hari Jumat"
    assert body["due_date"] == "2026-11-27"


def test_edit_can_clear_assignee_and_due_date(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    _patch(
        s2_client,
        meeting_id,
        item["id"],
        {"assignee_text": "Ani", "due_date": "2026-11-27"},
    )
    response = _patch(
        s2_client,
        meeting_id,
        item["id"],
        {"assignee_text": None, "due_date": None},
    )
    assert response.status_code == 200, response.text
    assert response.json()["assignee_text"] is None
    assert response.json()["due_date"] is None


@pytest.mark.parametrize("new_status", ["COMPLETED", "CANCELLED", "OPEN"])
def test_status_changes(s2_client, monkeypatch, new_status):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    response = _patch(s2_client, meeting_id, item["id"], {"status": new_status})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == new_status
    assert response.json()["is_manually_edited"] is True


def test_invalid_status_is_rejected(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    response = _patch(s2_client, meeting_id, item["id"], {"status": "SOMEDAY"})
    assert response.status_code == 422


def test_unknown_patch_field_is_rejected(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    response = _patch(s2_client, meeting_id, item["id"], {"assignee_email": "a@b.test"})
    assert response.status_code == 422


def test_cross_meeting_speaker_is_rejected(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    other_id = _transcribed_meeting(s2_client, monkeypatch)
    _diarize(s2_client, monkeypatch, other_id)
    speaker = s2_client.get(f"/api/v1/meetings/{other_id}/diarization").json()["speakers"][0]

    response = _patch(
        s2_client, meeting_id, item["id"], {"assignee_speaker_id": speaker["id"]}
    )
    assert response.status_code == 422
    assert "meeting" in response.json()["detail"].lower()


def test_cross_meeting_item_is_rejected(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    other_id = _transcribed_meeting(s2_client, monkeypatch)

    patch_response = _patch(s2_client, other_id, item["id"], {"title": "Tips"})
    delete_response = s2_client.delete(
        f"/api/v1/meetings/{other_id}/action-items/{item['id']}"
    )
    assert patch_response.status_code == 404
    assert delete_response.status_code == 404
    assert _items(s2_client, meeting_id)["items"][0]["id"] == item["id"]


def test_delete_single_item(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [
                    _extracted(segments, title="Satu"),
                    _extracted(segments, title="Dua", segment_ids=(segments[1]["id"],),
                               start_seconds=segments[1]["start_seconds"],
                               end_seconds=segments[1]["end_seconds"]),
                ]
            )
        ),
    )
    assert _generate(s2_client, meeting_id).status_code == 202
    items = _items(s2_client, meeting_id)["items"]
    assert len(items) == 2

    response = s2_client.delete(
        f"/api/v1/meetings/{meeting_id}/action-items/{items[0]['id']}"
    )
    assert response.status_code == 200, response.text
    remaining = _items(s2_client, meeting_id)["items"]
    assert [item["title"] for item in remaining] == ["Dua"]


def test_delete_all_action_items(s2_client, monkeypatch):
    meeting_id, _ = _one_item(s2_client, monkeypatch)
    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/action-items")
    assert response.status_code == 200, response.text
    assert response.json()["items_deleted"] == 1
    assert response.json()["sources_deleted"] == 3
    detail = _items(s2_client, meeting_id)
    assert detail["items"] == []
    assert detail["status"] == "NOT_STARTED"


def test_manual_changes_survive_refresh(s2_client, monkeypatch):
    meeting_id, item = _one_item(s2_client, monkeypatch)
    _patch(s2_client, meeting_id, item["id"], {"title": "Tersimpan", "status": "COMPLETED"})

    refreshed = _items(s2_client, meeting_id)["items"][0]
    assert refreshed["title"] == "Tersimpan"
    assert refreshed["status"] == "COMPLETED"
    assert refreshed["is_manually_edited"] is True


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def test_generate_without_transcript_is_conflict(s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)
    response = _generate(s2_client, meeting_id)
    assert response.status_code == 409
    assert "Transkrip" in response.json()["detail"]


def test_stt_in_progress_is_conflict(s2_db: Session, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    job = s2_db.query(TranscriptionJob).filter(
        TranscriptionJob.meeting_id == meeting_id
    ).first()
    job.status = TranscriptionStatus.PROCESSING
    s2_db.commit()

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 409
    assert "Transkripsi" in response.json()["detail"]


def test_diarization_in_progress_is_conflict(s2_db: Session, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    s2_db.add(
        DiarizationJob(
            meeting_id=meeting_id, status=DiarizationStatus.PROCESSING
        )
    )
    s2_db.commit()

    response = _generate(s2_client, meeting_id)
    assert response.status_code == 409
    assert "Diarisasi" in response.json()["detail"]


def test_duplicate_job_and_delete_conflict(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    # Task sengaja tidak dijalankan supaya job tetap PROCESSING.
    monkeypatch.setattr(action_items_api, "run_action_items", lambda meeting_id: None)
    _inject_llm(monkeypatch, MockLlmProvider())

    assert _generate(s2_client, meeting_id).status_code == 202
    duplicate = _generate(s2_client, meeting_id)
    assert duplicate.status_code == 409
    delete_all = s2_client.delete(f"/api/v1/meetings/{meeting_id}/action-items")
    assert delete_all.status_code == 409


def test_recovery_marks_stuck_job_failed(s2_db: Session, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    s2_db.add(
        ActionItemJob(
            meeting_id=meeting_id, status=ActionExtractionStatus.PROCESSING
        )
    )
    s2_db.commit()

    assert action_service.recover_stuck_action_items() == 1
    s2_db.expire_all()
    job = s2_db.query(ActionItemJob).filter(
        ActionItemJob.meeting_id == meeting_id
    ).first()
    assert job.status == ActionExtractionStatus.FAILED
    assert "dimulai ulang" in job.error


def test_regeneration_replaces_ai_items_but_keeps_manual_edits(
    s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch, MockLlmProvider())
    assert _generate(s2_client, meeting_id).status_code == 202
    original = _items(s2_client, meeting_id)["items"][0]
    _patch(s2_client, meeting_id, original["id"], {"title": "Edit pengguna"})

    segments = _segments(s2_client, meeting_id)
    _inject_llm(
        monkeypatch,
        MockLlmProvider(
            action_result=_result(
                [
                    _extracted(segments, title="Baru A"),
                    _extracted(
                        segments,
                        title="Baru B",
                        segment_ids=(segments[1]["id"],),
                        start_seconds=segments[1]["start_seconds"],
                        end_seconds=segments[1]["end_seconds"],
                    ),
                ]
            )
        ),
    )
    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "COMPLETED"

    by_title = {item["title"]: item for item in detail["items"]}
    assert set(by_title) == {"Edit pengguna", "Baru A", "Baru B"}
    assert by_title["Edit pengguna"]["id"] == original["id"]
    assert by_title["Edit pengguna"]["is_manually_edited"] is True


def test_failed_regeneration_keeps_old_items(s2_client, monkeypatch):
    meeting_id, original = _one_item(s2_client, monkeypatch)

    _inject_llm(monkeypatch, MockLlmProvider(action_error=LlmProviderError("Gagal cloud")))
    assert _generate(s2_client, meeting_id).status_code == 202
    detail = _items(s2_client, meeting_id)
    assert detail["status"] == "FAILED"
    assert detail["items"] == [original]


def test_deleting_transcript_clears_action_items(s2_client, monkeypatch):
    meeting_id, _ = _one_item(s2_client, monkeypatch)
    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 200, response.text

    detail = _items(s2_client, meeting_id)
    assert detail["items"] == []
    assert detail["status"] == "NOT_STARTED"


# ---------------------------------------------------------------------------
# Regression Sprint 1–7 + skema aditif
# ---------------------------------------------------------------------------


def test_summary_and_action_items_can_coexist(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr(
        "app.services.summary.workflow._create_provider",
        lambda *args, **kwargs: MockLlmProvider(),
    )
    _inject_llm(monkeypatch, MockLlmProvider())

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    assert _generate(s2_client, meeting_id).status_code == 202

    summary = s2_client.get(f"/api/v1/meetings/{meeting_id}/summary").json()
    assert summary["status"] == SummaryStatus.COMPLETED
    assert summary["topics"]
    assert len(_items(s2_client, meeting_id)["items"]) == 1

    assert s2_client.delete(f"/api/v1/meetings/{meeting_id}/action-items").status_code == 200
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/summary").json()["topics"] == summary["topics"]


def test_additive_schema_keeps_old_tables(s2_db: Session):
    tables = set(inspect(s2_db.get_bind()).get_table_names())
    for table in (
        "meetings",
        "audio_assets",
        "transcript_segments",
        "transcription_jobs",
        "speakers",
        "diarization_jobs",
        "meeting_summaries",
        "summary_jobs",
        "action_items",
        "action_item_sources",
        "action_item_jobs",
    ):
        assert table in tables

    summary_columns = {
        column["name"] for column in inspect(s2_db.get_bind()).get_columns("meeting_summaries")
    }
    assert "action_items" not in summary_columns
    assert "assignee" not in summary_columns
    assert "deadline" not in summary_columns
