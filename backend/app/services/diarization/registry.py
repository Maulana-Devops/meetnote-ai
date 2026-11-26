"""Pemilih provider diarisasi berdasarkan konfigurasi backend."""

from ...core.config import settings
from .base import DiarizationProvider
from .deepgram_provider import DeepgramDiarizationProvider
from .errors import DiarizationConfigurationError
from .mock import MockDiarizationProvider
from .pyannote_provider import PyannoteDiarizationProvider


def create_provider(provider_name: str | None = None) -> DiarizationProvider:
    """Buat provider sesuai nama; error jelas bila nama tidak dikenali."""
    name = (provider_name or settings.DIARIZATION_PROVIDER).strip().lower()

    if name == "deepgram":
        return DeepgramDiarizationProvider()
    if name == "mock":
        return MockDiarizationProvider()
    if name == "pyannote":
        return PyannoteDiarizationProvider()

    raise DiarizationConfigurationError(
        f"DIARIZATION_PROVIDER '{name}' tidak dikenali. "
        "Pilih 'mock', 'deepgram', atau 'pyannote'."
    )


def is_diarization_configured() -> bool:
    """Cek aman untuk endpoint konfigurasi publik (tanpa secret)."""
    try:
        create_provider().validate_configuration()
        return True
    except Exception:
        return False
