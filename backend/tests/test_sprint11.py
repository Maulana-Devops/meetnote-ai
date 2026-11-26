"""Pengujian integrasi Sprint 11 — alur lengkap Sprint 1–10.

Tidak seperti test per-sprint yang memotong alur, file ini menjalankan seluruh
jalan: meeting → audio → playback → transkripsi → diarisasi → koreksi →
ringkasan → action items → edit → ekspor TXT/PDF, lalu memeriksa konsistensi
data dan perilaku retry/recovery. Semua provider adalah mock yang disuntik
lewat seam ``_create_provider``; tidak ada jaringan, kredensial, audio produksi,
database produksi, atau folder ``storage/`` yang disentuh.
"""

import datetime
import io
import uuid

import pytest
from pypdf import PdfReader

from app.models.action_item import ActionItem, ActionItemSource
from app.services.diarization.base import DiarizationTurn
from app.services.diarization.mock import MockDiarizationProvider
from app.services.llm.base import (
    ActionItemExtractionResult,
    ExtractedActionItem,
    SummaryDecision,
    SummaryResult,
    SummaryTopic,
)
from app.services.llm.errors import LlmProviderError
from app.services.llm.mock import MockLlmProvider
from app.services.stt.base import SttSegment
from app.services.stt.mock import MockSttProvider

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


# ---------------------------------------------------------------------------
# Helper alur
# ---------------------------------------------------------------------------


def _meeting_and_audio(client, title: str = "Rapat Integrasi Sprint 11") -> str:
    created = client.post("/api/v1/meetings", json={"title": title})
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]
    assert created.json()["status"] == "PENDING"

    uploaded = client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("rapat.wav", WAV_HEADER, "audio/wav")},
        data={"duration_seconds": "6.0"},
    )
    assert uploaded.status_code == 201, uploaded.text
    return meeting_id


def _inject_stt(monkeypatch, segments: list[SttSegment]) -> None:
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: MockSttProvider(segments=segments),
    )


def _segments_for_transcription() -> list[SttSegment]:
    return [
        SttSegment("Halo semua, mulai rapat.", 0.0, 2.0),
        SttSegment("Kita bahas rilis aplikasi.", 2.0, 4.0),
        SttSegment("Terima kasih.", 4.0, 6.0),
    ]


def _inject_diarization(monkeypatch, turns: list[DiarizationTurn] | None = None) -> None:
    turns = turns or [
        DiarizationTurn("0", 0.0, 2.0),
        DiarizationTurn("1", 2.0, 4.0),
        DiarizationTurn("0", 4.0, 6.0),
    ]
    monkeypatch.setattr(
        "app.services.diarization.workflow._create_provider",
        lambda *args, **kwargs: MockDiarizationProvider(turns=turns),
    )


def _inject_summary(monkeypatch, provider: MockLlmProvider) -> None:
    monkeypatch.setattr(
        "app.services.summary.workflow._create_provider",
        lambda *args, **kwargs: provider,
    )


def _inject_action_items(monkeypatch, provider: MockLlmProvider) -> None:
    monkeypatch.setattr(
        "app.services.action_items.workflow._create_provider",
        lambda *args, **kwargs: provider,
    )


def _segments(client, meeting_id: str) -> list[dict]:
    return client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["segments"]


def _speakers(client, meeting_id: str) -> list[dict]:
    return client.get(f"/api/v1/meetings/{meeting_id}/diarization").json()["speakers"]


def _summary(client, meeting_id: str) -> dict:
    return client.get(f"/api/v1/meetings/{meeting_id}/summary").json()


def _items(client, meeting_id: str) -> dict:
    return client.get(f"/api/v1/meetings/{meeting_id}/action-items").json()


def _result_summary(overview: str, segments: list[dict]) -> SummaryResult:
    first = segments[0]
    return SummaryResult(
        overview=overview,
        topics=[
            SummaryTopic(
                title="Topik rilis",
                detail="Rilis dibahas pada awal rapat.",
                segment_ids=(first["id"],),
                start_seconds=first["start_seconds"],
                end_seconds=first["end_seconds"],
            )
        ],
        decisions=[
            SummaryDecision(
                text="Rilis ditunda satu minggu.",
                segment_ids=(first["id"],),
                start_seconds=first["start_seconds"],
                end_seconds=first["end_seconds"],
            )
        ],
        provider="mock",
        model="mock-1",
        is_mock=True,
    )


def _result_action(
    segments: list[dict],
    *,
    title: str = "Kirim laporan rilis",
    label: str | None = None,
) -> ActionItemExtractionResult:
    first = segments[0]
    return ActionItemExtractionResult(
        items=[
            ExtractedActionItem(
                title=title,
                description="Laporan dikirim sebelum rilis.",
                assignee_speaker_label=label,
                assignee_text=None,
                deadline_text="akhir pekan",
                due_date=datetime.date(2026, 12, 31),
                segment_ids=(first["id"],),
                start_seconds=first["start_seconds"],
                end_seconds=first["end_seconds"],
            )
        ],
        provider="mock",
        model="mock-1",
        is_mock=True,
    )


def _prepare_through_diarization(client, monkeypatch, title="Rapat Integrasi") -> str:
    meeting_id = _meeting_and_audio(client, title)
    _inject_stt(monkeypatch, _segments_for_transcription())
    assert client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    _inject_diarization(monkeypatch)
    assert client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    return meeting_id


def _txt(client, meeting_id: str) -> str:
    response = client.get(f"/api/v1/meetings/{meeting_id}/export/txt")
    assert response.status_code == 200, response.text
    return response.text


def _pdf_text(client, meeting_id: str) -> tuple[str, bytes]:
    response = client.get(f"/api/v1/meetings/{meeting_id}/export/pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, response.content


# ---------------------------------------------------------------------------
# 1. Alur lengkap 16 langkah + konsistensi ekspor
# ---------------------------------------------------------------------------


def test_e2e_full_pipeline_and_export_consistency(s2_client, monkeypatch):
    # 1–3. Buat meeting, unggah audio, lalu putar lewat endpoint playback.
    meeting_id = _meeting_and_audio(s2_client, "Rapat Integrasi Penuh é")
    playback = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording/play")
    assert playback.status_code == 200
    assert playback.content == WAV_HEADER

    # 4. Transkripsi: urutan segmen dan timestamp dari provider.
    _inject_stt(monkeypatch, _segments_for_transcription())
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert transcript["status"] == "COMPLETED"
    assert [s["sequence"] for s in transcript["segments"]] == [1, 2, 3]
    assert [
        (s["start_seconds"], s["end_seconds"]) for s in transcript["segments"]
    ] == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    assert transcript["full_text"].startswith("[MOCK] Halo semua")

    # 5. Diarisasi: label anonim + assignment segmen.
    _inject_diarization(monkeypatch)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/diarization").status_code == 202
    speakers = _speakers(s2_client, meeting_id)
    assert [s["speaker_label"] for s in speakers] == ["Speaker 1", "Speaker 2"]
    mapped = _segments(s2_client, meeting_id)
    assert [s["speaker_label"] for s in mapped] == [
        "Speaker 1",
        "Speaker 2",
        "Speaker 1",
    ]

    # 6. Edit teks: timestamp dan speaker tidak berubah.
    first_id = mapped[0]["id"]
    edited = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/transcript/{first_id}",
        json={"text": "Teks hasil suntingan pengguna."},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["text"] == "Teks hasil suntingan pengguna."
    assert edited.json()["speaker_id"] == mapped[0]["speaker_id"]
    assert edited.json()["start_seconds"] == 0.0

    # 7. Ubah nama tampilan speaker.
    renamed = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/speakers/{speakers[0]['id']}",
        json={"display_name": "Rani"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["display_name"] == "Rani"

    # 8. Ubah assignment speaker segmen kedua.
    reassigned = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/transcript/{mapped[1]['id']}/speaker",
        json={"speaker_id": speakers[0]["id"]},
    )
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["speaker_display_name"] == "Rani"

    # 9–10. Ringkasan: overview/topics/decisions + referensi segmen nyata.
    _inject_summary(
        monkeypatch,
        MockLlmProvider(result=_result_summary("Ringkasan terverifikasi Sprint 11.", mapped)),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    summary = _summary(s2_client, meeting_id)
    assert summary["status"] == "COMPLETED"
    assert summary["overview"] == "Ringkasan terverifikasi Sprint 11."
    assert summary["topics"][0]["segment_ids"] == [first_id]
    assert summary["decisions"][0]["text"] == "Rilis ditunda satu minggu."

    # 11–12. Action items + suntingan/status pengguna.
    _inject_action_items(
        monkeypatch,
        MockLlmProvider(
            action_result=_result_action(mapped, label=renamed.json()["display_name"])
        ),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items").status_code == 202
    generated = _items(s2_client, meeting_id)
    assert generated["status"] == "COMPLETED"
    item = generated["items"][0]
    assert item["assignee_speaker_id"] == speakers[0]["id"]
    assert item["segment_ids"] == [first_id]
    assert (item["start_seconds"], item["end_seconds"]) == (0.0, 2.0)

    edited_item = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/action-items/{item['id']}",
        json={"title": "Tindak lanjut terverifikasi"},
    )
    assert edited_item.status_code == 200, edited_item.text
    assert edited_item.json()["is_manually_edited"] is True
    done_item = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/action-items/{item['id']}",
        json={"status": "COMPLETED"},
    )
    assert done_item.status_code == 200, done_item.text
    assert done_item.json()["status"] == "COMPLETED"

    # Semua job final tanpa error palsu.
    for path in ("transcription", "diarization", "summary", "action-items"):
        assert s2_client.get(f"/api/v1/meetings/{meeting_id}/{path}").json()["status"] == "COMPLETED"

    # 14–16. Ekspor TXT: memuat hasil edit, bukan data mentah provider.
    text = _txt(s2_client, meeting_id)
    for expected in (
        "Teks hasil suntingan pengguna.",
        "Rani",
        "Ringkasan terverifikasi Sprint 11.",
        "Rilis ditunda satu minggu.",
        "Tindak lanjut terverifikasi",
        "COMPLETED",
        "2026-12-31",
        "0:00",
        "0:02",
        "0:04",
    ):
        assert expected in text, expected
    # Urutan transkrip mengikuti sequence, bukan urutan penyisipan provider.
    assert text.index("Teks hasil suntingan pengguna.") < text.index(
        "Kita bahas rilis aplikasi."
    )

    # Ekspor PDF valid, teks terekstrak, lampiran transkrip hadir.
    pdf_text, pdf_bytes = _pdf_text(s2_client, meeting_id)
    assert pdf_bytes.startswith(b"%PDF")
    assert "LAMPIRAN - TRANSKRIP" in pdf_text
    assert "ACTION ITEMS" in pdf_text
    assert "Tindak lanjut terverifikasi" in pdf_text
    assert "Halaman" in pdf_text


# ---------------------------------------------------------------------------
# 2. Retry/regenerasi: konsistensi setelah hasil lama diganti
# ---------------------------------------------------------------------------


def test_e2e_regeneration_preserves_manual_edits_and_export(s2_client, monkeypatch):
    meeting_id = _prepare_through_diarization(s2_client, monkeypatch, "Rapat Retry")
    segments = _segments(s2_client, meeting_id)

    _inject_summary(
        monkeypatch, MockLlmProvider(result=_result_summary("Ringkasan versi pertama.", segments))
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    _inject_action_items(monkeypatch, MockLlmProvider())
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items").status_code == 202

    original = _items(s2_client, meeting_id)["items"][0]
    manual = s2_client.patch(
        f"/api/v1/meetings/{meeting_id}/action-items/{original['id']}",
        json={"title": "Item yang diedit pengguna"},
    )
    assert manual.status_code == 200

    # Regenerasi dengan hasil berbeda: item manual harus tetap utuh.
    _inject_summary(
        monkeypatch, MockLlmProvider(result=_result_summary("Ringkasan versi kedua.", segments))
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    _inject_action_items(
        monkeypatch,
        MockLlmProvider(action_result=_result_action(segments, title="Item AI pengganti")),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items").status_code == 202

    summary = _summary(s2_client, meeting_id)
    assert summary["status"] == "COMPLETED"
    assert summary["overview"] == "Ringkasan versi kedua."
    items = _items(s2_client, meeting_id)
    assert items["status"] == "COMPLETED"
    titles = [item["title"] for item in items["items"]]
    assert "Item yang diedit pengguna" in titles
    assert "Item AI pengganti" in titles
    preserved = next(i for i in items["items"] if i["title"] == "Item yang diedit pengguna")
    assert preserved["id"] == original["id"]

    text = _txt(s2_client, meeting_id)
    assert "Ringkasan versi kedua." in text
    assert "Item yang diedit pengguna" in text
    assert "Item AI pengganti" in text
    assert "Ringkasan versi pertama." not in text


# ---------------------------------------------------------------------------
# 3. Data parsial/gagal: tidak ada hasil palsu COMPLETED
# ---------------------------------------------------------------------------


def test_e2e_failed_summary_exports_safe_snapshot_then_retry(s2_client, monkeypatch):
    meeting_id = _prepare_through_diarization(s2_client, monkeypatch, "Rapat Parsial")
    segments = _segments(s2_client, meeting_id)

    _inject_summary(
        monkeypatch,
        MockLlmProvider(error=LlmProviderError("Gagal sementara (uji).")),
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    failed = _summary(s2_client, meeting_id)
    assert failed["status"] == "FAILED"
    assert failed["overview"] == ""
    # Pesan provider yang aman memang ditampilkan ke UI; kredensial/internal
    # error mentah tidak pernah ikut.
    assert failed["error"] == "Gagal sementara (uji)."

    text = _txt(s2_client, meeting_id)
    assert "RINGKASAN EKSEKUTIF" in text and "Belum tersedia." in text
    assert "Halo semua, mulai rapat." in text
    assert "FAILED" in text
    pdf_text, _ = _pdf_text(s2_client, meeting_id)
    assert "LAMPIRAN - TRANSKRIP" in pdf_text

    # Retry sukses: ekspor berikutnya memuat ringkasan tanpa mengubah transkrip.
    _inject_summary(
        monkeypatch, MockLlmProvider(result=_result_summary("Ringkasan setelah retry.", segments))
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    assert _summary(s2_client, meeting_id)["status"] == "COMPLETED"
    text = _txt(s2_client, meeting_id)
    assert "Ringkasan setelah retry." in text
    assert "Halo semua, mulai rapat." in text


# ---------------------------------------------------------------------------
# 4. Transkripsi ulang: turunan lama dibersihkan, ekspor tidak menggantung
# ---------------------------------------------------------------------------


def test_e2e_retranscription_clears_downstream_export(s2_client, monkeypatch, s2_db):
    meeting_id = _prepare_through_diarization(s2_client, monkeypatch, "Rapat Ulang")
    segments = _segments(s2_client, meeting_id)
    _inject_summary(
        monkeypatch, MockLlmProvider(result=_result_summary("Ringkasan lama.", segments))
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    _inject_action_items(monkeypatch, MockLlmProvider())
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items").status_code == 202
    s2_db.expire_all()
    assert (
        s2_db.query(ActionItemSource)
        .join(ActionItem)
        .filter(ActionItem.meeting_id == meeting_id)
        .count()
        > 0
    )

    # Transkripsi ulang menghasilkan dua segmen baru.
    _inject_stt(
        monkeypatch,
        [
            SttSegment("Transkrip baru satu.", 0.0, 3.0),
            SttSegment("Transkrip baru dua.", 3.0, 6.0),
        ],
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert transcript["status"] == "COMPLETED"
    assert [s["text"] for s in transcript["segments"]] == [
        "[MOCK] Transkrip baru satu.",
        "[MOCK] Transkrip baru dua.",
    ]
    for path in ("diarization", "summary", "action-items"):
        assert s2_client.get(f"/api/v1/meetings/{meeting_id}/{path}").json()["status"] == "NOT_STARTED"
    s2_db.expire_all()
    assert (
        s2_db.query(ActionItemSource)
        .join(ActionItem)
        .filter(ActionItem.meeting_id == meeting_id)
        .count()
        == 0
    )

    text = _txt(s2_client, meeting_id)
    assert "Transkrip baru satu." in text
    assert "Ringkasan lama." not in text
    assert "Kirim laporan rilis" not in text
    assert "Belum tersedia." in text


# ---------------------------------------------------------------------------
# 5. Job aktif: klik berulang, delete, recovery, retry
# ---------------------------------------------------------------------------


def test_e2e_active_job_blocks_repeat_delete_and_recovers(s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client, "Rapat Job Aktif")
    _inject_stt(monkeypatch, _segments_for_transcription())
    # Simulasikan task tertunda agar status tetap PROCESSING.
    monkeypatch.setattr(
        "app.api.v1.transcriptions.run_transcription", lambda meeting_id: None
    )
    first = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert first.status_code == 202
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["status"] == "PROCESSING"

    # Klik kedua/Hapus rekaman ditolak selama job aktif.
    repeat = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert repeat.status_code == 409
    delete = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")
    assert delete.status_code == 409
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200

    # Restart: recovery menandai FAILED secara idempoten, lalu retry sukses.
    from app.services.transcription import recover_stuck_transcriptions

    assert recover_stuck_transcriptions() >= 1
    assert recover_stuck_transcriptions() == 0
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["status"] == "FAILED"

    monkeypatch.undo()
    _inject_stt(monkeypatch, _segments_for_transcription())
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription").status_code == 202
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()["status"] == "COMPLETED"
    assert "Halo semua, mulai rapat." in _txt(s2_client, meeting_id)


# ---------------------------------------------------------------------------
# 6. Storage/DB tetap konsisten setelah alur penuh
# ---------------------------------------------------------------------------


def test_e2e_storage_and_database_consistency(s2_client, monkeypatch, s2_db):
    meeting_id = _prepare_through_diarization(s2_client, monkeypatch, "Rapat Diagnostik")
    segments = _segments(s2_client, meeting_id)
    _inject_summary(
        monkeypatch, MockLlmProvider(result=_result_summary("Ringkasan diagnostik.", segments))
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    _inject_action_items(monkeypatch, MockLlmProvider())
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items").status_code == 202

    # Hitungan sebelum ekspor dipakai sebagai baseline read-only check.
    s2_db.expire_all()
    sources_query = (
        s2_db.query(ActionItemSource)
        .join(ActionItem)
        .filter(ActionItem.meeting_id == meeting_id)
    )
    sources_before = sources_query.count()
    assert sources_before > 0

    _txt(s2_client, meeting_id)
    _pdf_text(s2_client, meeting_id)

    diagnostics = s2_client.get("/api/v1/health/diagnostics")
    assert diagnostics.status_code == 200
    data = diagnostics.json()
    assert data["sqlite_foreign_keys"] == 1
    storage = data["storage"]
    # Fixture test lain dapat menyisakan metadata dari meeting sebelumnya;
    # yang penting alur saat ini tidak menyisakan anomali.
    anomalies = (
        storage["orphan_files"]
        + storage["temp_files"]
        + storage["trash_files"]
        + storage["metadata_without_file"]
    )
    assert all(meeting_id not in path for path in anomalies), anomalies
    assert storage["invalid_metadata_paths"] == 0

    # Export tidak mengubah jumlah baris/objek mana pun.
    s2_db.expire_all()
    assert sources_query.count() == sources_before
    assert len(_segments(s2_client, meeting_id)) == 3
    assert len(_speakers(s2_client, meeting_id)) == 2


# ---------------------------------------------------------------------------
# 7. Hardening konfigurasi rilis
# ---------------------------------------------------------------------------


def test_release_config_defaults_are_not_development_only():
    from starlette.middleware.cors import CORSMiddleware

    from app.core.config import Settings, settings
    from app.main import app

    assert Settings.model_fields["DEBUG"].default is False
    assert "localhost:5173" in Settings.model_fields["CORS_ALLOWED_ORIGINS"].default

    cors = [item for item in app.user_middleware if item.cls is CORSMiddleware]
    assert len(cors) == 1
    kwargs = cors[0].kwargs
    expected_origins = [
        origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()
    ]
    assert kwargs["allow_origins"] == expected_origins
    assert "*" not in kwargs["allow_methods"]
    assert set(kwargs["allow_headers"]) == {"Content-Type", "Accept"}
