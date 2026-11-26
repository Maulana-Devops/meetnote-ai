"""Provider diarisasi lokal opsional memakai pyannote community-1 (Fase 1).

Token Hugging Face dibaca dari environment (``PYANNOTE_TOKEN``) dan tidak
pernah ditulis ke repo/log. Telemetri dimatikan dengan
``PYANNOTE_METRICS_ENABLED=0`` sebelum library di-import.

Provider ini OPT-IN: default tetap ``mock`` untuk CI dan demo tanpa kredensial.
Pengguna wajib menerima conditions model di Hugging Face sebelum memakainya.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Protocol

from ...core.config import settings
from .base import DiarizationProvider, DiarizationResult, DiarizationTurn
from .errors import (
    DiarizationConfigurationError,
    DiarizationInvalidResultError,
    DiarizationProviderError,
    DiarizationUnsupportedFormatError,
)

_SUPPORTED_EXTENSIONS = {".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}


class _PipelineFactory(Protocol):
    """Bentuk minimal `Pipeline.from_pretrained` yang dipakai provider."""

    def __call__(self, model: str, token: str) -> object: ...


class PyannoteDiarizationProvider:
    """Diarisasi lokal dengan label speaker anonim dari pipeline pyannote."""

    name = "pyannote"

    def __init__(self, *, pipeline_factory: _PipelineFactory | None = None) -> None:
        self._pipeline_factory = pipeline_factory
        self._pipeline: object | None = None

    @property
    def model(self) -> str:
        return settings.PYANNOTE_MODEL

    @property
    def max_file_bytes(self) -> int:
        return settings.DIARIZATION_MAX_FILE_BYTES

    def supported_extensions(self) -> set[str]:
        return set(_SUPPORTED_EXTENSIONS)

    def validate_configuration(self) -> None:
        if not settings.PYANNOTE_MODEL.strip():
            raise DiarizationConfigurationError("PYANNOTE_MODEL belum diisi.")
        if not settings.PYANNOTE_TOKEN.get_secret_value().strip():
            raise DiarizationConfigurationError(
                "PYANNOTE_TOKEN belum diisi. Terima conditions model di Hugging Face, "
                "lalu simpan token di environment backend (bukan di repository)."
            )

    def _load_pipeline(self) -> object:
        self.validate_configuration()
        if self._pipeline is None:
            if not settings.PYANNOTE_METRICS_ENABLED:
                os.environ["PYANNOTE_METRICS_ENABLED"] = "0"

            factory: _PipelineFactory
            if self._pipeline_factory is not None:
                factory = self._pipeline_factory
            else:
                factory = _default_pipeline_factory

            token = settings.PYANNOTE_TOKEN.get_secret_value()
            try:
                self._pipeline = factory(self.model, token)
            except ImportError as exc:
                raise DiarizationConfigurationError(
                    "pyannote.audio belum terpasang. Pasang dependency opsional "
                    "di host on-prem atau pakai DIARIZATION_PROVIDER=mock."
                ) from exc
            except Exception as exc:  # noqa: BLE001 - jangan bocorkan token/error mentah
                raise DiarizationConfigurationError(
                    f"Gagal memuat pipeline pyannote ({exc.__class__.__name__})."
                ) from exc
        return self._pipeline

    def diarize(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> DiarizationResult:
        if audio_path.suffix.lower() not in self.supported_extensions():
            raise DiarizationUnsupportedFormatError(
                "Format audio tidak didukung provider pyannote."
            )
        if audio_path.stat().st_size > self.max_file_bytes:
            raise DiarizationUnsupportedFormatError(
                "Ukuran file melebihi batas provider pyannote."
            )

        pipeline = self._load_pipeline()
        try:
            output = pipeline(str(audio_path))  # type: ignore[operator]
            turns: list[DiarizationTurn] = []
            for segment, _track, speaker in output.itertracks(yield_label=True):
                start = float(segment.start)
                end = float(segment.end)
                if end <= start:
                    continue
                turns.append(
                    DiarizationTurn(
                        speaker_ref=str(speaker),
                        start_seconds=start,
                        end_seconds=end,
                    )
                )
        except DiarizationUnsupportedFormatError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DiarizationProviderError(
                f"pyannote gagal memproses audio ({exc.__class__.__name__})."
            ) from exc

        if not turns:
            raise DiarizationInvalidResultError(
                "pyannote tidak menghasilkan giliran speaker."
            )
        turns.sort(key=lambda turn: (turn.start_seconds, turn.end_seconds))
        return DiarizationResult(
            turns=turns,
            provider=self.name,
            model=self.model,
        )


def _default_pipeline_factory(model: str, token: str) -> object:
    """Import lazy: pyannote tidak diperlukan untuk mock/CI."""
    from pyannote.audio import Pipeline

    try:
        return Pipeline.from_pretrained(model, use_auth_token=token)
    except TypeError:
        # Versi pyannote yang lebih baru memakai nama parameter `token`.
        return Pipeline.from_pretrained(model, token=token)


__all__ = ["PyannoteDiarizationProvider"]
