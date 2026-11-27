"""Uji hardening keamanan pasca-audit (read-only terhadap data produksi).

Semua penulisan memakai fixture test yang terisolasi (``s2_db``/``s2_client``).
Tidak ada provider AI, jaringan, audio produksi, atau secret yang dipakai.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import uuid
from pathlib import Path

from starlette.middleware.cors import CORSMiddleware

from app.core.request_limits import UploadSizeLimitMiddleware
from app.main import app, safe_cors_origins
from app.models.action_item import ActionItem
from app.models.audio_asset import AudioAsset
from app.models.meeting import Meeting, MeetingStatus
from app.services import job_guard


def _meeting(s2_db) -> Meeting:
    meeting = Meeting(title="Rapat Uji Keamanan", status=MeetingStatus.PENDING)
    s2_db.add(meeting)
    s2_db.commit()
    return meeting


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_middleware_menolak_content_length_sebelum_multipart():
    downstream_calls: list[bool] = []

    async def downstream(scope, receive, send):
        downstream_calls.append(True)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = UploadSizeLimitMiddleware(downstream)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/meetings/x/recording",
        "headers": [(b"content-length", b"999999999")],
    }
    asyncio.run(middleware(scope, None, send))

    assert sent[0]["status"] == 413
    assert downstream_calls == []


def test_upload_middleware_meneruskan_request_normal():
    downstream_calls: list[bool] = []

    async def downstream(scope, receive, send):
        downstream_calls.append(True)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = UploadSizeLimitMiddleware(downstream)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/meetings/x/recording",
        "headers": [(b"content-length", b"2048")],
    }
    asyncio.run(middleware(scope, None, send))

    assert sent[0]["status"] == 204
    assert downstream_calls == [True]


def test_durasi_inf_ditolak_tanpa_menyimpan_asset(s2_db, s2_client):
    meeting = _meeting(s2_db)
    before = s2_db.query(AudioAsset).count()

    response = s2_client.post(
        f"/api/v1/meetings/{meeting.id}/recording",
        files={"file": ("rapat.webm", b"fake-audio", "audio/webm")},
        data={"duration_seconds": "1e999"},
    )

    assert response.status_code == 422
    assert s2_db.query(AudioAsset).count() == before


# ---------------------------------------------------------------------------
# Header & CORS
# ---------------------------------------------------------------------------


def test_request_id_invalid_disanhitasi_dan_nosniff_aktif(s2_client):
    response = s2_client.get("/api/v1/health", headers={"X-Request-ID": "bad id!"})

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_cors_wildcard_dan_skema_asing_ditolak():
    assert safe_cors_origins("*") == []
    assert safe_cors_origins("javascript:alert(1),ftp://x") == []
    assert safe_cors_origins("*,http://localhost:4173") == ["http://localhost:4173"]

    cors = [item for item in app.user_middleware if item.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_credentials"] is False


# ---------------------------------------------------------------------------
# Batas teks & konkurensi
# ---------------------------------------------------------------------------


def test_deskripsi_action_item_dibatasi(s2_db, s2_client):
    meeting = _meeting(s2_db)
    item = ActionItem(
        meeting_id=meeting.id,
        title="Kirim laporan",
        description="",
        status="OPEN",
        start_seconds=0.0,
        end_seconds=1.0,
    )
    s2_db.add(item)
    s2_db.commit()

    response = s2_client.patch(
        f"/api/v1/meetings/{meeting.id}/action-items/{item.id}",
        json={"description": "a" * 5000},
    )

    assert response.status_code == 422
    s2_db.refresh(item)
    assert item.description == ""


def test_registry_lock_dibersihkan_setelah_pemakaian():
    key = ("test-harden", str(uuid.uuid4()))
    with job_guard.job_lock(key[0], key[1]):
        assert key in job_guard._locks
        assert job_guard._users[key] == 1

    assert key not in job_guard._locks
    assert key not in job_guard._users


# ---------------------------------------------------------------------------
# Migrasi
# ---------------------------------------------------------------------------


def test_downgrade_alembic_sengaja_dinonaktifkan():
    baseline = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0001_baseline.py"
    )
    spec = importlib.util.spec_from_file_location("baseline_0001", baseline)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    try:
        module.downgrade()
    except RuntimeError as exc:
        assert "backup/restore" in str(exc)
    else:
        raise AssertionError("downgrade harus menolak penghapusan skema")

    assert "op.drop_table" not in baseline.read_text(encoding="utf-8")
