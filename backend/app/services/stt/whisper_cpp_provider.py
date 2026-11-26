"""Provider STT lokal opsional memakai whisper-server (whisper.cpp).

Server memakai API kompatibel OpenAI Transcription, sehingga tidak perlu
dependency Python tambahan. whisper.cpp CLI menerima WAV 16-bit/mono secara
default; provider ini memeriksa header WAV sebelum mengirim file dan memberi
pesan jelas bila audio perlu dikonversi ke 16 kHz mono.
"""

from __future__ import annotations

import struct
from pathlib import Path

import httpx

from ...core.config import settings
from .base import SttResult, SttSegment, audio_source_ref
from .errors import (
    SttConfigurationError,
    SttInvalidResultError,
    SttProviderError,
    SttTimeoutError,
    SttUnsupportedFormatError,
)


def _is_pcm16_mono_wav(path: Path) -> bool:
    """Cek header WAV dasar: RIFF/WAVE, PCM, 1 kanal, 16-bit."""
    try:
        with path.open("rb") as handle:
            header = handle.read(44)
    except OSError:
        return False
    if len(header) < 44 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        return False
    # Cari chunk 'fmt ' dalam batas header awal yang dibaca.
    offset = 12
    while offset + 8 <= len(header):
        chunk_id = header[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", header, offset + 4)[0]
        body = offset + 8
        if chunk_id == b"fmt " and body + 16 <= len(header):
            audio_format, channels, _rate, _byte_rate, _block_align, bits = (
                struct.unpack_from("<HHIIHH", header, body)
            )
            return audio_format == 1 and channels == 1 and bits == 16
        offset = body + chunk_size + (chunk_size % 2)
    return False


class WhisperCppSttProvider:
    """Adapter HTTP untuk whisper-server; tidak memakai API key cloud."""

    name = "whisper_cpp"

    @property
    def model(self) -> str:
        return settings.WHISPER_CPP_MODEL

    @property
    def max_file_bytes(self) -> int:
        return min(settings.MAX_AUDIO_FILE_BYTES, settings.STT_MAX_FILE_BYTES)

    @property
    def supports_timestamps(self) -> bool:
        return True

    def supported_extensions(self) -> set[str]:
        return {".wav"}

    def validate_configuration(self) -> None:
        if not settings.WHISPER_CPP_BASE_URL.strip():
            raise SttConfigurationError("WHISPER_CPP_BASE_URL belum diisi.")
        if not settings.WHISPER_CPP_MODEL.strip():
            raise SttConfigurationError("WHISPER_CPP_MODEL belum diisi.")

    def transcribe(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> SttResult:
        self.validate_configuration()
        if audio_path.suffix.lower() != ".wav" or not _is_pcm16_mono_wav(audio_path):
            raise SttUnsupportedFormatError(
                "whisper.cpp memerlukan WAV PCM 16-bit mono. "
                "Konversi rekaman ke 16 kHz mono sebelum diproses."
            )
        if audio_path.stat().st_size > self.max_file_bytes:
            raise SttUnsupportedFormatError("Ukuran file melebihi batas yang diizinkan.")

        language = settings.STT_LANGUAGE.strip().lower() or "id"
        url = f"{settings.WHISPER_CPP_BASE_URL.rstrip('/')}/audio/transcriptions"
        data = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
            "language": language,
        }
        try:
            with audio_path.open("rb") as audio_file:
                response = httpx.post(
                    url,
                    files={"file": (filename, audio_file, "audio/wav")},
                    data=data,
                    timeout=settings.STT_TIMEOUT_SECONDS,
                )
        except httpx.TimeoutException as exc:
            raise SttTimeoutError("whisper-server tidak merespons tepat waktu.") from exc
        except httpx.HTTPError as exc:
            raise SttProviderError(
                f"Gagal menghubungi whisper-server ({exc.__class__.__name__})."
            ) from exc

        if response.status_code >= 400:
            raise SttProviderError(
                f"whisper-server gagal memproses audio (HTTP {response.status_code})."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SttProviderError("whisper-server mengembalikan respons bukan JSON.") from exc
        if not isinstance(payload, dict):
            raise SttProviderError("Format respons whisper-server tidak dikenali.")

        raw_segments = payload.get("segments")
        segments: list[SttSegment] = []
        if isinstance(raw_segments, list):
            for index, item in enumerate(raw_segments):
                if not isinstance(item, dict):
                    raise SttInvalidResultError(f"Segmen #{index + 1} bukan objek.")
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                try:
                    start = float(item.get("start", 0))
                    end = float(item.get("end", 0))
                except (TypeError, ValueError) as exc:
                    raise SttInvalidResultError(
                        f"Timestamp segmen #{index + 1} tidak valid."
                    ) from exc
                if start < 0 or end < start:
                    raise SttInvalidResultError(
                        f"Segmen #{index + 1} memiliki timestamp tidak valid."
                    )
                segments.append(
                    SttSegment(
                        text=text,
                        start_seconds=start,
                        end_seconds=end,
                        language=language,
                        source_ref=audio_source_ref(start, end),
                    )
                )

        text = str(payload.get("text") or "").strip()
        if not segments and not text:
            raise SttInvalidResultError("whisper-server mengembalikan transkrip kosong.")
        if not segments:
            segments = [
                SttSegment(
                    text=text,
                    start_seconds=0.0,
                    end_seconds=0.0,
                    language=language,
                )
            ]
            has_timestamps = False
        else:
            has_timestamps = True

        return SttResult(
            text=text or " ".join(segment.text for segment in segments),
            segments=segments,
            provider=self.name,
            model=self.model,
            has_timestamps=has_timestamps,
            language=language,
        )


__all__ = ["WhisperCppSttProvider"]
