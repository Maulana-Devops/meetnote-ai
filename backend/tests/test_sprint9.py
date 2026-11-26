"""Pengujian Sprint 9 — Pipeline Reliability & Data Integrity.

Semua provider adalah mock; tidak ada panggilan cloud/jaringan. Database dan
storage memakai fixture terisolasi dari ``conftest.py``.
"""

import concurrent.futures
import logging
import threading
import uuid

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import app.database.migrations as migrations
import app.services.summary.workflow as summary_service
from app.core.config import settings
from app.core.storage import storage_root
from app.database.session import SessionLocal, engine
from app.models.audio_asset import AudioAsset
from app.models.meeting import Meeting, MeetingStatus
from app.models.summary import SummaryJob, SummaryStatus
from app.models.transcript import TranscriptSegment
from app.services.llm.mock import MockLlmProvider
from app.services.stt.base import SttSegment
from app.services.stt.errors import SttProviderError
from app.services.stt.mock import MockSttProvider

WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 20


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _segments() -> list[SttSegment]:
    return [
        SttSegment("Halo semua.", 0.0, 2.0),
        SttSegment("Mulai rapat.", 2.0, 4.0),
        SttSegment("Terima kasih.", 4.0, 6.0),
    ]


def _meeting_and_audio(client, title: str = "Rapat Sprint 9") -> str:
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


def _transcribed_meeting(s2_client, monkeypatch, title: str = "Rapat Sprint 9") -> str:
    meeting_id = _meeting_and_audio(s2_client, title=title)
    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: MockSttProvider(segments=_segments()),
    )
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")
    assert response.status_code == 202, response.text
    return meeting_id


def _inject_llm(monkeypatch) -> None:
    """Suntik provider LLM mock untuk workflow ringkasan & action items."""
    monkeypatch.setattr(
        "app.services.summary.workflow._create_provider",
        lambda *args, **kwargs: MockLlmProvider(),
    )
    monkeypatch.setattr(
        "app.services.action_items.workflow._create_provider",
        lambda *args, **kwargs: MockLlmProvider(),
    )


# ---------------------------------------------------------------------------
# Database: foreign keys, constraints, migrasi aditif
# ---------------------------------------------------------------------------


def test_sqlite_foreign_keys_enabled_on_every_connection():
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    # raw_connection membuktikan event listener berjalan pada koneksi DBAPI baru.
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1
        cursor.close()
    finally:
        raw.close()


def test_foreign_key_violation_is_rejected(s2_db):
    orphan_meeting_id = str(uuid.uuid4())
    s2_db.add(
        TranscriptSegment(
            meeting_id=orphan_meeting_id,
            text="segmen yatim",
            start_seconds=0.0,
            end_seconds=1.0,
            sequence=1,
        )
    )
    with pytest.raises(IntegrityError):
        s2_db.commit()
    s2_db.rollback()


def test_db_level_cascade_removes_children(s2_db):
    # Buat meeting + metadata lewat ORM, lalu hapus lewat SQL mentah supaya
    # cascade benar-benar dijalankan SQLite (bukan ORM-level cascade).
    meeting = Meeting(title="Cascade", status=MeetingStatus.UPLOADED)
    s2_db.add(meeting)
    s2_db.commit()
    meeting_id = meeting.id
    s2_db.add(
        AudioAsset(
            meeting_id=meeting_id,
            original_filename="rapat.wav",
            storage_filename="rapat.wav",
            storage_path=f"meetings/{meeting_id}/rapat.wav",
            mime_type="audio/wav",
            file_size_bytes=1,
            duration_seconds=0.0,
        )
    )
    s2_db.commit()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM meetings WHERE id = :id"), {"id": meeting_id})
    s2_db.expunge_all()
    assert s2_db.query(AudioAsset).filter(AudioAsset.meeting_id == meeting_id).count() == 0


def test_job_tables_have_run_token_column(s2_db):
    inspector = inspect(engine)
    for table in (
        "transcription_jobs",
        "diarization_jobs",
        "summary_jobs",
        "action_item_jobs",
    ):
        assert "run_token" in {c["name"] for c in inspector.get_columns(table)}


def test_legacy_migration_is_additive_and_keeps_duplicates(tmp_path, monkeypatch):
    """DB lama tanpa run_token dan dengan duplikat audio tetap aman."""
    legacy_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy_engine = create_engine(
        legacy_url, connect_args={"check_same_thread": False}
    )
    with legacy_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY, title VARCHAR(255))")
        )
        connection.execute(
            text(
                "CREATE TABLE transcript_segments ("
                "id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36), sequence INTEGER)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE audio_assets ("
                "id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36))"
            )
        )
        connection.execute(text("INSERT INTO meetings (id, title) VALUES ('m1', 'Lama')"))
        connection.execute(
            text("INSERT INTO audio_assets (id, meeting_id) VALUES ('a1', 'm1')")
        )
        connection.execute(
            text("INSERT INTO audio_assets (id, meeting_id) VALUES ('a2', 'm1')")
        )

    monkeypatch.setattr(migrations, "engine", legacy_engine)
    migrations.apply_additive_migrations()

    inspector = inspect(legacy_engine)
    assert "speaker_id" in {
        c["name"] for c in inspector.get_columns("transcript_segments")
    }
    # Duplikat lama TIDAK dihapus; index unik sengaja dilewati.
    with legacy_engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM audio_assets WHERE meeting_id = 'm1'")
        ).scalar() == 1 + 1
        indexes = {row[0] for row in connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        )}
    assert "uq_audio_asset_meeting" not in indexes
    legacy_engine.dispose()


# ---------------------------------------------------------------------------
# Concurrency & stale-task protection
# ---------------------------------------------------------------------------


def test_concurrent_prepare_summary_only_one_wins(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.summaries.run_summary", lambda meeting_id: None
    )

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt() -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=5)
            summary_service.prepare_summary(session, uuid.UUID(meeting_id))
            session.commit()
            outcomes.append("ok")
        except HTTPException as exc:
            outcomes.append(str(exc.status_code))
        finally:
            session.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: attempt(), range(2)))

    assert sorted(outcomes) == ["409", "ok"]
    db = SessionLocal()
    try:
        assert db.query(SummaryJob).filter(
            SummaryJob.meeting_id == meeting_id
        ).count() == 1
    finally:
        db.close()


def test_stale_task_cannot_mark_failed_newer_job(s2_db):
    meeting = Meeting(title="Stale", status=MeetingStatus.PENDING)
    s2_db.add(meeting)
    s2_db.commit()
    job = SummaryJob(
        meeting_id=meeting.id,
        status=SummaryStatus.PROCESSING,
        run_token="token-baru",
        provider="mock",
        model="mock-model",
    )
    s2_db.add(job)
    s2_db.commit()

    summary_service._mark_failed(uuid.UUID(meeting.id), "kegagalan lama", "token-lama")
    s2_db.expire_all()
    refreshed = s2_db.query(SummaryJob).filter(SummaryJob.meeting_id == meeting.id).first()
    assert refreshed.status == SummaryStatus.PROCESSING
    assert refreshed.error is None


def test_recovery_is_idempotent_and_preserves_completed(s2_client, monkeypatch, s2_db):
    completed_meeting = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch)
    monkeypatch.setattr("app.api.v1.summaries.run_summary", lambda meeting_id: None)
    assert s2_client.post(f"/api/v1/meetings/{completed_meeting}/summary").status_code == 202
    # Selesaikan job pertama secara sinkron.
    summary_service.run_summary(uuid.UUID(completed_meeting))
    before = s2_client.get(f"/api/v1/meetings/{completed_meeting}/summary").json()

    stuck_meeting = _transcribed_meeting(s2_client, monkeypatch, title="Stuck")
    s2_db.add(
        SummaryJob(
            meeting_id=stuck_meeting,
            status=SummaryStatus.PROCESSING,
            run_token=str(uuid.uuid4()),
            provider="mock",
            model="mock-model",
        )
    )
    s2_db.commit()

    assert summary_service.recover_stuck_summaries() == 1
    assert summary_service.recover_stuck_summaries() == 0

    after = s2_client.get(f"/api/v1/meetings/{completed_meeting}/summary").json()
    assert after["status"] == "COMPLETED"
    assert after["topics"] == before["topics"]
    stuck = s2_client.get(f"/api/v1/meetings/{stuck_meeting}/summary").json()
    assert stuck["status"] == "FAILED"
    assert "dimulai ulang" in stuck["error"]


# ---------------------------------------------------------------------------
# Error handling & logging
# ---------------------------------------------------------------------------


def test_provider_exception_maps_to_failed_without_leaking_secret(
    s2_db, s2_client, monkeypatch, caplog
):
    meeting_id = _meeting_and_audio(s2_client)
    monkeypatch.setattr(settings, "STT_API_KEY", SecretStr("sk-jangan-bocor"))

    class ExplodingProvider:
        name = "mock"
        model = "mock-model"

        def validate_configuration(self):
            return None

        def supported_extensions(self):
            return {".wav"}

        max_file_bytes = 25 * 1024 * 1024

        def transcribe(self, **kwargs):
            raise SttProviderError("koneksi gagal")

    monkeypatch.setattr(
        "app.services.transcription._create_provider",
        lambda *args, **kwargs: ExplodingProvider(),
    )

    with caplog.at_level(logging.INFO, logger="meetnote"):
        response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 202
    detail = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()
    assert detail["status"] == "FAILED"
    assert "sk-jangan-bocor" not in str(detail)
    assert "sk-jangan-bocor" not in caplog.text
    assert "job_failed" in caplog.text
    assert "SttProviderError" in caplog.text
    assert meeting_id in caplog.text


def test_internal_error_is_not_leaked(s2_db, s2_client, monkeypatch):
    meeting_id = _meeting_and_audio(s2_client)

    def boom(*args, **kwargs):
        raise SQLAlchemyError("rahasia-database-internal")

    monkeypatch.setattr("app.services.transcription.clear_transcription", boom)
    response = s2_client.post(f"/api/v1/meetings/{meeting_id}/transcription")

    assert response.status_code == 500
    assert response.json()["detail"] == "Gagal menyiapkan transkripsi."
    assert "rahasia-database-internal" not in response.text


# ---------------------------------------------------------------------------
# Storage audit & health
# ---------------------------------------------------------------------------


def test_health_diagnostics_reports_fk_and_is_readonly(s2_client):
    response = s2_client.get("/api/v1/health/diagnostics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sqlite_foreign_keys"] == 1
    assert body["storage"]["note"].startswith("Audit read-only")
    assert "orphan_files" in body["storage"]


def test_storage_audit_reports_relative_paths_without_deleting(s2_client):
    root = storage_root()
    orphan = root / "meetings" / "orphan-check.txt"
    temp = root / "meetings" / "partial.part"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"orphan")
    temp.write_bytes(b"partial")

    try:
        body = s2_client.get("/api/v1/health/diagnostics").json()
        storage = body["storage"]
        assert "meetings/orphan-check.txt" in storage["orphan_files"]
        assert "meetings/partial.part" in storage["temp_files"]
        assert all(not p.startswith(("C:", "/")) for p in storage["orphan_files"])
        assert orphan.exists() and temp.exists()
    finally:
        orphan.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Delete dependency
# ---------------------------------------------------------------------------


def test_delete_transcription_and_recording_blocked_by_active_summary(
    s2_client, monkeypatch
):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch)
    monkeypatch.setattr("app.api.v1.summaries.run_summary", lambda meeting_id: None)
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202

    transcript_delete = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")
    assert transcript_delete.status_code == 409
    assert "ringkasan" in transcript_delete.json()["detail"]

    recording_delete = s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording")
    assert recording_delete.status_code == 409

    # Selesaikan job ringkasan agar penghapusan normal tetap berfungsi
    # (regresi Sprint 3/4/7).
    summary_service.run_summary(uuid.UUID(meeting_id))
    summary_delete = s2_client.delete(f"/api/v1/meetings/{meeting_id}/summary")
    assert summary_delete.status_code == 200, summary_delete.text
    transcript_delete_ok = s2_client.delete(f"/api/v1/meetings/{meeting_id}/transcription")
    assert transcript_delete_ok.status_code == 200, transcript_delete_ok.text
    assert s2_client.delete(f"/api/v1/meetings/{meeting_id}/recording").status_code == 200


def test_failed_summary_does_not_invalidate_transcript(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)

    class BadLlm:
        name = "mock"
        model = "mock-model"

        def validate_configuration(self):
            return None

        def summarize(self, data):
            raise RuntimeError("gangguan")

    monkeypatch.setattr(
        "app.services.summary.workflow._create_provider", lambda *a, **k: BadLlm()
    )
    assert s2_client.post(f"/api/v1/meetings/{meeting_id}/summary").status_code == 202
    status = s2_client.get(f"/api/v1/meetings/{meeting_id}/summary").json()
    transcript = s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()

    assert status["status"] == "FAILED"
    assert len(transcript["segments"]) == len(_segments())
    assert transcript["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Regresi ringkas Sprint 1-8
# ---------------------------------------------------------------------------


def test_full_pipeline_mock_regression(s2_client, monkeypatch):
    meeting_id = _transcribed_meeting(s2_client, monkeypatch)
    _inject_llm(monkeypatch)
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/transcription").json()[
        "status"
    ] == "COMPLETED"

    summary_response = s2_client.post(f"/api/v1/meetings/{meeting_id}/summary")
    assert summary_response.status_code == 202, summary_response.text
    assert s2_client.get(f"/api/v1/meetings/{meeting_id}/summary").json()["status"] == "COMPLETED"

    items_response = s2_client.post(f"/api/v1/meetings/{meeting_id}/action-items")
    assert items_response.status_code == 202, items_response.text
    items = s2_client.get(f"/api/v1/meetings/{meeting_id}/action-items").json()
    assert items["status"] == "COMPLETED"

    health = s2_client.get("/api/v1/health")
    assert health.json()["status"] == "healthy"
