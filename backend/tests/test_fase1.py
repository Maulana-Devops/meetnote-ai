"""Pengujian Fase 1 — Bahasa Indonesia & provider lokal.

Semua percobaan memakai fixture buatan dan provider mock/fake. Tidak ada model
besar yang diunduh, tidak ada API key, dan tidak ada jaringan yang dipakai.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services.diarization.pyannote_provider import PyannoteDiarizationProvider
from app.services.indonesian import (
    character_error_rate,
    diarization_error_rate,
    is_valid_source_ref,
    normalize_segments,
    normalize_text,
    word_error_rate,
)
from app.services.llm.base import SYSTEM_PROMPT, SummaryInput
from app.services.stt.base import SttProvider, SttSegment
from app.services.stt.errors import SttUnsupportedFormatError
from app.services.stt.faster_whisper_provider import FasterWhisperSttProvider
from app.services.stt.mock import MockSttProvider
from app.services.stt.registry import create_provider
from app.services.summary.prompts import (
    SUMMARY_SYSTEM_PROMPT_ID,
    build_summary_system_prompt,
    is_indonesian,
)


@dataclass
class _FakeSegment:
    text: str
    start: float
    end: float


class _FakeWhisperModel:
    """Pengganti WhisperModel; tidak memuat bobot atau ffmpeg."""

    def transcribe(self, _path: str, **_kwargs: object) -> tuple[object, object]:
        segments = [
            _FakeSegment("yg penting rapat", 0.0, 2.0),
            _FakeSegment("meetnote dg kpi", 2.0, 4.0),
        ]
        return iter(segments), SimpleNamespace(language="id")


def _fake_factory(**kwargs: object) -> object:
    assert kwargs["device"] == settings.STT_DEVICE
    assert kwargs["compute_type"] == settings.STT_COMPUTE_TYPE
    return _FakeWhisperModel()


def _dummy_wav(tmp_path: Path) -> Path:
    path = tmp_path / "rekaman.wav"
    path.write_bytes(b"RIFF0000WAVEfmt 0000")
    return path


def _assert_stt_contract(provider: SttProvider, path: Path) -> None:
    """Satu kontrak yang sama dipakai mock dan provider lokal."""
    assert isinstance(provider, SttProvider)
    provider.validate_configuration()
    assert provider.supported_extensions()
    result = provider.transcribe(path, "rekaman.wav", "audio/wav")

    assert result.has_content
    assert result.has_timestamps
    assert result.provider == provider.name
    assert result.segments
    for segment in result.segments:
        assert segment.text.strip()
        assert segment.language == "id"
        assert is_valid_source_ref(segment.source_ref)
        assert 0 <= segment.start_seconds < segment.end_seconds


def test_kontrak_stt_mock(tmp_path: Path) -> None:
    provider = MockSttProvider(
        segments=[SttSegment("Halo semua.", 0.0, 2.0)]
    )
    _assert_stt_contract(provider, _dummy_wav(tmp_path))


def test_kontrak_stt_lokal_sama_dengan_mock(tmp_path: Path) -> None:
    provider = FasterWhisperSttProvider(model_factory=_fake_factory)
    _assert_stt_contract(provider, _dummy_wav(tmp_path))


def test_registry_menerima_nama_provider_fase1() -> None:
    assert create_provider("mock").name == "mock"
    assert create_provider("faster_whisper").name == "faster_whisper"
    assert create_provider("local").name == "faster_whisper"
    assert create_provider("whisper_cpp").name == "whisper_cpp"


def test_normalizer_memakai_kamus_dan_eyd_sederhana() -> None:
    result = normalize_text(
        "yg penting meetnote dg kpi ,  bukan  tdk jelas",
        vocab={"meetnote": "MeetNote", "kpi": "KPI"},
    )
    assert result == "Yang penting MeetNote dengan KPI, bukan tidak jelas"


def test_normalizer_tidak_mengubah_source_ref() -> None:
    segment = SttSegment(
        "halo semua",
        1.0,
        3.0,
        language="id",
        source_ref="audio#t=1.000-3.000",
    )
    normalized = normalize_segments([segment])[0]
    assert normalized.text == "Halo semua"
    assert normalized.source_ref == segment.source_ref
    assert normalized.language == "id"


def test_metrik_cer_wer_dan_source_ref() -> None:
    assert character_error_rate("halo", "halo") == 0.0
    assert character_error_rate("halo", "hala") == pytest.approx(0.25)
    assert word_error_rate("halo dunia", "halo dunia") == 0.0
    assert word_error_rate("halo dunia", "halo ada") == pytest.approx(0.5)
    assert is_valid_source_ref("audio#t=0.500-2.250")
    assert not is_valid_source_ref("C:/Users/private/rekaman.wav")
    assert not is_valid_source_ref("audio#t=2.000-1.000")


def test_der_penyederhanaan_dapat_membedakan_kehilangan() -> None:
    reference = [{"speaker": "A", "start_seconds": 0, "end_seconds": 2}]
    identical = [{"speaker": "X", "start_seconds": 0, "end_seconds": 2}]
    missing: list[dict[str, object]] = []
    assert diarization_error_rate(reference, identical) == pytest.approx(0.0)
    assert diarization_error_rate(reference, missing) == pytest.approx(1.0)


def test_prompt_ringkasan_memilih_bahasa_indonesia() -> None:
    id_input = SummaryInput("Rapat", [], output_language="Indonesia")
    en_input = SummaryInput("Meeting", [], output_language="English")
    assert is_indonesian("ID")
    assert build_summary_system_prompt(id_input) == SUMMARY_SYSTEM_PROMPT_ID
    assert build_summary_system_prompt(en_input) == SYSTEM_PROMPT
    assert "Keputusan" in SUMMARY_SYSTEM_PROMPT_ID
    assert "Tindak lanjut" in SUMMARY_SYSTEM_PROMPT_ID
    assert "PIC" in SUMMARY_SYSTEM_PROMPT_ID
    assert "Tenggat" in SUMMARY_SYSTEM_PROMPT_ID
    assert "Catatan penting" in SUMMARY_SYSTEM_PROMPT_ID


class _FakeDiarization:
    def itertracks(self, yield_label: bool = True) -> object:
        assert yield_label is True
        return iter([(SimpleNamespace(start=0.0, end=2.0), None, "SPEAKER_00")])


def test_pyannote_provider_meminat_factory_tanpa_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PYANNOTE_TOKEN", SecretStr("hf_fake_token_value"))
    monkeypatch.setattr(settings, "PYANNOTE_METRICS_ENABLED", False)

    def factory(model: str, token: str) -> object:
        assert model == settings.PYANNOTE_MODEL
        assert token == "hf_fake_token_value"
        return lambda _path: _FakeDiarization()

    provider = PyannoteDiarizationProvider(pipeline_factory=factory)
    result = provider.diarize(_dummy_wav(tmp_path), "rekaman.wav", "audio/wav")
    assert result.provider == "pyannote"
    assert result.turns[0].speaker_ref == "SPEAKER_00"


def test_whisper_cpp_menolak_file_bukan_wav_pcm16(tmp_path: Path) -> None:
    provider = create_provider("whisper_cpp")
    bad = tmp_path / "rekaman.mp3"
    bad.write_bytes(b"not a wav")
    with pytest.raises(SttUnsupportedFormatError):
        provider.transcribe(bad, "rekaman.mp3", "audio/mpeg")
