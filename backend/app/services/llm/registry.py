"""Pemilih provider LLM berdasarkan konfigurasi backend."""

from ...core.config import settings
from .base import LlmProvider
from .errors import LlmConfigurationError
from .mock import MockLlmProvider
from .openai_provider import OpenAiLlmProvider


def create_provider(provider_name: str | None = None) -> LlmProvider:
    """Buat provider sesuai nama; error jelas bila nama tidak dikenali."""
    name = (provider_name or settings.LLM_PROVIDER).strip().lower()

    if name == "openai":
        return OpenAiLlmProvider()
    if name == "mock":
        return MockLlmProvider()

    raise LlmConfigurationError(
        f"LLM_PROVIDER '{name}' tidak dikenali. Pilih 'openai' atau 'mock'."
    )


def is_llm_configured() -> bool:
    """Cek aman untuk endpoint konfigurasi publik (tanpa secret)."""
    try:
        create_provider().validate_configuration()
        return True
    except Exception:
        return False
