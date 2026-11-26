"""Pengujian Sprint 3 — upload file lokal & pengelolaan rekaman."""

import uuid
from pathlib import Path

from app.core.storage import storage_root
from app.models.audio_asset import AudioAsset

BACKEND_DIR = Path(__file__).resolve().parents[1]

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20
WEBM_HEADER = b"\x1a\x45\xdf\xa3" + b"\x9f\x42\x86\x81\x01\x42\xf7\x81\x01"
MP3_HEADER = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 16


def _create_meeting(client, title: str = "Rapat Upload") -> str:
    response = client.post("/api/v1/meetings", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client, meeting_id, *, filename="rapat.webm", content_type="audio/webm",
            content: bytes = WEBM_HEADER, duration="2.0"):
    return client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": (filename, content, content_type)},
        data={"duration_seconds": duration},
    )


# ---------------------------------------------------------------------------
# Upload format lokal
# ---------------------------------------------------------------------------


def test_upload_webm_with_signature(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(s2_client, meeting_id)

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["mime_type"] == "audio/webm"
    assert data["storage_filename"].endswith(".webm")
    assert data["duration_seconds"] == 2.0


def test_upload_wav_with_signature(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="rapat.wav",
        content_type="audio/wav",
        content=WAV_HEADER,
    )

    assert response.status_code == 201, response.text
    assert response.json()["storage_filename"].endswith(".wav")


def test_upload_mp3_with_signature(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="rapat.mp3",
        content_type="audio/mpeg",
        content=MP3_HEADER,
    )

    assert response.status_code == 201, response.text
    assert response.json()["mime_type"] == "audio/mpeg"
    assert response.json()["storage_filename"].endswith(".mp3")


def test_upload_mp4_extension_is_accepted(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="rapat.mp4",
        content_type="audio/mp4",
        content=b"\x00\x00\x00\x18ftypM4A mp42isom" + b"\x00" * 16,
    )

    assert response.status_code == 201, response.text
    # Ekstensi asli .mp4 diterima, tetapi nama internal tetap aman .m4a.
    assert response.json()["storage_filename"].endswith(".m4a")


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------


def test_reject_unsupported_mime_type(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="rapat.flac",
        content_type="audio/flac",
        content=b"fLaC",
    )

    assert response.status_code == 415
    assert "tidak didukung" in response.json()["detail"]


def test_reject_unsupported_extension(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(
        s2_client,
        meeting_id,
        filename="rapat.flac",
        content_type="audio/webm",
        content=WEBM_HEADER,
    )

    assert response.status_code == 400
    assert "Ekstensi" in response.json()["detail"]


def test_reject_signature_mismatch(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    # Isi WAV, tetapi MIME dikirim sebagai webm.
    response = _upload(
        s2_client,
        meeting_id,
        filename="rapat.webm",
        content_type="audio/webm",
        content=WAV_HEADER,
    )

    assert response.status_code == 415
    assert "terdeteksi" in response.json()["detail"]


def test_reject_oversized_file(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = _upload(s2_client, meeting_id, content=b"x" * (1024 * 1024 + 1))

    assert response.status_code == 413


def test_reject_upload_to_missing_meeting(s2_db, s2_client):
    response = _upload(s2_client, str(uuid.uuid4()))
    assert response.status_code == 404


def test_config_endpoint_matches_backend_limit(s2_client):
    response = s2_client.get("/api/v1/config")

    assert response.status_code == 200
    data = response.json()
    assert data["max_audio_file_bytes"] == 1048576
    assert ".mp4" in data["allowed_extensions"]


# ---------------------------------------------------------------------------
# Metadata & playback
# ---------------------------------------------------------------------------


def test_get_metadata_after_upload(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    uploaded = _upload(s2_client, meeting_id).json()

    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 200
    assert response.json()["id"] == uploaded["id"]


def test_playback_after_upload(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    _upload(s2_client, meeting_id)

    response = s2_client.get(f"/api/v1/meetings/{meeting_id}/recording/play")

    assert response.status_code == 200
    assert response.content == WEBM_HEADER
    assert response.headers["content-type"].startswith("audio/webm")


# ---------------------------------------------------------------------------
# Hapus rekaman
# ---------------------------------------------------------------------------


def test_delete_recording(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    uploaded = _upload(s2_client, meeting_id).json()
    stored = storage_root() / "meetings" / meeting_id / uploaded["storage_filename"]
    assert stored.is_file()

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 200
    assert response.json()["detail"] == "Rekaman berhasil dihapus."
    assert not stored.exists()
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 404

    meetings = s2_client.get("/api/v1/meetings").json()
    target = next(m for m in meetings if m["id"] == meeting_id)
    assert target["status"] == "PENDING"
    assert target["has_recording"] is False


def test_delete_recording_when_not_available(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 404
    assert "belum tersedia" in response.json()["detail"]


def test_upload_again_after_delete(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    first = _upload(s2_client, meeting_id).json()

    assert s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200
    second = _upload(s2_client, meeting_id)

    assert second.status_code == 201
    assert second.json()["id"] != first["id"]
    assert second.json()["storage_filename"] != first["storage_filename"]


def test_delete_rejects_path_outside_storage(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    outside_file = BACKEND_DIR / "outside-delete-test.txt"
    outside_file.write_bytes(b"jangan dihapus")

    asset = AudioAsset(
        meeting_id=meeting_id,
        original_filename="outside.txt",
        storage_filename="outside.txt",
        storage_path="../outside-delete-test.txt",
        mime_type="audio/webm",
        file_size_bytes=outside_file.stat().st_size,
        duration_seconds=0.0,
    )
    s2_db.add(asset)
    s2_db.commit()

    try:
        response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")
        assert response.status_code == 500
        assert "luar direktori storage" in response.json()["detail"]
        assert outside_file.read_bytes() == b"jangan dihapus"
    finally:
        outside_file.unlink(missing_ok=True)


def test_delete_when_file_already_missing(s2_db, s2_client):
    meeting_id = _create_meeting(s2_client)
    uploaded = _upload(s2_client, meeting_id).json()
    stored = storage_root() / "meetings" / meeting_id / uploaded["storage_filename"]
    stored.unlink()

    response = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")

    assert response.status_code == 200
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/recording").status_code == 404
