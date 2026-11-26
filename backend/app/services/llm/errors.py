"""Error bertipe untuk provider LLM.

Pesan di sini aman dikirim ke frontend: tidak memuat API key, header
Authorization, prompt mentah, atau isi response provider yang belum disaring.
"""


class LlmError(Exception):
    """Induk seluruh error provider LLM."""

    http_status: int = 500


class LlmConfigurationError(LlmError):
    """Konfigurasi/kredensial belum lengkap."""

    http_status = 503


class LlmAuthenticationError(LlmError):
    """Provider menolak kredensial (401/403)."""

    http_status = 502


class LlmRateLimitError(LlmError):
    """Provider membatasi permintaan (429)."""

    http_status = 429


class LlmTimeoutError(LlmError):
    """Provider tidak merespons sebelum batas waktu."""

    http_status = 504


class LlmProviderError(LlmError):
    """Provider gagal atau mengembalikan respons tak terduga."""

    http_status = 502


class LlmInvalidResultError(LlmError):
    """Respons provider tidak memenuhi kontrak ringkasan/action items."""

    http_status = 502
