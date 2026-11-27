"""Konfigurasi global untuk pengujian backend.

Environment di-set SEBELUM modul `app` di-import agar engine database dan
direktori storage pointing ke lokasi khusus test. Database produksi
(`meetnote.db`) dan folder `storage/` tidak disentuh oleh test.
"""

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_API_DB = BACKEND_DIR / "api_test.db"
TEST_STORAGE_DIR = BACKEND_DIR / "test_storage"

# Kritis: harus terjadi sebelum `from app...` di bawah.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_API_DB.as_posix()}"
os.environ["STORAGE_DIR"] = str(TEST_STORAGE_DIR)
# 1 MB supaya test batas ukuran cepat; produksi tetap 25 MB dari .env.
os.environ["MAX_AUDIO_FILE_BYTES"] = "1048576"
# Sprint 4: test memakai provider mock, tidak pernah memanggil cloud/API key.
os.environ["STT_PROVIDER"] = "mock"
os.environ["STT_API_KEY"] = ""
os.environ["STT_API_BASE_URL"] = "https://api.openai.com/v1"
os.environ["STT_MODEL"] = "mock-1"
# Sprint 5: test memakai provider mock, tidak pernah memanggil cloud/API key.
os.environ["DIARIZATION_PROVIDER"] = "mock"
os.environ["DIARIZATION_API_KEY"] = ""
os.environ["DIARIZATION_API_BASE_URL"] = "https://api.deepgram.com/v1"
os.environ["DIARIZATION_MODEL"] = "nova-3"
os.environ["DIARIZATION_DIARIZE_MODEL"] = "latest"
os.environ["DIARIZATION_MIN_OVERLAP_RATIO"] = "0.5"
os.environ["DIARIZATION_MIN_OVERLAP_SECONDS"] = "0"
# Sprint 7: test memakai provider mock, tidak pernah memanggil cloud/API key.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_BASE_URL"] = "https://api.openai.com/v1"
os.environ["LLM_MODEL"] = "mock-1"
os.environ["LLM_OUTPUT_LANGUAGE"] = ""
os.environ["LLM_TIMEOUT_SECONDS"] = "30"
os.environ["LLM_MAX_INPUT_CHARACTERS"] = "24000"
# Retry diuji terpisah dengan sleep di-mock. Job test tetap deterministik dan
# tidak menunggu backoff saat provider error disengaja.
os.environ["PROVIDER_RETRY_ATTEMPTS"] = "1"
# Test mengelola skema sendiri lewat Base.metadata.create_all()/drop_all().
# Alembic tidak dipakai supaya tabel alembic_version tidak tertinggal.
os.environ["RUN_DB_MIGRATIONS"] = "false"

from app.database.migrations import apply_additive_migrations  # noqa: E402
from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def s2_db():
    """Database + storage bersih untuk satu test Sprint 2."""
    shutil.rmtree(TEST_STORAGE_DIR, ignore_errors=True)
    Base.metadata.create_all(bind=engine)
    apply_additive_migrations()

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        shutil.rmtree(TEST_STORAGE_DIR, ignore_errors=True)


@pytest.fixture
def s2_client():
    """TestClient yang menjalankan lifespan aplikasi."""
    with TestClient(app) as client:
        yield client
