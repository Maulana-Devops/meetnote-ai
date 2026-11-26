"""Environment Alembic untuk MeetNote AI.

Semua tabel target berasal dari metadata ORM yang sama dengan aplikasi.
Konfigurasi database dibaca dari ``app.core.config.settings`` sehingga
variabel environment / file .env menjadi satu-satunya sumber kebenaran.
"""

import sys
from pathlib import Path

from alembic import context

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app import models  # noqa: E402,F401 - daftarkan semua model
from app.core.config import settings  # noqa: E402
from app.database.session import Base, engine  # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """Jalankan migrasi memakai engine yang sudah dikonfigurasi aplikasi."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
