"""Pengujian Sprint 10 — export notulen TXT dan PDF.

Semua data dibuat langsung di database test yang terisolasi (fixture
``s2_db``/``s2_client``). Tidak ada provider AI, jaringan, audio produksi,
atau file sementara yang dipakai. Parser PDF memakai ``pypdf``.
"""

import datetime
import io
import logging
import uuid
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.core.storage import storage_root
from app.models.action_item import (
    ActionExtractionStatus,
    ActionItem,
    ActionItemJob,
    ActionItemSource,
)
from app.models.audio_asset import AudioAsset
from app.models.diarization import DiarizationJob, DiarizationStatus, Speaker
from app.models.meeting import Meeting, MeetingStatus
from app.models.summary import MeetingSummary, SummaryJob, SummaryStatus
from app.models.transcript import TranscriptSegment, TranscriptionJob, TranscriptionStatus
from app.services.export import _source_ref


# ---------------------------------------------------------------------------
# Helper pembuat data (semua lewat ORM, lalu commit)
# ---------------------------------------------------------------------------


def _meeting(s2_db, title: str = "Rapat Sprint 10") -> Meeting:
    meeting = Meeting(
        title=title,
        status=MeetingStatus.TRANSCRIBED,
        created_at=datetime.datetime(2026, 1, 2, 10, 30, 0),
    )
    s2_db.add(meeting)
    s2_db.commit()
    return meeting


def _recording(s2_db, meeting_id: str, duration: float = 125.0, path: str = "missing.wav") -> None:
    s2_db.add(
        AudioAsset(
            meeting_id=meeting_id,
            original_filename="rapat.wav",
            storage_filename="rapat.wav",
            storage_path=path,
            mime_type="audio/wav",
            file_size_bytes=100,
            duration_seconds=duration,
        )
    )
    s2_db.commit()


def _speaker(s2_db, meeting_id: str, label: str, display: str | None) -> Speaker:
    speaker = Speaker(meeting_id=meeting_id, speaker_label=label, display_name=display)
    s2_db.add(speaker)
    s2_db.commit()
    return speaker


def _segment(
    s2_db,
    meeting_id: str,
    sequence: int,
    text: str,
    start: float,
    end: float,
    speaker: Speaker | None = None,
) -> TranscriptSegment:
    segment = TranscriptSegment(
        meeting_id=meeting_id,
        text=text,
        start_seconds=start,
        end_seconds=end,
        sequence=sequence,
        speaker_id=speaker.id if speaker else None,
    )
    s2_db.add(segment)
    s2_db.commit()
    return segment


def _summary(s2_db, meeting_id: str) -> None:
    s2_db.add(
        MeetingSummary(
            meeting_id=meeting_id,
            overview="Rapat membahas rilis \u00e9dan kualitas.",
            topics=[
                {
                    "title": "Rilis \u00e9",
                    "detail": "Tim menyiapkan rilis akhir \u2014 menit terakhir.",
                    "segment_ids": ["s1"],
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                }
            ],
            decisions=[
                {
                    "text": "Rilis ditunda sampai Jumat.",
                    "segment_ids": ["s2"],
                    "start_seconds": 2.0,
                    "end_seconds": 4.0,
                }
            ],
        )
    )
    s2_db.commit()


def _jobs(s2_db, meeting_id: str) -> None:
    for model, status in (
        (TranscriptionJob, TranscriptionStatus.COMPLETED),
        (DiarizationJob, DiarizationStatus.COMPLETED),
        (SummaryJob, SummaryStatus.COMPLETED),
        (ActionItemJob, ActionExtractionStatus.COMPLETED),
    ):
        s2_db.add(model(meeting_id=meeting_id, status=status))
    s2_db.commit()


def _action_item(s2_db, meeting_id: str, segment: TranscriptSegment, assignee: Speaker) -> None:
    item = ActionItem(
        meeting_id=meeting_id,
        title="Kirim laporan \u00e9",
        description="Laporan dikirim sebelum rilis.",
        assignee_speaker_id=assignee.id,
        due_date=datetime.date(2026, 2, 15),
        deadline_text="sebelum rilis",
        status="OPEN",
        start_seconds=0.0,
        end_seconds=2.0,
        is_manually_edited=True,
    )
    s2_db.add(item)
    s2_db.commit()
    s2_db.add(ActionItemSource(action_item_id=item.id, segment_id=segment.id, sequence=1))
    s2_db.commit()


def _full_meeting(s2_db, title: str = "Rapat Sprint 10") -> str:
    meeting = _meeting(s2_db, title)
    _recording(s2_db, meeting.id)
    first = _speaker(s2_db, meeting.id, "Speaker 1", "Andi")
    second = _speaker(s2_db, meeting.id, "Speaker 2", None)
    # Sengaja disisipkan urut-terbalik untuk menguji ORDER BY sequence.
    later = _segment(s2_db, meeting.id, 3, "Terima kasih.", 4.0, 6.0, first)
    middle = _segment(s2_db, meeting.id, 2, "Rilis ditunda sampai Jumat.", 2.0, 4.0, second)
    earlier = _segment(s2_db, meeting.id, 1, "Halo \u00e9, mulai rapat.", 0.0, 2.0, first)
    assert (later.sequence, middle.sequence, earlier.sequence) == (3, 2, 1)
    _summary(s2_db, meeting.id)
    _action_item(s2_db, meeting.id, earlier, first)
    _jobs(s2_db, meeting.id)
    return str(meeting.id)


def _snapshot(s2_db) -> dict[str, list[tuple]]:
    s2_db.expire_all()
    return {
        "meetings": [(m.id, m.title, m.status) for m in s2_db.query(Meeting).all()],
        "audio": [(a.id, a.storage_path) for a in s2_db.query(AudioAsset).all()],
        "speakers": [(s.id, s.display_name) for s in s2_db.query(Speaker).all()],
        "segments": [(s.id, s.text, s.sequence) for s in s2_db.query(TranscriptSegment).all()],
        "summaries": [(s.id, s.overview) for s in s2_db.query(MeetingSummary).all()],
        "items": [(i.id, i.title, i.status) for i in s2_db.query(ActionItem).all()],
        "sources": [(s.action_item_id, s.segment_id) for s in s2_db.query(ActionItemSource).all()],
    }


def _storage_files() -> set[Path]:
    root = storage_root()
    if not root.is_dir():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


# ---------------------------------------------------------------------------
# Validasi meeting & request
# ---------------------------------------------------------------------------


def test_export_meeting_not_found(s2_client):
    missing = str(uuid.uuid4())
    for extension in ("txt", "pdf"):
        response = s2_client.get(f"/api/v1/meetings/{missing}/export/{extension}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Meeting tidak ditemukan."
        assert "sqlite" not in response.text.lower()
        assert "storage" not in response.text.lower()


def test_export_rejects_invalid_uuid(s2_client):
    response = s2_client.get("/api/v1/meetings/tidak-uuid/export/txt")
    assert response.status_code == 422
    assert response.json()["detail"]


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


def test_txt_contains_all_sections_and_stored_data(s2_db, s2_client):
    meeting_id = _full_meeting(s2_db, "Rapat Rilis \u00e9")
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/txt")
    assert response.status_code == 200, response.text

    text = response.text
    for section in (
        "NOTULEN RAPAT",
        "INFORMASI RAPAT",
        "PEMBICARA",
        "RINGKASAN EKSEKUTIF",
        "TOPIK PEMBAHASAN",
        "KEPUTUSAN",
        "ACTION ITEMS",
        "TRANSKRIP",
    ):
        assert section in text

    assert "Rapat Rilis \u00e9" in text
    assert "2026-01-02 10:30:00" in text
    assert "2:05" in text
    assert "Speaker 1 (Andi)" in text
    assert "Speaker 2" in text
    assert "Rapat membahas rilis \u00e9dan kualitas." in text
    assert "Rilis \u00e9" in text
    assert "Rilis ditunda sampai Jumat." in text
    assert "0:00\u20131:00" not in text  # sumber memakai format m:ss–m:ss dari DB
    assert "0:00\u20130:02" in text
    assert "Kirim laporan \u00e9" in text
    assert "Laporan dikirim sebelum rilis." in text
    assert "2026-02-15 (sebelum rilis)" in text
    assert "[OPEN]" in text
    assert "(diedit manual)" in text

    # Urutan segmen mengikuti `sequence`, bukan urutan insert. Batasi pencarian
    # ke bagian transkrip karena kalimat yang sama juga muncul di keputusan.
    transcript = text.split("TRANSKRIP\n" + "-" * 64 + "\n", 1)[1]
    first = transcript.index("Halo \u00e9, mulai rapat.")
    second = transcript.index("Rilis ditunda sampai Jumat.")
    third = transcript.index("Terima kasih.")
    assert first < second < third
    assert "[0:00 - 0:02] Speaker 1 (Andi): Halo \u00e9, mulai rapat." in text
    # Format waktu adalah m:ss, bukan mm:ss (4 detik = 0:04).
    assert "[0:04 - 0:06] Speaker 1 (Andi): Terima kasih." in text


def test_txt_keeps_audio_provenance_alongside_human_clock(s2_db, s2_client):
    meeting_id = _full_meeting(s2_db, "Rapat Provenance")
    text = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/txt").text

    # Label waktu manusia tidak diganti oleh referensi mesin.
    assert "Sumber: 0:00\u20130:02" in text
    assert "[0:00 - 0:02] Speaker 1 (Andi): Halo \u00e9, mulai rapat." in text
    assert "Sumber: audio#t=" not in text

    for reference in (
        "audio#t=0.000-2.000",
        "audio#t=2.000-4.000",
        "audio#t=4.000-6.000",
    ):
        assert reference in text

    # Topik/segmen memakai 'Referensi audio:', action item memakai spasi
    # perataan yang sama dengan baris 'Sumber' di tabel.
    assert "Referensi audio: audio#t=0.000-2.000" in text
    assert "Referensi audio : audio#t=0.000-2.000" in text
    assert "rapat.wav" not in text  # provenance tidak membocorkan nama file


def test_partial_data_uses_explicit_placeholders(s2_db, s2_client):
    meeting = _meeting(s2_db, "Rapat Kosong")
    response = s2_client.get(f"/api/v1/meetings/{meeting.id}/export/txt")
    assert response.status_code == 200
    text = response.text
    assert text.count("Belum tersedia.") >= 7
    assert "Status transkripsi   : NOT_STARTED" in text
    assert "Status ringkasan     : NOT_STARTED" in text
    assert "Status action items  : NOT_STARTED" in text
    assert "Rapat Kosong" in text


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_is_valid_and_text_is_extractable(s2_db, s2_client):
    meeting_id = _full_meeting(s2_db, "Rapat PDF \u00e9")
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content

    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) >= 2
    assert "Notulen - Rapat PDF" in (reader.metadata.title or "")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    for expected in (
        "Rapat PDF \u00e9",
        "2026-01-02 10:30:00",
        "Speaker 1 (Andi)",
        "Rapat membahas rilis \u00e9dan kualitas.",
        "Kirim laporan \u00e9",
        # Pada tabel PDF, deadline terbuat dua baris diagonal.
        "2026-02-15",
        "(sebelum rilis)",
        "LAMPIRAN - TRANSKRIP",
        "Halo \u00e9, mulai rapat.",
        "Halaman 1",
        "Halaman 2",
    ):
        assert expected in text, expected

    # Tanda hubung panjang dari data diubah ke ASCII agar font tetap mendukung.
    assert "\u2014" not in text
    assert "menit terakhir" in text


def test_pdf_keeps_audio_provenance_alongside_human_clock(s2_db, s2_client):
    meeting_id = _full_meeting(s2_db, "Rapat Provenance PDF")
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/pdf")
    assert response.status_code == 200

    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Provenance: audio#t=<mulai>-<akhir>" in text
    for reference in (
        "audio#t=0.000-2.000",
        "audio#t=2.000-4.000",
        "audio#t=4.000-6.000",
    ):
        assert reference in text, reference

    # Label waktu manusia tetap terbaca di ringkasan dan lampiran transkrip.
    assert "0:00-0:02" in text
    assert "[0:00 - 0:02]" in text
    assert "Halo \u00e9, mulai rapat." in text
    assert "rapat.wav" not in text


def test_pdf_escapes_xml_only_for_paragraphs(s2_db, s2_client):
    meeting_id = _full_meeting(s2_db, "Rapat A & B")
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/pdf")
    assert response.status_code == 200

    reader = PdfReader(io.BytesIO(response.content))
    assert "Notulen - Rapat A & B" == (reader.metadata.title or "")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Rapat A & B" in text
    assert "&amp;" not in text


# ---------------------------------------------------------------------------
# Nama file, header, keamanan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("extension,media_type", [("txt", "text/plain; charset=utf-8"), ("pdf", "application/pdf")])
def test_content_type_and_filename_are_safe(s2_db, s2_client, extension, media_type):
    title = '  ../../Rapat "Aneh"? \u2014 \u00e9  '
    meeting_id = _full_meeting(s2_db, title)
    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/{extension}")
    assert response.status_code == 200
    assert response.headers["content-type"] == media_type

    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="')
    filename = disposition.split('filename="', 1)[1].rstrip('"')
    assert filename.startswith("notulen-") and filename.endswith(f".{extension}")
    assert "/" not in filename and "\\" not in filename
    assert ".." not in filename and '"' not in filename
    assert all(ord(character) < 128 for character in filename)


def test_unicode_is_preserved_in_txt(s2_db, s2_client):
    meeting_id = _full_meeting(s2_db, "Rapat \u00e9\u00e8\u00ea \u2014 terakhir")
    text = s2_client.get(f"/api/v1/meetings/{meeting_id}/export/txt").text
    assert "Rapat \u00e9\u00e8\u00ea \u2014 terakhir" in text
    assert "Tim menyiapkan rilis akhir \u2014 menit terakhir." in text


def test_export_does_not_need_audio_file(s2_db, s2_client):
    meeting = _meeting(s2_db, "Tanpa File Audio")
    _recording(s2_db, meeting.id, path="meetings/tidak-ada/recording.wav")
    # Path sengaja tidak dibuat; export tetap harus sukses.
    response = s2_client.get(f"/api/v1/meetings/{meeting.id}/export/pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_export_failure_is_generic_and_does_not_leak(s2_db, s2_client, monkeypatch, caplog):
    meeting = _meeting(s2_db, "Rapat Error")

    def boom(*args, **kwargs):
        raise RuntimeError("rahasia / C:\\internal\\path")

    monkeypatch.setattr("app.api.v1.export.render_txt", boom)
    with caplog.at_level(logging.ERROR, logger="meetnote.export"):
        response = s2_client.get(f"/api/v1/meetings/{meeting.id}/export/txt")

    assert response.status_code == 500
    assert response.json()["detail"] == "Gagal membuat dokumen export."
    assert "rahasia" not in response.text
    assert "C:\\internal" not in response.text
    assert "rahasia" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_export_is_read_only_and_leaves_no_temp_files(s2_db, s2_client, monkeypatch):
    meeting_id = _full_meeting(s2_db, "Rapat Read Only")
    before_db = _snapshot(s2_db)
    before_files = _storage_files()

    for extension in ("txt", "pdf"):
        assert s2_client.get(f"/api/v1/meetings/{meeting_id}/export/{extension}").status_code == 200

    assert _snapshot(s2_db) == before_db
    assert _storage_files() == before_files


def test_source_ref_helpers_tolak_waktu_tidak_valid():
    assert _source_ref(None, 2.0) == ""
    assert _source_ref("bukan-angka", 2.0) == ""
    assert _source_ref(-1.0, 2.0) == ""
    assert _source_ref(float("nan"), 2.0) == ""
    assert _source_ref(float("inf"), 2.0) == ""
    assert _source_ref(0.5, 2.25) == "audio#t=0.500-2.250"
    assert _source_ref(3.0, 2.0) == "audio#t=3.000-3.000"
