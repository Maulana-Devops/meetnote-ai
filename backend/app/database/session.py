# Konfigurasi database dan engine SQLAlchemy.
#
# Membaca DATABASE_URL dari `core.config` dan menyiapkan:
#   - `engine`  : koneksi database (default: SQLite)
#   - `SessionLocal`: factory untuk membuat sesi database
#   - `Base`    : base class ORM yang diwarisi oleh semua model
#
# Sprint 9: untuk SQLite, PRAGMA foreign_keys=ON diaktifkan pada SETIAP
# koneksi baru. Tanpa ini, klausa ON DELETE CASCADE / SET NULL di model hanya
# berupa teks DDL dan TIDAK dijalankan oleh SQLite. busy_timeout juga ditambah
# supaya writer yang bentrok tidak langsung gagal dengan "database is locked".

import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config import settings

# Untuk SQLite diperlukan `check_same_thread=False` agar bisa dipakai oleh thread
# server (uvicorn).
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_integrity(dbapi_connection, connection_record) -> None:
        """Aktifkan FK + timeout pada setiap koneksi SQLite baru."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    if settings.SQLITE_WAL_ENABLED:
        # WAL dipakai bila beberapa proses (API + worker) membaca/menulis DB
        # yang sama. Bersifat aditif: tidak mengubah data atau skema tabel.
        logger = logging.getLogger(__name__)
        try:
            with engine.connect() as connection:
                mode = connection.exec_driver_sql(
                    "PRAGMA journal_mode=WAL"
                ).scalar()
            if str(mode).lower() != "wal":
                logger.warning("sqlite_wal_not_applied mode=%s", mode)
        except Exception as exc:  # pragma: no cover - tergantung filesystem
            logger.warning(
                "sqlite_wal_unavailable error_category=%s", type(exc).__name__
            )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
