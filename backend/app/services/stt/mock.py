"""Provider mock untuk test dan pengembangan lokal.

Ini BUKAN transkripsi sungguhan. Semua teks diberi awalan ``[MOCK]`` supaya
tidak mungkin tertukar dengan hasil provider asli. Dipakai oleh test otomatis
dan bisa dipilih lewat ``STT_PROVIDER=mock`` untuk mencoba alur UI tanpa API key.
"""

from pathlib import Path

from ...core.config import settings
from .base import SttResult, SttSegment, audio_source_ref
from .errors import SttError, SttInvalidResultError


class MockSttProvider:
    """Provider deterministik; bisa disuntik segmen atau error saat test."""

    name = "mock"
    _model = "mock-1"

    def __init__(
        self,
        *,
        segments: list[SttSegment] | None = None,
        text: str | None = None,
        error: SttError | None = None,
        has_timestamps: bool | None = None,
    ) -> None:
        self._segments = segments
        self._text = text
        self._error = error
        self._has_timestamps = has_timestamps

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_file_bytes(self) -> int:
        return settings.STT_MAX_FILE_BYTES

    @property
    def supports_timestamps(self) -> bool:
        return True

    def supported_extensions(self) -> set[str]:
        return {".webm", ".ogg", ".wav", ".mp3", ".m4a", ".mp4"}

    def validate_configuration(self) -> None:
        # Mock tidak memerlukan kredensial.
        return None

    def transcribe(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> SttResult:
        if self._error is not None:
            raise self._error

        language = settings.STT_LANGUAGE.strip() or "id"
        if self._segments is not None:
            segments = [
                SttSegment(
                    text=f"[MOCK] {segment.text}",
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    language=language,
                    source_ref=audio_source_ref(
                        segment.start_seconds, segment.end_seconds
                    ),
                )
                for segment in self._segments
            ]
            text = " ".join(segment.text for segment in segments)
            has_timestamps = (
                self._has_timestamps if self._has_timestamps is not None else True
            )
            return SttResult(
                text=text,
                segments=segments,
                provider=self.name,
                model=self.model,
                has_timestamps=has_timestamps,
                language=language,
            )

        if self._text:
            return SttResult(
                text=f"[MOCK] {self._text}",
                segments=[],
                provider=self.name,
                model=self.model,
                has_timestamps=False,
                language=language,
            )

        raise SttInvalidResultError(
            "Provider mock tidak diberi teks/segmen konfigurasi — respons kosong, "
            "tidak ada transkrip yang dibuat."
        )
