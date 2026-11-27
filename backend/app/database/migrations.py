"""Migrasi aditif untuk skema lama (Sprint 5 + Sprint 9).

Tidak ada Alembic/dependency baru. Fungsi ini hanya melakukan perubahan yang
bersifat aditif dan idempotent:

* menambah kolom ``speaker_id`` bila database lama belum memilikinya;
* memastikan index kolom tersebut ada;
* memastikan index UNIK ``audio_assets.meeting_id`` ada bila data lama tidak
  memiliki duplikat (Sprint 9).

Tabel lama tidak dijatuhkan dan tidak dibuat ulang, sehingga data produksi
tetap aman. Constraint foreign key hanya dibuat otomatis oleh ``create_all``
pada database baru; SQLite tidak mendukung ``ALTER TABLE ADD CONSTRAINT``.
Sprint 9 mengaktifkan ``PRAGMA foreign_keys=ON`` per koneksi di
``database/session.py``, tetapi untuk database lama yang dibuat sebelum
constraint ada, integritas tetap dijaga di level ORM/clear_* seperti sebelumnya.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .session import engine

logger = logging.getLogger(__name__)

# backend/app/database/migrations.py -> backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


_UNIQUE_INDEXES = (
    # (nama index, tabel, kolom)
    ("uq_audio_asset_meeting", "audio_assets", "meeting_id"),
)

# Sprint 9: kolom token percobaan untuk empat jenis job. Nullable dan tidak
# mengubah data lama; job lama tetap bisa di-retry dengan token kosong.
_RUN_TOKEN_TABLES = (
    "transcription_jobs",
    "diarization_jobs",
    "summary_jobs",
    "action_item_jobs",
)


def _ensure_unique_index(connection: Connection, name: str, table: str, column: str) -> None:
    """Buat unique index hanya bila tidak ada duplikat pada data lama.

    SQLite tidak bisa ALTER TABLE ADD CONSTRAINT, jadi CREATE UNIQUE INDEX
    adalah satu-satunya cara aditif. Bila database lama ternyata sudah punya
    dua metadata audio untuk meeting yang sama, index DITUNDA dan dicatat —
    data pengguna tidak dihapus atau diubah.
    """
    existing = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"),
        {"name": name},
    ).first()
    if existing is not None:
        return

    duplicate = connection.execute(
        text(
            f"SELECT {column} FROM {table} "
            f"GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        logger.warning(
            "unique_index_skipped index=%s table=%s reason=legacy_duplicates",
            name,
            table,
        )
        return

    connection.execute(
        text(f"CREATE UNIQUE INDEX {name} ON {table} ({column})")
    )
    logger.info("unique_index_created index=%s table=%s", name, table)


def apply_additive_migrations() -> None:
    """Terapkan migrasi aditif dengan aman untuk SQLite."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "transcript_segments" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("transcript_segments")}

    with engine.begin() as connection:
        if "speaker_id" not in columns:
            connection.execute(
                text("ALTER TABLE transcript_segments ADD COLUMN speaker_id VARCHAR(36)")
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_id "
                "ON transcript_segments (speaker_id)"
            )
        )

        for table in _RUN_TOKEN_TABLES:
            if table not in table_names:
                continue
            table_columns = {c["name"] for c in inspector.get_columns(table)}
            if "run_token" not in table_columns:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN run_token VARCHAR(36)")
                )
                logger.info("column_added table=%s column=run_token", table)

        for name, table, column in _UNIQUE_INDEXES:
            if table in table_names:
                _ensure_unique_index(connection, name, table, column)

        # Mode worker (JOB_RUNNER=worker) memakai tabel ini. Database lama yang
        # di-stamp head tidak menjalankan 0002, jadi pastikan dibuat di sini.
        # CREATE TABLE IF NOT EXISTS bersifat aditif dan tidak menyentuh data.
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS job_queue ("
                "id VARCHAR(36) NOT NULL, "
                "job_type VARCHAR(40) NOT NULL, "
                "meeting_id VARCHAR(36) NOT NULL, "
                "run_token VARCHAR(36), "
                "status VARCHAR(20) NOT NULL, "
                "attempts INTEGER NOT NULL DEFAULT '0', "
                "worker_id VARCHAR(100), "
                "error_category VARCHAR(100), "
                "created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP), "
                "updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP), "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(meeting_id) REFERENCES meetings (id) ON DELETE CASCADE"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_job_queue_status_created_at "
                "ON job_queue (status, created_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_job_queue_meeting_id "
                "ON job_queue (meeting_id)"
            )
        )


def _alembic_config() -> Config:
    """Buat Config Alembic yang menunjuk ke folder migrasi backend."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return config


def run_migrations() -> None:
    """Terapkan Alembic dengan aman untuk DB baru maupun DB lama.

    - DB kosong: ``upgrade head`` membuat seluruh tabel dari baseline.
    - DB lama yang sudah punya tabel tetapi belum punya ``alembic_version``:
      jalankan migrasi aditif lama, lalu ``stamp head``. Tidak ada tabel yang
      dijatuhkan dan tidak ada data yang diubah.
    - DB yang sudah punya ``alembic_version``: ``upgrade head`` (biasanya no-op).
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_version_table = "alembic_version" in tables
    has_legacy_schema = bool(tables - {"alembic_version"})

    config = _alembic_config()

    if not has_version_table and has_legacy_schema:
        logger.info("legacy_database_detected action=stamp_baseline")
        apply_additive_migrations()
        command.stamp(config, "head")
        logger.info("legacy_database_stamped revision=head")
        return

    command.upgrade(config, "head")
    logger.info("alembic_upgrade_complete revision=head")
