"""Skema konfigurasi publik untuk frontend."""

from pydantic import BaseModel


class AppConfigRead(BaseModel):
    """Informasi bukan rahasia yang dibutuhkan frontend saat memilih file."""

    max_audio_file_bytes: int
    allowed_mime_types: list[str]
    allowed_extensions: list[str]
    # Sprint 4: info STT yang aman dipublikasikan (tanpa API key).
    stt_provider: str
    stt_configured: bool
    # Fase 1: bahasa yang dipakai STT/ringkasan (bukan secret/path absolut).
    stt_language: str
    summary_language: str
    # Sprint 5: info diarisasi yang aman dipublikasikan (tanpa API key).
    diarization_provider: str
    diarization_configured: bool
    # Sprint 7: info LLM yang aman dipublikasikan (tanpa API key).
    llm_provider: str
    llm_configured: bool
