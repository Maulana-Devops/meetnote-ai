"""Abstraksi speech-to-text (Sprint 4)."""

from .base import SttProvider, SttResult, SttSegment, audio_source_ref
from .errors import SttError
from .faster_whisper_provider import FasterWhisperSttProvider
from .mock import MockSttProvider
from .registry import create_provider, is_stt_configured
from .whisper_cpp_provider import WhisperCppSttProvider

__all__ = [
    "FasterWhisperSttProvider",
    "MockSttProvider",
    "SttError",
    "SttProvider",
    "SttResult",
    "SttSegment",
    "WhisperCppSttProvider",
    "audio_source_ref",
    "create_provider",
    "is_stt_configured",
]
