"""Entry point aplikasi FastAPI MeetNote AI.

Menjalankan aplikasi:
    python main.py
atau:
    uvicorn app.main:app --reload --port 8000
"""

import os
import sys
from contextlib import asynccontextmanager

# Pastikan folder backend menjadi import root agar `app...` dapat dikenali
# ketika script dijalankan langsung (python main.py).
_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import RequestIDMiddleware
from app.core.request_limits import UploadSizeLimitMiddleware
from app.database.session import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Siapkan logging, skema database, dan recovery job saat aplikasi start."""
    # Import di sini agar model terdaftar sebelum skema dibuat/diverifikasi.
    from app import models  # noqa: F401
    from app.core.logging import configure_logging
    from app.database.migrations import apply_additive_migrations, run_migrations
    from app.services.action_items.workflow import recover_stuck_action_items
    from app.services.diarization.workflow import recover_stuck_diarizations
    from app.services.summary.workflow import recover_stuck_summaries
    from app.services.transcription import recover_stuck_transcriptions

    configure_logging()

    if settings.RUN_DB_MIGRATIONS:
        # Alembic menangani DB baru dan DB lama tanpa menghapus data.
        run_migrations()
    else:
        # Test suite mengelola skema sendiri (lihat tests/conftest.py).
        Base.metadata.create_all(bind=engine)
        apply_additive_migrations()

    # Mode background: task in-process hilang saat restart, jadi tandai job
    # PROCESSING sebagai FAILED agar bisa dicoba lagi dari UI. Mode worker
    # sengaja tidak melakukan ini: worker yang membersihkan antrean stale.
    # Setiap recovery diisolasi agar satu kegagalan tidak membatalkan yang lain.
    import logging

    logger = logging.getLogger("meetnote.startup")

    if settings.JOB_RUNNER != "worker":
        for name, recover in (
            ("transcription", recover_stuck_transcriptions),
            ("diarization", recover_stuck_diarizations),
            ("summary", recover_stuck_summaries),
            ("action_items", recover_stuck_action_items),
        ):
            try:
                recover()
            except Exception as exc:  # pragma: no cover - startup abnormal
                logger.error(
                    "startup_recovery_failed job_type=%s error_category=%s",
                    name,
                    type(exc).__name__,
                )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Aplikasi untuk merekam, mentranskripsikan, dan merangkum rapat menggunakan AI.",
    version="0.1.0",
    lifespan=lifespan,
)

def safe_cors_origins(raw: str) -> list[str]:
    """Origin yang benar-benar berbentuk http(s)://host; wildcard ditolak."""
    origins: list[str] = []
    for value in raw.split(","):
        origin = value.strip()
        if not origin or origin == "*":
            continue
        parsed = urlparse(origin)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            origins.append(origin)
    return origins


# Urutan penting: RequestID adalah middleware terluar, lalu CORS, lalu batas
# ukuran upload. Dengan begitu response 413 tetap membawa X-Request-ID dan
# header CORS yang sah.
app.add_middleware(UploadSizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=safe_cors_origins(settings.CORS_ALLOWED_ORIGINS),
    # Tidak ada cookie/token dalam mode tanpa akun; jangan aktifkan credentials.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
# Request ID harus aktif untuk semua response, termasuk error.
app.add_middleware(RequestIDMiddleware)

# Daftarkan router v1
app.include_router(api_router)


@app.get("/", tags=["Root"])
def root() -> dict:
    """Endpoint akar untuk informasi singkat."""
    return {"message": f"Selamat datang di {settings.APP_NAME}", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.BACKEND_PORT,
        reload=settings.DEBUG,
    )