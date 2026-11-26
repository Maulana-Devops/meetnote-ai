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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.database.session import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Buat tabel database saat aplikasi start."""
    # Import di sini agar model terdaftar sebelum create_all dipanggil
    from app import models  # noqa: F401
    from app.database.migrations import apply_additive_migrations
    from app.services.action_items.workflow import recover_stuck_action_items
    from app.services.diarization.workflow import recover_stuck_diarizations
    from app.services.summary.workflow import recover_stuck_summaries
    from app.services.transcription import recover_stuck_transcriptions

    # create_all hanya membuat tabel baru; tabel lama dan datanya tidak diubah.
    Base.metadata.create_all(bind=engine)
    # Sprint 5: tambahan kolom aditif untuk database yang sudah ada.
    apply_additive_migrations()

    # Sprint 4/5/7/8: background task in-process hilang saat restart. Tandai job
    # yang masih PROCESSING sebagai FAILED agar bisa dicoba lagi dari UI.
    # Sprint 9: setiap recovery diisolasi agar satu kegagalan tidak membatalkan
    # recovery jenis lain atau membuat aplikasi gagal start.
    import logging

    logger = logging.getLogger("meetnote.startup")

    for name, recover in (
        ("transcription", recover_stuck_transcriptions),
        ("diarization", recover_stuck_diarizations),
        ("summary", recover_stuck_summaries),
        ("action_items", recover_stuck_action_items),
    ):
        try:
            recover()
        except Exception as exc:  # pragma: no cover - jalur startup abnormal
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

# CORS: origin dapat diatur lewat CORS_ALLOWED_ORIGINS (default: Vite dev server).
_cors_origins = [
    origin.strip()
    for origin in settings.CORS_ALLOWED_ORIGINS.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

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