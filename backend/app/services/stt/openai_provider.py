"""Provider speech-to-text memakai API OpenAI Transcription.

API yang dipakai (diverifikasi dari dokumentasi resmi, 23 Nov 2026):
    POST {STT_API_BASE_URL}/audio/transcriptions
    Content-Type: multipart/form-data
        file                       = file audio
        model                      = STT_MODEL
        response_format            = verbose_json
        timestamp_granularities[]  = segment
    Authorization: Bearer {STT_API_KEY}

``verbose_json`` + granularitas ``segment`` mengembalikan ``segments`` dengan
``start``/``end``/``text``. Opsi ini didokumentasikan untuk ``whisper-1``;
model lain seperti ``gpt-transcribe`` mengembalikan teks utuh saja. Bila
segmen tidak ada, hasil ditandai ``has_timestamps=False``.

Batas dokumen provider: file maksimal 25 MB; format input meliputi flac, mp3,
mp4, mpeg, mpga, m4a, ogg, wav, dan webm.
"""

from pathlib import Path

import httpx

from ...core.config import settings
from .base import SttResult, SttSegment
from .errors import (
    SttAuthenticationError,
    SttConfigurationError,
    SttInvalidResultError,
    SttProviderError,
    SttRateLimitError,
    SttTimeoutError,
    SttUnsupportedFormatError,
)

# Documented input formats. Nama file internal hasil Sprint 2/3 memakai
# ekstensi di subset ini, jadi provider tidak perlu mengganti nama file.
_DOCUMENTED_EXTENSIONS = {
    ".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm",
}


class OpenAISttProvider:
    """Implementasi provider memakai httpx (sudah bagian dari stack FastAPI)."""

    name = "openai"

    @property
    def model(self) -> str:
        return settings.STT_MODEL

    @property
    def max_file_bytes(self) -> int:
        # Pakai batas terketat: konfigurasi aplikasi atau batas dokumen provider.
        return min(settings.MAX_AUDIO_FILE_BYTES, settings.STT_MAX_FILE_BYTES)

    @property
    def supports_timestamps(self) -> bool:
        return True  # Hanya saat model=whisper-1 + verbose_json + granularitas segment.

    def supported_extensions(self) -> set[str]:
        return set(_DOCUMENTED_EXTENSIONS)

    def validate_configuration(self) -> None:
        if not settings.STT_API_KEY.get_secret_value().strip():
            raise SttConfigurationError(
                "STT_API_KEY belum diisi. Tambahkan kredensial provider di file .env backend."
            )
        if not settings.STT_API_BASE_URL.strip():
            raise SttConfigurationError("STT_API_BASE_URL belum diisi.")
        if not settings.STT_MODEL.strip():
            raise SttConfigurationError("STT_MODEL belum diisi.")

    def transcribe(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> SttResult:
        self.validate_configuration()

        suffix = audio_path.suffix.lower()
        if suffix not in self.supported_extensions():
            raise SttUnsupportedFormatError(
                f"Ekstensi '{suffix or 'tanpa ekstensi'}' tidak didukung provider STT."
            )
        file_size = audio_path.stat().st_size
        if file_size > self.max_file_bytes:
            raise SttUnsupportedFormatError(
                f"Ukuran file {file_size} byte melebihi batas provider "
                f"{self.max_file_bytes} byte."
            )

        url = f"{settings.STT_API_BASE_URL.rstrip('/')}/audio/transcriptions"
        api_key = settings.STT_API_KEY.get_secret_value()
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }

        try:
            with audio_path.open("rb") as audio_file:
                response = httpx.post(
                    url,
                    headers=headers,
                    files={"file": (filename, audio_file, mime_type or "application/octet-stream")},
                    data=data,
                    timeout=settings.STT_TIMEOUT_SECONDS,
                )
        except httpx.TimeoutException as exc:
            raise SttTimeoutError(
                f"Provider STT tidak merespons dalam {settings.STT_TIMEOUT_SECONDS:.0f} detik."
            ) from exc
        except httpx.HTTPError as exc:
            raise SttProviderError(f"Gagal menghubungi provider STT: {exc.__class__.__name__}") from exc

        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: httpx.Response) -> SttResult:
        status = response.status_code
        if status in (401, 403):
            raise SttAuthenticationError(
                "Provider STT menolak kredensial (periksa STT_API_KEY)."
            )
        if status == 429:
            raise SttRateLimitError("Provider STT membatasi permintaan (rate limit). Coba lagi nanti.")
        if status in (408, 504):
            raise SttTimeoutError("Provider STT mengalami timeout.")
        if status >= 400:
            # Kirim ringkasan aman; jangan pernah mengembalikan header/request.
            raise SttProviderError(f"Provider STT gagal (HTTP {status}).")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SttProviderError("Provider STT mengembalikan respons bukan JSON.") from exc

        if not isinstance(payload, dict):
            raise SttProviderError("Format respons provider STT tidak dikenali.")

        text = str(payload.get("text") or "").strip()
        raw_segments = payload.get("segments")
        segments: list[SttSegment] = []

        if isinstance(raw_segments, list):
            for index, item in enumerate(raw_segments):
                if not isinstance(item, dict):
                    raise SttInvalidResultError(f"Segmen #{index + 1} bukan objek.")
                segment_text = str(item.get("text") or "").strip()
                if not segment_text:
                    # Segmen kosong bukan alasan untuk menganggap transkrip gagal;
                    # lewati, tetapi teks utuh tetap harus ada.
                    continue
                try:
                    start = float(item.get("start", 0))
                    end = float(item.get("end", 0))
                except (TypeError, ValueError) as exc:
                    raise SttInvalidResultError(
                        f"Timestamp segmen #{index + 1} tidak valid."
                    ) from exc
                segments.append(
                    SttSegment(text=segment_text, start_seconds=start, end_seconds=end)
                )

        if not text and not segments:
            raise SttInvalidResultError(
                "Provider STT mengembalikan transkrip kosong — tidak ada teks yang disimpan."
            )

        # Validasi timestamp: negatif atau end < start ditolak, bukan dibungkam.
        for index, segment in enumerate(segments):
            if segment.start_seconds < 0 or segment.end_seconds < 0:
                raise SttInvalidResultError(f"Segmen #{index + 1} memiliki timestamp negatif.")
            if segment.end_seconds < segment.start_seconds:
                raise SttInvalidResultError(
                    f"Segmen #{index + 1} memiliki waktu akhir sebelum waktu mulai."
                )

        return SttResult(
            text=text or " ".join(segment.text for segment in segments),
            segments=segments,
            provider="openai",
            model=str(payload.get("model") or settings.STT_MODEL),
            has_timestamps=bool(segments),
        )
