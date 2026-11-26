"""Pengujian untuk backend MeetNote AI Sprint 1.

Cakupan:
- Endpoint health check
- Inisialisasi database (create_all)
- Pembuatan model Meeting (default status UPLOADED)
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.main import app
from app.models.meeting import Meeting

# Database khusus untuk pengujian (file terpisah dari database produksi)
TEST_DATABASE_URL = "sqlite:///./test.db"

test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def db_session():
    """Buat ulang tabel untuk setiap test function."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="module")
def client():
    """TestClient untuk endpoint API."""
    # Pastikan tabel ada selama modul tes berjalan
    Base.metadata.create_all(bind=test_engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=test_engine)


# ---------------------------------------------------------------------------
# 1. Health endpoint
# ---------------------------------------------------------------------------


def test_health_endpoint(client: TestClient):
    """GET /api/v1/health harus mengembalikan status healthy."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "application": "MeetNote AI",
    }


# ---------------------------------------------------------------------------
# 2. Inisialisasi database
# ---------------------------------------------------------------------------


def test_database_initialization(db_session):
    """Tabel `meetings` harus dibuat oleh create_all."""
    inspector = inspect(test_engine)
    tables = inspector.get_table_names()
    assert "meetings" in tables

    columns = {col["name"] for col in inspector.get_columns("meetings")}
    assert columns == {"id", "title", "status", "created_at", "updated_at"}


# ---------------------------------------------------------------------------
# 3. Model Meeting
# ---------------------------------------------------------------------------


def test_list_meetings_endpoint(client: TestClient):
    """GET /api/v1/meetings harus mengembalikan array (bisa kosong)."""
    response = client.get("/api/v1/meetings")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_meeting_model(db_session):
    """Meeting baru harus memiliki UUID dan status awal UPLOADED."""
    meeting = Meeting(title="Rapat Mingguan")
    db_session.add(meeting)
    db_session.commit()
    db_session.refresh(meeting)

    # UUID valid
    assert isinstance(uuid.UUID(meeting.id), uuid.UUID)

    # Field dasar
    assert meeting.title == "Rapat Mingguan"
    assert meeting.status == "UPLOADED"
    assert meeting.created_at is not None
    assert meeting.updated_at is not None


def test_meeting_repr(db_session):
    """Representasi string Meeting membantu debugging."""
    meeting = Meeting(title="Rapat Tim")
    assert "Rapat Tim" in repr(meeting)
