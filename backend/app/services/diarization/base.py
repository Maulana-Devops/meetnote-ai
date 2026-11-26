"""Kontrak provider diarisasi dan hasil speaker turns.

Provider dipilih lewat environment variable ``DIARIZATION_PROVIDER``. Workflow
dan API hanya bergantung pada protocol ini, bukan pada vendor tertentu.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .errors import DiarizationError


@dataclass(frozen=True)
class DiarizationTurn:
    """Satu giliran speaker dengan timestamp relatif terhadap audio.

    ``speaker_ref`` adalah pengenal dari provider (mis. "0" atau "1"). Workflow
    yang mengubahnya menjadi label anonim "Speaker 1", "Speaker 2", ...
    """

    speaker_ref: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class DiarizationResult:
    """Hasil diarisasi yang sudah dinormalisasi.

    ``turns`` hanya berisi waktu + referensi speaker. Teks transkrip tidak
    diubah atau dikirim ulang oleh provider diarisasi.
    """

    turns: list[DiarizationTurn] = field(default_factory=list)
    provider: str = "unknown"
    model: str = "unknown"

    @property
    def is_mock(self) -> bool:
        return self.provider.lower() == "mock"


@runtime_checkable
class DiarizationProvider(Protocol):
    """Antarmuka yang harus dipenuhi setiap provider diarisasi."""

    name: str
    model: str
    max_file_bytes: int

    def supported_extensions(self) -> set[str]:
        """Ekstensi file audio yang diterima provider."""
        ...

    def validate_configuration(self) -> None:
        """Cek kredensial/konfigurasi; lempar DiarizationError bila kurang."""
        ...

    def diarize(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> DiarizationResult:
        """Kirim audio yang sudah ada dan kembalikan speaker turns."""
        ...


__all__ = ["DiarizationError", "DiarizationProvider", "DiarizationResult", "DiarizationTurn"]
