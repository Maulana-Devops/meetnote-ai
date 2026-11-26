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

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .session import engine

logger = logging.getLogger(__name__)


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
