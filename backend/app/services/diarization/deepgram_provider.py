"""Provider diarisasi memakai Deepgram Listen API.

Dokumentasi resmi diverifikasi 23 Nov 2026:
- https://developers.deepgram.com/reference/listen-file
- https://developers.deepgram.com/docs/diarization
- https://developers.deepgram.com/docs/utterances
- https://developers.deepgram.com/docs/supported-audio-formats

Request yang dipakai:
    POST {DIARIZATION_API_BASE_URL}/listen
        ?model={DIARIZATION_MODEL}
        &diarize_model={DIARIZATION_DIARIZE_MODEL}
        &utterances=true
    Authorization: Token {DIARIZATION_API_KEY}
    Content-Type: audio/{ext}
    Body: binary audio yang sudah tersimpan di storage aplikasi

Catatan penting:
- ``diarize=true`` sudah deprecated; ``diarize_model`` yang dipakai.
- ``utterances[].speaker`` adalah label speaker pada **segmen transkrip** yang
  diberi timestamp, bukan identitas dunia nyata. ``words[].speaker`` juga
  tersedia; workflow memakai keduanya sebagai speaker turns.
- Batas file terdokumentasi: 2 GB. Request lebih dari ~10 menit dapat 504.
"""

from pathlib import Path
from typing import Any, Iterator

import httpx

from ...core.config import settings
from .base import DiarizationProvider, DiarizationResult, DiarizationTurn
from .errors import (
    DiarizationAuthenticationError,
    DiarizationConfigurationError,
    DiarizationFileTooLargeError,
    DiarizationInvalidResultError,
    DiarizationProviderError,
    DiarizationRateLimitError,
    DiarizationTimeoutError,
    DiarizationUnsupportedFormatError,
)

# Format umum yang didokumentasikan Deepgram. Format yang dipakai aplikasi
# sendiri adalah subset dari daftar ini (lihat core/audio.py).
_DOCUMENTED_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp2",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".pcm",
    ".wav",
    ".webm",
}

_CONTENT_TYPE_BY_EXTENSION = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".mp2": "audio/mpeg",
    ".opus": "audio/ogg",
    ".pcm": "audio/raw",
}


def _iter_audio(path: Path, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """Stream file agar tidak perlu memuat audio besar ke memory."""
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def _content_type(path: Path, mime_type: str) -> str:
    """Pakai MIME tervalidasi aplikasi, dengan fallback berdasarkan ekstensi."""
    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith(("audio/", "video/")):
        return normalized
    return _CONTENT_TYPE_BY_EXTENSION.get(path.suffix.lower(), "application/octet-stream")


def _raise_for_status(response: httpx.Response) -> None:
    """Terjemahkan status HTTP menjadi error aman (tanpa response body)."""
    code = response.status_code
    if code in (401, 403):
        raise DiarizationAuthenticationError(
            "Provider diarisasi menolak kredensial (periksa DIARIZATION_API_KEY)."
        )
    if code == 429:
        raise DiarizationRateLimitError(
            "Provider diarisasi membatasi permintaan. Silakan coba lagi nanti."
        )
    if code in (408, 504):
        raise DiarizationTimeoutError("Provider diarisasi mengalami timeout.")
    if code == 415:
        raise DiarizationUnsupportedFormatError(
            "Format audio tidak didukung provider diarisasi."
        )
    if code >= 500:
        raise DiarizationProviderError("Provider diarisasi mengalami gangguan server.")
    if not response.is_success:
        raise DiarizationProviderError(
            f"Provider diarisasi menolak permintaan (HTTP {code})."
        )


def _as_turn(item: Any) -> DiarizationTurn | None:
    """Validasi satu item utterance/word menjadi speaker turn."""
    if not isinstance(item, dict):
        return None

    speaker = item.get("speaker")
    if speaker is None:
        # Utterance tanpa speaker: fallback ke words akan dilakukan workflow.
        return None
    if isinstance(speaker, bool) or not isinstance(speaker, (int, str)):
        raise DiarizationInvalidResultError("Provider mengembalikan referensi speaker tidak valid.")
    speaker_ref = str(speaker).strip()
    if not speaker_ref:
        raise DiarizationInvalidResultError("Provider mengembalikan referensi speaker kosong.")

    start = item.get("start")
    end = item.get("end")
    if start is None or end is None:
        raise DiarizationInvalidResultError("Provider mengembalikan timestamp diarisasi tidak lengkap.")
    try:
        start_value = float(start)
        end_value = float(end)
    except (TypeError, ValueError) as exc:
        raise DiarizationInvalidResultError(
            "Provider mengembalikan timestamp diarisasi bukan angka."
        ) from exc

    if start_value < 0 or end_value < 0:
        raise DiarizationInvalidResultError("Provider mengembalikan timestamp diarisasi negatif.")
    if end_value < start_value:
        raise DiarizationInvalidResultError(
            "Provider mengembalikan waktu akhir diarisasi sebelum waktu mulai."
        )

    return DiarizationTurn(speaker_ref, start_value, end_value)


def _parse_turns(payload: dict[str, Any]) -> list[DiarizationTurn]:
    """Ambil speaker turns dari utterances, lalu fallback ke words."""
    results = payload.get("results")
    if not isinstance(results, dict):
        raise DiarizationInvalidResultError("Respons diarisasi tidak memuat results.")

    turns: list[DiarizationTurn] = []
    utterances = results.get("utterances")
    if isinstance(utterances, list):
        for item in utterances:
            turn = _as_turn(item)
            if turn is not None:
                turns.append(turn)
    if turns:
        return sorted(turns, key=lambda turn: (turn.start_seconds, turn.end_seconds))

    # Fallback: gabungkan kata berurutan yang memiliki speaker sama.
    for channel in results.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        for alternative in channel.get("alternatives") or []:
            if not isinstance(alternative, dict):
                continue
            current: DiarizationTurn | None = None
            for word in alternative.get("words") or []:
                turn = _as_turn(word)
                if turn is None:
                    continue
                if current is not None and current.speaker_ref == turn.speaker_ref:
                    current = DiarizationTurn(
                        current.speaker_ref,
                        current.start_seconds,
                        max(current.end_seconds, turn.end_seconds),
                    )
                else:
                    if current is not None:
                        turns.append(current)
                    current = turn
            if current is not None:
                turns.append(current)

    return sorted(turns, key=lambda turn: (turn.start_seconds, turn.end_seconds))


class DeepgramDiarizationProvider:
    """Implementasi Deepgram Listen untuk diarisasi pre-recorded."""

    name = "deepgram"

    @property
    def model(self) -> str:
        return settings.DIARIZATION_MODEL

    @property
    def max_file_bytes(self) -> int:
        return settings.DIARIZATION_MAX_FILE_BYTES

    def supported_extensions(self) -> set[str]:
        return set(_DOCUMENTED_EXTENSIONS)

    def validate_configuration(self) -> None:
        if not settings.DIARIZATION_API_KEY.get_secret_value().strip():
            raise DiarizationConfigurationError(
                "DIARIZATION_API_KEY belum diisi. Tambahkan kredensial di .env backend."
            )
        if not settings.DIARIZATION_API_BASE_URL.strip():
            raise DiarizationConfigurationError("DIARIZATION_API_BASE_URL belum diisi.")
        if not settings.DIARIZATION_MODEL.strip():
            raise DiarizationConfigurationError("DIARIZATION_MODEL belum diisi.")
        if settings.DIARIZATION_DIARIZE_MODEL.strip() not in {"latest", "v1", "v2"}:
            raise DiarizationConfigurationError(
                "DIARIZATION_DIARIZE_MODEL harus salah satu dari latest, v1, atau v2."
            )
        if settings.DIARIZATION_TIMEOUT_SECONDS <= 0:
            raise DiarizationConfigurationError("DIARIZATION_TIMEOUT_SECONDS harus positif.")

    def diarize(
        self,
        audio_path: Path,
        filename: str,
        mime_type: str,
    ) -> DiarizationResult:
        self.validate_configuration()

        suffix = audio_path.suffix.lower()
        if suffix not in self.supported_extensions():
            raise DiarizationUnsupportedFormatError(
                f"Format '{suffix or 'tanpa ekstensi'}' tidak didukung provider diarisasi."
            )

        size = audio_path.stat().st_size
        if size == 0:
            raise DiarizationInvalidResultError("File rekaman kosong — tidak bisa diarisasi.")
        if size > self.max_file_bytes:
            raise DiarizationFileTooLargeError(
                f"Ukuran file {size} byte melebihi batas provider "
                f"{self.max_file_bytes} byte."
            )

        url = f"{settings.DIARIZATION_API_BASE_URL.rstrip('/')}/listen"
        params = {
            "model": settings.DIARIZATION_MODEL,
            "diarize_model": settings.DIARIZATION_DIARIZE_MODEL,
            "utterances": "true",
        }
        headers = {
            "Authorization": f"Token {settings.DIARIZATION_API_KEY.get_secret_value()}",
            "Content-Type": _content_type(audio_path, mime_type),
            "Content-Length": str(size),
        }

        try:
            with httpx.Client(timeout=settings.DIARIZATION_TIMEOUT_SECONDS) as client:
                response = client.post(
                    url,
                    params=params,
                    headers=headers,
                    content=_iter_audio(audio_path),
                )
        except httpx.TimeoutException as exc:
            raise DiarizationTimeoutError("Provider diarisasi mengalami timeout.") from exc
        except httpx.RequestError as exc:
            raise DiarizationProviderError(
                "Tidak dapat terhubung ke provider diarisasi."
            ) from exc

        _raise_for_status(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise DiarizationInvalidResultError(
                "Provider diarisasi mengembalikan respons bukan JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise DiarizationInvalidResultError("Respons diarisasi bukan objek JSON.")

        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("diarize_info"), dict):
            raise DiarizationInvalidResultError(
                "Provider tidak menjalankan diarisasi (metadata diarize_info tidak ada)."
            )

        turns = _parse_turns(payload)
        if not turns:
            raise DiarizationInvalidResultError(
                "Provider diarisasi mengembalikan respons kosong — tidak ada speaker yang disimpan."
            )

        return DiarizationResult(
            turns=turns,
            provider=self.name,
            model=self.model,
        )
