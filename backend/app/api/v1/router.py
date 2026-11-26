"""Router utama API v1.

Menggabungkan seluruh endpoint versi 1 di bawah prefix `/api/v1`.
"""

from fastapi import APIRouter

from . import (
    action_items,
    config,
    diarizations,
    export,
    health,
    meetings,
    recordings,
    summaries,
    transcript_edits,
    transcriptions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(config.router)
api_router.include_router(meetings.router)
api_router.include_router(recordings.router)
api_router.include_router(transcriptions.router)
api_router.include_router(diarizations.router)
api_router.include_router(transcript_edits.router)
api_router.include_router(summaries.router)
api_router.include_router(action_items.router)
api_router.include_router(export.router)
