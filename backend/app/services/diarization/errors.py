"""Error bertipe untuk provider diarisasi.

Pesan di sini aman dikirim ke frontend: tidak memuat API key, header
Authorization, atau response mentah provider.
"""


class DiarizationError(Exception):
    """Induk seluruh error diarisasi."""

    http_status: int = 500


class DiarizationConfigurationError(DiarizationError):
    """Konfigurasi/kredensial belum lengkap."""

    http_status = 503


class DiarizationAuthenticationError(DiarizationError):
    """Provider menolak kredensial (401/403)."""

    http_status = 502


class DiarizationRateLimitError(DiarizationError):
    """Provider membatasi permintaan (429)."""

    http_status = 429


class DiarizationTimeoutError(DiarizationError):
    """Provider tidak merespons sebelum batas waktu."""

    http_status = 504


class DiarizationProviderError(DiarizationError):
    """Provider gagal dengan error server atau respons tak terduga."""

    http_status = 502


class DiarizationUnsupportedFormatError(DiarizationError):
    """Format/ekstensi atau ukuran file tidak diterima provider."""

    http_status = 415


class DiarizationFileTooLargeError(DiarizationError):
    """File melebihi batas yang didokumentasikan provider."""

    http_status = 413


class DiarizationInvalidResultError(DiarizationError):
    """Respons kosong, timestamp invalid, atau referensi speaker tidak dikenali."""

    http_status = 502
