"""Pengujian Sprint 2 — rekaman langsung via MediaRecorder (mulipart).

Semua test memakai database dan folder storage khusus test (lihat conftest).
"""

import uuid

from app.core.storage import storage_root

AUDIO_CONTENT = b"fake-opus-payload-from-mediarecorder"


def _create_meeting(client, title: str = "Rapat Uji Rekaman") -> str:
    """Buat meeting lalu kembalikan id(string)-nya."""
    response = client.post("/api/v1/meetings", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client, meeting_id: str, *, filename="recording.webm", content_type="audio/webm",
            content: bytes = AUDIO_CONTENT, duration: str = "1.5"):
    """Helper upload multipart."""
    return client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": (filename, content, content_type)},
        data={"duration_seconds": duration},
    )


# ---------------------------------------------------------------------------
# 1. Membuat meeting
# ---------------------------------------------------------------------------


def test_create_meeting(s2_db, s2_client):
    """POST /meetings harus membuat UUID dan status awal PENDING."""
    response = s2_client.post("/api/v1/meetings", json={"title": "Rapat Sprint 2"})

    assert response.status_code == 201
    data = response.json()
    assert isinstance(uuid.UUID(data["id"]), uuid.UUID)
    assert data["title"] == "Rapat Sprint 2"
    assert data["status"] == "PENDING"
    assert data["has_recording"] is False
    assert data["recording"] is None

    listing = s2_client.get("/api/v1/meetings")
    assert listing.status_code == 200
    assert any(m["id"] == data["id"] for m in listing.json())


# ---------------------------------------------------------------------------
# 2. Upload rekaman hasil MediaRecorder
# ---------------------------------------------------------------------------


def test_upload_recording(s2_db, s2_client):
    """Upload audio/webm;codecs=opus harus tersimpan dan mengubah status."""
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        content_type="audio/webm;codecs=opus",
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert isinstance(uuid.UUID(data["id"]), uuid.UUID)
    assert data["meeting_id"] == meeting_id
    assert data["mime_type"] == "audio/webm"
    assert data["file_size_bytes"] == len(AUDIO_CONTENT)
    assert data["duration_seconds"] == 1.5
    assert data["playback_url"] == f"/api/v1/meetings/{meeting_id}/recording/play"

    # File benar-benar ada di storage dengan nama hasil generate (bukan nama user).
    stored = storage_root() / "meetings" / meeting_id / data["storage_filename"]
    assert stored.is_file()
    assert stored.read_bytes() == AUDIO_CONTENT
    assert stored.name != "recording.webm"

    # Dashboard melihat status & metadata rekaman.
    meetings = s2_client.get("/api/v1/meetings").json()
    target = next(m for m in meetings if m["id"] == meeting_id)
    assert target["status"] == "UPLOADED"
    assert target["has_recording"] is True
    assert target["recording"]["storage_filename"] == data["storage_filename"]


# ---------------------------------------------------------------------------
# 3. Menolak tipe file yang tidak didukung
# ---------------------------------------------------------------------------


def test_reject_unsupported_content_type(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="catatan.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4",
    )

    assert response.status_code == 415
    assert "tidak didukung" in response.json()["detail"]


def test_reject_unsupported_extension(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="recording.exe",
        content_type="audio/webm",
    )

    assert response.status_code == 400
    assert "Ekstensi" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Menolak ukuran file melebihi batas
# ---------------------------------------------------------------------------


def test_reject_oversized_recording(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    too_large = b"x" * (1024 * 1024 + 1)  # batas test = 1 MB (lihat conftest)

    response = _upload(
        s2_client,
        meeting_id,
        content=too_large,
    )

    assert response.status_code == 413
    assert "melebihi batas" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Meeting tidak ditemukan
# ---------------------------------------------------------------------------


def test_upload_to_missing_meeting(s2_db, s2_client):
    missing_id = str(uuid.uuid4())

    response = _upload(s2_client, missing_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "Meeting tidak ditemukan."


def test_get_recording_for_missing_meeting(s2_db, s2_client):
    response = s2_client.get(f"/api/v1/meetings/{uuid.uuid4()}/recording")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6. Metadata rekaman
# ---------------------------------------------------------------------------


def test_get_recording_metadata(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    uploaded = _upload(s2_client, meeting_id).json()

    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == uploaded["id"]
    assert data["duration_seconds"] == uploaded["duration_seconds"]
    assert data["original_filename"] == "recording.webm"


def test_get_recording_before_upload(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 404
    assert "belum tersedia" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 7. Playback rekaman
# ---------------------------------------------------------------------------


def test_play_recording(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    _upload(s2_client, meeting_id)

    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording/play")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/webm")
    assert response.content == AUDIO_CONTENT


# ---------------------------------------------------------------------------
# 8. Rekaman duplikat
# ---------------------------------------------------------------------------


def test_reject_duplicate_recording(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    first = _upload(s2_client, meeting_id)
    second = _upload(s2_client, meeting_id, filename="recording-lain.webm")

    assert first.status_code == 201
    assert second.status_code == 409
    assert "sudah memiliki rekaman" in second.json()["detail"]

    # File kedua tidak boleh tertulis ke disk.
    files = list((storage_root() / "meetings" / meeting_id).glob("*.part"))
    assert files == []
