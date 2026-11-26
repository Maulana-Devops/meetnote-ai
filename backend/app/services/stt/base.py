"""Kontrak provider speech-to-text dan hasil transkripsi.

Provider dipilih lewat environment variable ``STT_PROVIDER``. Lapisan API dan
workflow tidak boleh mengetahui detail vendor tertentu.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .errors import SttError


@dataclass(frozen=True)
class SttSegment:
    """Satu segmen transkrip dengan timestamp dari provider (jika ada)."""

    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class SttResult:
    """Hasil transkripsi yang sudah dinormalisasi.

    ``has_timestamps`` false berarti provider hanya mengembalikan teks utuh.
    Dalam kasus itu workflow menyimpan satu segmen kecil dengan timestamp 0
    dan frontend menampilkannya sebagai "tanpa timestamp" — bukan timestamp
    palsu.
    """

    text: str
    segments: list[SttSegment] = field(default_factory=list)
    provider: str = "unknown"
    model: str = "unknown"
    has_timestamps: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip()) or any(seg.text.strip() for seg in self.segments)


@runtime_checkable
class SttProvider(Protocol):
    """Antarmuka minimal yang harus dipenuhi setiap provider."""

    name: str

    @property
    def model(self) -> str: ...

    @property
    def max_file_bytes(self) -> int: ...

    @property
    def supports_timestamps(self) -> bool: ...

    def supported_extensions(self) -> set[str]: ...

    def validate_configuration(self) -> None:
        """Lempar SttConfigurationError jika kredensial/konfigurasi kurang."""

    def transcribe(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> SttResult:
        """Transkripsikan file. Lempar subclass SttError jika gagal."""
