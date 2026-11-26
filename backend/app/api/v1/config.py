"""Endpoint konfigurasi publik (bukan secret).

Frontend memakai endpoint ini untuk mengetahui batas ukuran file, daftar
format audio, dan info STT yang aman dipublikasikan. Kredensial provider
tidak pernah dikirim lewat endpoint ini.
"""

from fastapi import APIRouter

from ...core.audio import ALLOWED_AUDIO_TYPES, ALLOWED_EXTENSIONS
from ...core.config import settings
from ...schemas.config import AppConfigRead
from ...services.diarization.registry import is_diarization_configured
from ...services.llm.registry import is_llm_configured
from ...services.stt.registry import is_stt_configured

router = APIRouter(tags=["Config"])


@router.get("/config", response_model=AppConfigRead)
def get_app_config() -> AppConfigRead:
    """Kembalikan batas ukuran dan format audio yang didukung."""
    return AppConfigRead(
        max_audio_file_bytes=settings.MAX_AUDIO_FILE_BYTES,
        allowed_mime_types=sorted(ALLOWED_AUDIO_TYPES),
        allowed_extensions=sorted(ALLOWED_EXTENSIONS),
        stt_provider=settings.STT_PROVIDER,
        stt_configured=is_stt_configured(),
        diarization_provider=settings.DIARIZATION_PROVIDER,
        diarization_configured=is_diarization_configured(),
        llm_provider=settings.LLM_PROVIDER,
        llm_configured=is_llm_configured(),
    )