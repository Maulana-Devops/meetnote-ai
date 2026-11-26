"""Fixture mock dari environment variable untuk acceptance UI.

Tidak ada jaringan, kredensial, atau audio asli yang dipakai. Fixture ini hanya
mengisi ``MockSttProvider`` agar alur ``COMPLETED`` bisa diverifikasi di browser.
"""

import pytest

from app.core.config import settings
from app.services.stt.errors import SttConfigurationError
from app.services.stt.registry import create_provider


def test_registry_uses_segment_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings,
        "MOCK_STT_SEGMENTS_JSON",
        '[{"text":"Rapat dibuka.","start_seconds":0.0,"end_seconds":2.5}]',
    )
    monkeypatch.setattr(settings, "MOCK_STT_TEXT", "")

    result = create_provider("mock").transcribe(
        tmp_path / "dummy.wav", "dummy.wav", "audio/wav"
    )

    assert result.provider == "mock"
    assert result.model == "mock-1"
    assert result.has_timestamps is True
    assert [segment.text for segment in result.segments] == ["[MOCK] Rapat dibuka."]
    assert result.segments[0].start_seconds == 0.0
    assert result.segments[0].end_seconds == 2.5


def test_registry_uses_text_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MOCK_STT_SEGMENTS_JSON", "")
    monkeypatch.setattr(settings, "MOCK_STT_TEXT", "Ringkasan tanpa timestamp.")

    result = create_provider("mock").transcribe(
        tmp_path / "dummy.wav", "dummy.wav", "audio/wav"
    )

    assert result.text == "[MOCK] Ringkasan tanpa timestamp."
    assert result.has_timestamps is False
    assert result.segments == []


def test_registry_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(settings, "MOCK_STT_SEGMENTS_JSON", "{bukan json}")
    monkeypatch.setattr(settings, "MOCK_STT_TEXT", "")

    with pytest.raises(SttConfigurationError, match="JSON"):
        create_provider("mock")


def test_registry_rejects_invalid_segment_range(monkeypatch):
    monkeypatch.setattr(
        settings,
        "MOCK_STT_SEGMENTS_JSON",
        '[{"text":"A","start_seconds":3.0,"end_seconds":1.0}]',
    )
    monkeypatch.setattr(settings, "MOCK_STT_TEXT", "")

    with pytest.raises(SttConfigurationError, match="lebih kecil"):
        create_provider("mock")
