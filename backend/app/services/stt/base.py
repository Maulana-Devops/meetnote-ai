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
    """Satu segmen transkrip dengan timestamp dari provider (jika ada).

    ``language`` dan ``source_ref`` dipakai kontrak Fase 1. ``source_ref``
    berbentuk referensi relatif terhadap rekaman meeting, bukan path absolut
    ataupun nama file pengguna, sehingga aman ditampilkan ke UI.
    """

    text: str
    start_seconds: float
    end_seconds: float
    language: str = ""
    source_ref: str = ""


def audio_source_ref(start_seconds: float, end_seconds: float) -> str:
    """Buat referensi audio berbasis waktu untuk satu meeting (= satu rekaman)."""
    start = max(0.0, float(start_seconds))
    end = max(start, float(end_seconds))
    return f"audio#t={start:.3f}-{end:.3f}"


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
    language: str = ""

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
