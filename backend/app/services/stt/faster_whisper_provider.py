"""Provider STT lokal memakai faster-whisper (Fase 1).

Dependency `faster-whisper` bersifat opsional dan di-import secara lazy agar CI
dan installation tanpa model tetap ringan. Model/bobot tidak disimpan di Git;
`STT_MODEL_DIR` dipakai sebagai cache/download root.

Konfigurasi utama: CPU + compute type int8 + Bahasa Indonesia + VAD. Semua
keluaran memiliki `language="id"` dan `source_ref` relatif terhadap rekaman.
Tidak ada API key dan tidak ada jaringan yang diwajibkan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from ...core.config import settings
from ..indonesian import normalize_segments
from .base import SttProvider, SttResult, SttSegment, audio_source_ref
from .errors import (
    SttConfigurationError,
    SttInvalidResultError,
    SttProviderError,
    SttUnsupportedFormatError,
)

_SUPPORTED_EXTENSIONS = {
    ".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm",
}
_VALID_DEVICES = {"cpu", "cuda"}
_VALID_COMPUTE_TYPES = {
    "int8", "int8_float16", "int8_float32", "int8_bfloat16", "float16", "float32",
}


class _WhisperModelFactory(Protocol):
    """Bentuk minimal konstruktor faster-whisper yang dipakai provider."""

    def __call__(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        download_root: str,
    ) -> object: ...


class FasterWhisperSttProvider:
    """STT lokal dengan kontrak yang sama seperti provider cloud/mock."""

    name = "faster_whisper"

    def __init__(
        self,
        *,
        model_factory: _WhisperModelFactory | None = None,
        apply_normalization: bool = True,
    ) -> None:
        # Model factory bisa disuntik test agar kontrak diuji tanpa unduh model.
        self._model_factory = model_factory
        self._apply_normalization = apply_normalization
        self._model: object | None = None

    @property
    def model(self) -> str:
        return f"{settings.STT_LOCAL_MODEL}:{settings.STT_COMPUTE_TYPE}"

    @property
    def max_file_bytes(self) -> int:
        return min(settings.MAX_AUDIO_FILE_BYTES, settings.STT_MAX_FILE_BYTES)

    @property
    def supports_timestamps(self) -> bool:
        return True

    def supported_extensions(self) -> set[str]:
        return set(_SUPPORTED_EXTENSIONS)

    def validate_configuration(self) -> None:
        if not settings.STT_LOCAL_MODEL.strip():
            raise SttConfigurationError("STT_LOCAL_MODEL belum diisi.")
        device = settings.STT_DEVICE.strip().lower()
        if device not in _VALID_DEVICES:
            raise SttConfigurationError(
                "STT_DEVICE harus 'cpu' atau 'cuda'."
            )
        compute_type = settings.STT_COMPUTE_TYPE.strip().lower()
        if compute_type not in _VALID_COMPUTE_TYPES:
            raise SttConfigurationError(
                "STT_COMPUTE_TYPE tidak dikenali. Gunakan 'int8' untuk CPU."
            )
        model_dir = Path(settings.STT_MODEL_DIR).expanduser()
        if model_dir.exists() and not model_dir.is_dir():
            raise SttConfigurationError("STT_MODEL_DIR bukan direktori.")

    def _load_model(self) -> object:
        self.validate_configuration()
        if self._model is None:
            model_dir = Path(settings.STT_MODEL_DIR).expanduser()
            model_dir.mkdir(parents=True, exist_ok=True)

            factory: _WhisperModelFactory
            if self._model_factory is not None:
                factory = self._model_factory
            else:
                factory = _default_model_factory
            try:
                self._model = factory(
                    model=settings.STT_LOCAL_MODEL.strip(),
                    device=settings.STT_DEVICE.strip().lower(),
                    compute_type=settings.STT_COMPUTE_TYPE.strip().lower(),
                    download_root=str(model_dir),
                )
            except ImportError as exc:
                raise SttConfigurationError(
                    "faster-whisper belum terpasang. Pasang dependency opsional "
                    "`faster-whisper` di host on-prem atau pakai STT_PROVIDER=mock."
                ) from exc
            except Exception as exc:  # noqa: BLE001 - pesan mentah tidak dibocorkan
                raise SttConfigurationError(
                    f"Gagal memuat model STT lokal ({exc.__class__.__name__})."
                ) from exc
        return self._model

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
                f"Ekstensi '{suffix or 'tanpa ekstensi'}' tidak didukung STT lokal."
            )
        file_size = audio_path.stat().st_size
        if file_size > self.max_file_bytes:
            raise SttUnsupportedFormatError(
                f"Ukuran file {file_size} byte melebihi batas "
                f"{self.max_file_bytes} byte."
            )

        language = settings.STT_LANGUAGE.strip().lower() or "id"
        model = self._load_model()
        try:
            generated, _info = model.transcribe(  # type: ignore[attr-defined]
                str(audio_path),
                language=language,
                vad_filter=settings.STT_VAD,
                word_timestamps=settings.STT_WORD_TIMESTAMPS,
                beam_size=5,
            )
            raw_segments = list(generated)
        except Exception as exc:  # noqa: BLE001 - jangan kirim path/internal error
            raise SttProviderError(
                f"Model STT lokal gagal memproses audio ({exc.__class__.__name__})."
            ) from exc

        segments = [
            SttSegment(
                text=str(item.text).strip(),
                start_seconds=float(item.start),
                end_seconds=float(item.end),
                language=language,
                source_ref=audio_source_ref(float(item.start), float(item.end)),
            )
            for item in raw_segments
            if str(item.text).strip()
        ]
        if not segments:
            raise SttInvalidResultError(
                "Model STT lokal tidak menghasilkan segmen teks; tidak ada transkrip yang disimpan."
            )

        for index, segment in enumerate(segments):
            if segment.start_seconds < 0 or segment.end_seconds < segment.start_seconds:
                raise SttInvalidResultError(
                    f"Segmen #{index + 1} memiliki timestamp tidak valid."
                )

        if self._apply_normalization:
            segments = normalize_segments(segments)

        return SttResult(
            text=" ".join(segment.text for segment in segments),
            segments=segments,
            provider=self.name,
            model=self.model,
            has_timestamps=True,
            language=language,
        )


def _default_model_factory(
    *,
    model: str,
    device: str,
    compute_type: str,
    download_root: str,
) -> object:
    """Import lazy: dependency tidak diperlukan untuk mock/CI."""
    from faster_whisper import WhisperModel

    return WhisperModel(
        model,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )


__all__ = ["FasterWhisperSttProvider"]
