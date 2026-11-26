"""Pengujian Sprint 6 — edit transkrip & kelola speaker buatan pengguna.

Memakai fixture isolasi `s2_db`/`s2_client` dari conftest. Seluruh STT dan
diarisasi memakai provider mock yang disuntik lewat monkeypatch; tidak ada
panggilan jaringan, database produksi, atau folder `storage/` yang disentuh.
"""

import uuid

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.services.diarization.workflow as diarization_service
import app.services.transcription as transcription_service
from app.database.session import engine
from app.models.diarization import Speaker
from app.models.transcript import TranscriptSegment
from app.services.diarization.base import DiarizationTurn
from app.services.diarization.mock import MockDiarizationProvider
from app.services.stt.base import SttSegment
from app.services.stt.mock import MockSttProvider
from app.services.transcript_editing import (
    MAX_SEGMENT_TEXT_CHARS,
    MAX_SPEAKER_DISPLAY_NAME_CHARS,
)

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _create_meeting_with_audio(client, title: str = "Rapat Edit") -> str:
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


def _segments() -> list[SttSegment]:
    return [
        SttSegment("Halo semua.", 0.0, 2.0),
        SttSegment("Mulai rapat.", 2.0, 4.0),
        SttSegment("Terima kasih.", 4.0, 6.0),
    ]


def _turns() -> list[DiarizationTurn]:
    return [
        DiarizationTurn("0", 0.0, 2.0),
        DiarizationTurn("1", 2.0, 4.0),
        DiarizationTurn("0", 4.0, 6.0),
    ]


def _transcribed_meeting(s2_client, monkeypatch, segments=None) -> str:
    meeting_id = _create_meeting_with_audio(s2_client)
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: MockSttProvider(segments=segments or _segments()),
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 202, response.text
    return meeting_id


def _diarized_meeting(s2_client, monkeypatch) -> str:
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: MockDiarizationProvider(turns=_turns()),
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization")
    assert response.status_code == 202, response.text
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()
    assert detail["status"] == "COMPLETED", detail
    return meeting_id


def _first_segment(s2_client, meeting_id: str) -> dict:
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    return detail["segments"][0]


def _speakers(s2_client, meeting_id: str) -> list[dict]:
    return s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["speakers"]


def _patch_text(client, meeting_id: str, segment_id: str, text: str):
    return client.patch(
        f"/api/v1/meetings/{meeting_id}/transcript/{segment_id}",
        json={"text": text},
    )


def _patch_name(client, meeting_id: str, speaker_id: str, name):
    return client.patch(
        f"/api/v1/meetings/{meeting_id}/speakers/{speaker_id}",
        json={"display_name": name},
    )


def _patch_speaker(client, meeting_id: str, segment_id: str, speaker_id):
    return client.patch(
        f"/api/v1/meetings/{meeting_id}/transcript/{segment_id}/speaker",
        json={"speaker_id": speaker_id},
    )


def _fail_commit(*args, **kwargs):
    raise SQLAlchemyError("database down")


# ---------------------------------------------------------------------------
# Edit teks segmen
# ---------------------------------------------------------------------------


def test_edit_segment_text_changes_only_text(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    before = _first_segment(s2_client, meeting_id)

    response = _patch_text(s2_client, meeting_id, before["id"], "  Teks hasil sunting.  ")

    assert response.status_code == 200, response.text
    after = response.json()
    assert after["text"] == "Teks hasil sunting."
    assert after["id"] == before["id"]
    assert after["meeting_id"] == before["meeting_id"]
    assert after["sequence"] == before["sequence"]
    assert after["start_seconds"] == before["start_seconds"]
    assert after["end_seconds"] == before["end_seconds"]
    assert after["speaker_id"] == before["speaker_id"]
    assert after["speaker_label"] == before["speaker_label"]


def test_segment_edit_persists_and_updates_full_text(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)

    assert _patch_text(s2_client, meeting_id, segment["id"], "Kalimat baru.").status_code == 200

    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert detail["segments"][0]["text"] == "Kalimat baru."
    assert detail["full_text"].startswith("Kalimat baru.\n")
    stored = (
        s2_db.query(TranscriptSegment)
        .filter(TranscriptSegment.id == segment["id"])
        .one()
    )
    assert stored.text == "Kalimat baru."


def test_edit_segment_text_rejects_blank_and_whitespace(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    original = segment["text"]

    for value in ("", "   \n\t  "):
        response = _patch_text(s2_client, meeting_id, segment["id"], value)
        assert response.status_code == 400
        assert "tidak boleh kosong" in response.json()["detail"]

    assert _first_segment(s2_client, meeting_id)["text"] == original


def test_edit_segment_text_rejects_overlong_text(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)

    response = _patch_text(
        s2_client,
        meeting_id,
        segment["id"],
        "a" * (MAX_SEGMENT_TEXT_CHARS + 1),
    )

    assert response.status_code == 400
    assert "terlalu panjang" in response.json()["detail"]
    assert _first_segment(s2_client, meeting_id)["text"] == segment["text"]


def test_edit_segment_text_meeting_not_found(s2_client):
    response = _patch_text(s2_client, str(uuid.uuid4()), str(uuid.uuid4()), "Halo")
    assert response.status_code == 404
    assert "Meeting" in response.json()["detail"]


def test_edit_segment_text_segment_not_found(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)

    response = _patch_text(s2_client, meeting_id, str(uuid.uuid4()), "Halo")

    assert response.status_code == 404
    assert "Segmen" in response.json()["detail"]


def test_edit_segment_text_from_other_meeting_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_a = _transcribed_meeting(s2_client, monkeypatch)
    meeting_b = _transcribed_meeting(s2_client, monkeypatch)
    foreign = _first_segment(s2_client, meeting_b)

    response = _patch_text(s2_client, meeting_a, foreign["id"], "Menyusup")

    assert response.status_code == 404
    assert _first_segment(s2_client, meeting_b)["text"] == foreign["text"]


def test_identical_text_edit_skips_commit(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)

    # Jika implementasi melakukan commit pada data yang tidak berubah, patch
    # ini akan mengubah response menjadi 500 dan test gagal.
    with monkeypatch.context() as mp:
        mp.setattr(Session, "commit", _fail_commit)
        response = _patch_text(s2_client, meeting_id, segment["id"], segment["text"])

    assert response.status_code == 200
    assert response.json()["text"] == segment["text"]


def test_segment_edit_db_failure_returns_generic_500(s2_db, s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)

    with monkeypatch.context() as mp:
        mp.setattr(Session, "commit", _fail_commit)
        response = _patch_text(s2_client, meeting_id, segment["id"], "Gagal disimpan")

    assert response.status_code == 500
    assert response.json()["detail"] == "Gagal menyimpan perubahan teks segmen."
    assert "database down" not in response.text
    assert _first_segment(s2_client, meeting_id)["text"] == segment["text"]


# ---------------------------------------------------------------------------
# Nama tampilan speaker
# ---------------------------------------------------------------------------


def test_speaker_display_name_can_be_set_and_cleared(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    speaker = _speakers(s2_client, meeting_id)[0]

    updated = _patch_name(s2_client, meeting_id, speaker["id"], "  Rani  ")
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Rani"
    assert updated.json()["speaker_label"] == speaker["speaker_label"]

    cleared = _patch_name(s2_client, meeting_id, speaker["id"], None)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["display_name"] is None
    assert cleared.json()["speaker_label"] == speaker["speaker_label"]


def test_segment_response_prefers_display_name_then_label(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    speaker_id = segment["speaker_id"]
    speaker = next(item for item in _speakers(s2_client, meeting_id) if item["id"] == speaker_id)

    assert segment["speaker_display_name"] is None
    assert segment["speaker_label"] == speaker["speaker_label"]

    assert _patch_name(s2_client, meeting_id, speaker_id, "Budi").status_code == 200
    after = _first_segment(s2_client, meeting_id)
    assert after["speaker_display_name"] == "Budi"
    assert after["speaker_label"] == speaker["speaker_label"]

    assert _patch_name(s2_client, meeting_id, speaker_id, None).status_code == 200
    restored = _first_segment(s2_client, meeting_id)
    assert restored["speaker_display_name"] is None
    assert restored["speaker_label"] == speaker["speaker_label"]


def test_speaker_display_name_rejects_blank_and_overlong(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    speaker = _speakers(s2_client, meeting_id)[0]

    blank = _patch_name(s2_client, meeting_id, speaker["id"], "  ")
    assert blank.status_code == 400
    assert "tidak boleh kosong" in blank.json()["detail"]

    long_name = _patch_name(
        s2_client,
        meeting_id,
        speaker["id"],
        "a" * (MAX_SPEAKER_DISPLAY_NAME_CHARS + 1),
    )
    assert long_name.status_code == 400
    assert "terlalu panjang" in long_name.json()["detail"]

    stored = (
        s2_db.query(Speaker).filter(Speaker.id == speaker["id"]).one()
    )
    assert stored.display_name is None


def test_speaker_display_name_unknown_speaker(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)

    response = _patch_name(s2_client, meeting_id, str(uuid.uuid4()), "Hantu")

    assert response.status_code == 404
    assert "Speaker" in response.json()["detail"]


def test_speaker_display_name_from_other_meeting_is_rejected(s2_db, s2_client, monkeypatch):
    meeting_a = _diarized_meeting(s2_client, monkeypatch)
    meeting_b = _diarized_meeting(s2_client, monkeypatch)
    foreign = _speakers(s2_client, meeting_b)[0]

    response = _patch_name(s2_client, meeting_a, foreign["id"], "Menyusup")

    assert response.status_code == 404
    assert _speakers(s2_client, meeting_b)[0]["display_name"] is None


def test_speaker_display_name_preserves_relationships(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    speaker = _speakers(s2_client, meeting_id)[0]
    before = s2_db.query(TranscriptSegment).filter(
        TranscriptSegment.speaker_id == speaker["id"]
    ).count()
    original_text = _first_segment(s2_client, meeting_id)["text"]

    response = _patch_name(s2_client, meeting_id, speaker["id"], "Nama Baru")

    assert response.status_code == 200
    assert response.json()["segment_count"] == speaker["segment_count"] == before
    assert _first_segment(s2_client, meeting_id)["text"] == original_text
    stored = s2_db.query(Speaker).filter(Speaker.id == speaker["id"]).one()
    assert stored.segments
    assert all(item.speaker_id == speaker["id"] for item in stored.segments)


# ---------------------------------------------------------------------------
# Penugasan speaker manual
# ---------------------------------------------------------------------------


def test_manual_assignment_updates_only_speaker_fields(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    speakers = _speakers(s2_client, meeting_id)
    other = next(item for item in speakers if item["id"] != segment["speaker_id"])
    assert _patch_name(s2_client, meeting_id, other["id"], "Sinta").status_code == 200

    response = _patch_speaker(s2_client, meeting_id, segment["id"], other["id"])

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["speaker_id"] == other["id"]
    assert updated["speaker_label"] == other["speaker_label"]
    assert updated["speaker_display_name"] == "Sinta"
    assert updated["text"] == segment["text"]
    assert updated["start_seconds"] == segment["start_seconds"]
    assert updated["end_seconds"] == segment["end_seconds"]
    assert updated["sequence"] == segment["sequence"]
    assert updated["id"] == segment["id"]


def test_manual_assignment_persists_after_refetch(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    other = next(
        item for item in _speakers(s2_client, meeting_id)
        if item["id"] != segment["speaker_id"]
    )

    assert _patch_speaker(s2_client, meeting_id, segment["id"], other["id"]).status_code == 200

    after = _first_segment(s2_client, meeting_id)
    assert after["speaker_id"] == other["id"]
    stored = (
        s2_db.query(TranscriptSegment).filter(TranscriptSegment.id == segment["id"]).one()
    )
    assert stored.speaker_id == other["id"]


def test_manual_assignment_can_unassign_segment(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    assert segment["speaker_id"] is not None

    response = _patch_speaker(s2_client, meeting_id, segment["id"], None)

    assert response.status_code == 200, response.text
    assert response.json()["speaker_id"] is None
    assert response.json()["speaker_label"] is None
    assert response.json()["speaker_display_name"] is None
    assert _first_segment(s2_client, meeting_id)["speaker_id"] is None


def test_manual_assignment_can_assign_previously_unassigned_segment(
    s2_db, s2_client, monkeypatch
):
    # Turn hanya di 5–6 detik: segmen 0–2 dan 2–4 sengaja tanpa speaker.
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: MockDiarizationProvider(
            turns=[DiarizationTurn("0", 5.0, 6.0)]
        ),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    segment = _first_segment(s2_client, meeting_id)
    assert segment["speaker_id"] is None
    speaker = _speakers(s2_client, meeting_id)[0]

    response = _patch_speaker(s2_client, meeting_id, segment["id"], speaker["id"])

    assert response.status_code == 200, response.text
    assert response.json()["speaker_id"] == speaker["id"]


def test_manual_assignment_rejects_unknown_speaker(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)

    response = _patch_speaker(s2_client, meeting_id, segment["id"], str(uuid.uuid4()))

    assert response.status_code == 404
    assert _first_segment(s2_client, meeting_id)["speaker_id"] == segment["speaker_id"]


def test_manual_assignment_rejects_speaker_from_other_meeting(
    s2_db, s2_client, monkeypatch
):
    meeting_a = _diarized_meeting(s2_client, monkeypatch)
    meeting_b = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_a)
    foreign = _speakers(s2_client, meeting_b)[0]

    response = _patch_speaker(s2_client, meeting_a, segment["id"], foreign["id"])

    assert response.status_code == 404
    assert _first_segment(s2_client, meeting_a)["speaker_id"] == segment["speaker_id"]


def test_manual_assignment_segment_and_meeting_not_found(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    speaker_id = _speakers(s2_client, meeting_id)[0]["id"]

    missing_segment = _patch_speaker(
        s2_client, meeting_id, str(uuid.uuid4()), speaker_id
    )
    missing_meeting = _patch_speaker(
        s2_client, str(uuid.uuid4()), str(uuid.uuid4()), speaker_id
    )

    assert missing_segment.status_code == 404
    assert missing_meeting.status_code == 404


def test_manual_assignment_db_failure_returns_generic_500(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    other = next(
        item for item in _speakers(s2_client, meeting_id)
        if item["id"] != segment["speaker_id"]
    )

    with monkeypatch.context() as mp:
        mp.setattr(Session, "commit", _fail_commit)
        response = _patch_speaker(s2_client, meeting_id, segment["id"], other["id"])

    assert response.status_code == 500
    assert response.json()["detail"] == "Gagal mengubah speaker segmen."
    assert "database down" not in response.text
    assert _first_segment(s2_client, meeting_id)["speaker_id"] == segment["speaker_id"]


# ---------------------------------------------------------------------------
# Job aktif, skema, dan regresi
# ---------------------------------------------------------------------------


def test_edits_are_blocked_while_transcription_is_processing(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    # prepare_transcription() membersihkan hasil lama, jadi simpan ID dulu.
    speaker_id = _speakers(s2_client, meeting_id)[0]["id"]
    monkeypatch.setattr("app.api.v1.transcriptions.run_transcription", lambda _: None)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202

    text = _patch_text(s2_client, meeting_id, str(uuid.uuid4()), "Halo")
    name = _patch_name(s2_client, meeting_id, speaker_id, "Budi")
    assignment = _patch_speaker(s2_client, meeting_id, str(uuid.uuid4()), speaker_id)

    assert [item.status_code for item in (text, name, assignment)] == [409, 409, 409]
    assert "sedang berjalan" in text.json()["detail"]


def test_edits_are_blocked_while_diarization_is_processing(
    s2_db, s2_client, monkeypatch
):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    # prepare_diarization() juga membersihkan speaker lama sebelum job baru.
    segment = _first_segment(s2_client, meeting_id)
    speaker_id = _speakers(s2_client, meeting_id)[0]["id"]
    monkeypatch.setattr("app.api.v1.diarizations.run_diarization", lambda _: None)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    text = _patch_text(s2_client, meeting_id, segment["id"], "Halo")
    name = _patch_name(s2_client, meeting_id, speaker_id, "Budi")
    assignment = _patch_speaker(s2_client, meeting_id, segment["id"], speaker_id)

    assert [item.status_code for item in (text, name, assignment)] == [409, 409, 409]


def test_rerunning_diarization_resets_manual_edits(s2_db, s2_client, monkeypatch):
    """Batasan yang didokumentasikan: hasil otomatis baru menimpa koreksi."""
    meeting_id = _diarized_meeting(s2_client, monkeypatch)
    segment = _first_segment(s2_client, meeting_id)
    assert _patch_text(s2_client, meeting_id, segment["id"], "Suntingan manual").status_code == 200
    speaker = _speakers(s2_client, meeting_id)[0]
    assert _patch_name(s2_client, meeting_id, speaker["id"], "Nama Manual").status_code == 200

    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202

    after = _first_segment(s2_client, meeting_id)
    assert after["text"] == "Suntingan manual"  # teks tidak pernah diubah diarisasi
    assert all(item["display_name"] is None for item in _speakers(s2_client, meeting_id))
    # Mapping dibuat ulang dari nol, jadi koreksi speaker manual ikut hilang.
    assert {item["speaker_label"] for item in _speakers(s2_client, meeting_id)} == {
        "Speaker 1",
        "Speaker 2",
    }


def test_sprint5_read_endpoints_unchanged(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)

    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription")
    diarization = s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization")

    assert transcript.status_code == 200
    assert diarization.status_code == 200
    body = transcript.json()
    assert body["status"] == "COMPLETED"
    assert body["segments"][0]["text"].startswith("[MOCK]")
    assert [item["speaker_label"] for item in body["segments"]] == [
        "Speaker 1",
        "Speaker 2",
        "Speaker 1",
    ]
    assert diarization.json()["is_mock"] is True
    assert diarization.json()["mapped_segments"] == 3


def test_delete_transcript_still_keeps_audio(s2_db, s2_client, monkeypatch):
    meeting_id = _diarized_meeting(s2_client, monkeypatch)

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 200
    assert response.json()["segments_deleted"] == 3
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["speakers"] == []


def test_no_new_database_columns_for_sprint6(s2_client):
    """Tidak ada kolom bukti 'manual vs otomatis' yang ditambahkan."""
    inspector = inspect(engine)

    segment_columns = {
        column["name"] for column in inspector.get_columns("transcript_segments")
    }
    speaker_columns = {
        column["name"] for column in inspector.get_columns("speakers")
    }

    assert segment_columns == {
        "id",
        "meeting_id",
        "text",
        "start_seconds",
        "end_seconds",
        "sequence",
        "created_at",
        "speaker_id",
    }
    assert speaker_columns == {
        "id",
        "meeting_id",
        "speaker_label",
        "display_name",
        "created_at",
    }


def test_services_remain_separated(s2_client):
    assert not hasattr(transcription_service, "update_segment_text")
    assert not hasattr(diarization_service, "update_speaker_display_name")
