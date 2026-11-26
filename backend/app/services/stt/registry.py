"""Pemilih provider STT berdasarkan konfigurasi backend."""

import json
from numbers import Real

from ...core.config import settings
from .base import SttProvider, SttSegment
from .errors import SttConfigurationError
from .faster_whisper_provider import FasterWhisperSttProvider
from .mock import MockSttProvider
from .openai_provider import OpenAISttProvider
from .whisper_cpp_provider import WhisperCppSttProvider


def _mock_segments_from_env(raw: str) -> list[SttSegment]:
    """Parse fixture segmen untuk acceptance UI; bukan hasil transkripsi asli."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SttConfigurationError("MOCK_STT_SEGMENTS_JSON bukan JSON yang valid.") from exc

    if not isinstance(payload, list) or not payload:
        raise SttConfigurationError("MOCK_STT_SEGMENTS_JSON harus berisi array segmen.")

    segments: list[SttSegment] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SttConfigurationError(
                f"MOCK_STT_SEGMENTS_JSON indeks {index} bukan objek."
            )
        text = item.get("text")
        start = item.get("start_seconds")
        end = item.get("end_seconds")
        if (
            not isinstance(text, str)
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, Real)
            or not isinstance(end, Real)
        ):
            raise SttConfigurationError(
                f"MOCK_STT_SEGMENTS_JSON indeks {index} butuh text dan "
                "start_seconds/end_seconds berupa angka."
            )
        if start >= end:
            raise SttConfigurationError(
                f"MOCK_STT_SEGMENTS_JSON indeks {index}: start_seconds harus lebih kecil dari end_seconds."
            )
        segments.append(
            SttSegment(text=text, start_seconds=float(start), end_seconds=float(end))
        )
    return segments


def _create_mock_provider() -> MockSttProvider:
    """Buat mock kosong atau isi fixture dari env var untuk pengujian UI."""
    raw_segments = settings.MOCK_STT_SEGMENTS_JSON.strip()
    if raw_segments:
        return MockSttProvider(segments=_mock_segments_from_env(raw_segments))

    text = settings.MOCK_STT_TEXT.strip()
    if text:
        return MockSttProvider(text=text)

    return MockSttProvider()


def create_provider(provider_name: str | None = None) -> SttProvider:
    """Buat provider sesuai nama. Lempar error jelas jika nama tidak dikenali."""
    name = (provider_name or settings.STT_PROVIDER).strip().lower()

    if name == "openai":
        return OpenAISttProvider()
    if name == "mock":
        return _create_mock_provider()
    if name in {"faster_whisper", "local"}:
        # `local` adalah alias singkat; keduanya memakai adapter yang sama.
        return FasterWhisperSttProvider()
    if name == "whisper_cpp":
        return WhisperCppSttProvider()

    raise SttConfigurationError(
        f"STT_PROVIDER '{name}' tidak dikenali. Pilih 'mock', 'openai', "
        "'faster_whisper'/'local', atau 'whisper_cpp'."
    )


def is_stt_configured() -> bool:
    """Cek aman untuk endpoint konfigurasi publik (tanpa membocorkan secret)."""
    try:
        provider = create_provider()
        provider.validate_configuration()
        return True
    except Exception:
        return False
