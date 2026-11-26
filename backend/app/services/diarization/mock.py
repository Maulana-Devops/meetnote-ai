"""Provider diarisasi deterministik untuk test dan percobaan lokal.

Ini BUKAN diarisasi sungguhan. Provider selalu melaporkan ``provider="mock"``
dan tidak pernah menyamar sebagai hasil cloud. Test menyuntik turns lewat
konstruktor sehingga perilakunya sepenuhnya deterministik.
"""

from pathlib import Path

from ...core.config import settings
from .base import DiarizationProvider, DiarizationResult, DiarizationTurn
from .errors import DiarizationError


class MockDiarizationProvider:
    """Provider mock dengan speaker turns yang bisa diatur test."""

    name = "mock"
    _model = "mock-1"

    def __init__(
        self,
        *,
        turns: list[DiarizationTurn] | None = None,
        error: DiarizationError | None = None,
        supported_extensions: set[str] | None = None,
    ) -> None:
        self._turns = turns
        self._error = error
        self._extensions = supported_extensions

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_file_bytes(self) -> int:
        return settings.DIARIZATION_MAX_FILE_BYTES

    def supported_extensions(self) -> set[str]:
        if self._extensions is not None:
            return self._extensions
        return {".webm", ".ogg", ".wav", ".mp3", ".m4a", ".mp4"}

    def validate_configuration(self) -> None:
        # Mock tidak memerlukan kredensial.
        return None

    def diarize(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> DiarizationResult:
        if self._error is not None:
            raise self._error

        turns = self._turns if self._turns is not None else [
            DiarizationTurn("0", 0.0, 2.0),
            DiarizationTurn("1", 2.0, 4.0),
        ]
        return DiarizationResult(
            turns=list(turns),
            provider=self.name,
            model=self.model,
        )
