"""Error bertipe untuk provider speech-to-text.

Semua error dibuat di backend dan pesannya aman dikirim ke client: tidak ada
API key, header Authorization, atau isi response mentah yang diposting.
"""


class SttError(Exception):
    """Induk seluruh error STT."""

    # Status HTTP yang disarankan untuk kegagalan saat validasi awal (POST).
    http_status: int = 500


class SttConfigurationError(SttError):
    """Konfigurasi provider belum lengkap (mis. API key kosong)."""

    http_status = 503


class SttAuthenticationError(SttError):
    """Provider menolak kredensial (401/403)."""

    http_status = 502


class SttRateLimitError(SttError):
    """Provider membatasi permintaan (429)."""

    http_status = 429


class SttTimeoutError(SttError):
    """Provider tidak merespons dalam batas waktu."""

    http_status = 504


class SttProviderError(SttError):
    """Provider gagal dengan error server atau respons tak terduga."""

    http_status = 502


class SttUnsupportedFormatError(SttError):
    """Format/ekstensi atau ukuran file tidak didukung provider."""

    http_status = 415


class SttInvalidResultError(SttError):
    """Respons provider kosong, bukan teks, atau timestamp tidak valid."""

    http_status = 502
