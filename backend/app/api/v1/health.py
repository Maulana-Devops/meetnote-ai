"""Endpoint health check.

Digunakan untuk memverifikasi bahwa aplikasi backend berjalan dengan baik.
Sprint 9 menambahkan diagnostic read-only: status PRAGMA SQLite dan ringkasan
anomali storage. Tidak ada secret, path absolut, isi audio, atau transkrip yang
dikembalikan.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.storage import audit_storage
from ...database.session import engine
from .meetings import get_db

router = APIRouter()


@router.get("/health", tags=["Health"])
def health_check() -> dict:
    """Kembalikan status kesehatan aplikasi."""
    return {"status": "healthy", "application": settings.APP_NAME}


@router.get("/health/diagnostics", tags=["Health"])
def health_diagnostics(db: Session = Depends(get_db)) -> dict:
    """Informasi diagnostik non-sensitif untuk operasional.

    - ``sqlite_foreign_keys``: 1 bila PRAGMA foreign_keys AKTIF pada koneksi.
    - ``storage``: laporan anomaly read-only (lihat ``core.storage.audit_storage``).
    """
    foreign_keys: int | None = None
    if settings.DATABASE_URL.startswith("sqlite"):
        with engine.connect() as connection:
            foreign_keys = int(connection.execute(text("PRAGMA foreign_keys")).scalar() or 0)

    return {
        "status": "healthy",
        "application": settings.APP_NAME,
        "sqlite_foreign_keys": foreign_keys,
        "storage": audit_storage(db),
    }
