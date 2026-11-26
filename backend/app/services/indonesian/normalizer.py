"""Normalisasi transkrip Bahasa Indonesia tanpa dependency/model tambahan.

Fungsi di sini sengaja konservatif: hanya memperbaiki pola yang jelas salah
dalam transkrip ASR (spasi, singkatan umum, ejaan tidak baku yang sering
muncul, dan kamus organisasi). Tidak ada terjemahan, tidak ada pengarangan
informasi, dan tidak ada perubahan pada ID/time reference segmen.

Ini BUKAN pemeriksa EYD V otomatis yang sempurna. Hasil tetap harus ditinjau
pengguna (human-in-the-loop).
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from ...core.config import settings

# Bentuk informal yang sering muncul pada ASR Bahasa Indonesia. Hanya pola
# dengan padanan tunggal yang dimasukkan; singkatan kontekstual diserahkan
# ke kamus organisasi.
_INFORMAL: dict[str, str] = {
    "yg": "yang",
    "dg": "dengan",
    "dgn": "dengan",
    "utk": "untuk",
    "krn": "karena",
    "tdk": "tidak",
    "jdi": "jadi",
    "sdh": "sudah",
    "blm": "belum",
    "pd": "pada",
    "dr": "dari",
}

_WS_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[])\s+")
_SPACE_BEFORE_CLOSE_RE = re.compile(r"\s+([)\]])")
_GROUPED_NUMBER_RE = re.compile(r"(?<=\d)\s+(?=\d{3}\b)")
_SENTENCE_START_RE = re.compile(r"(^|[.!?]\s+)([a-z])")


@lru_cache(maxsize=8)
def load_vocab(path: str | None = None) -> Mapping[str, str]:
    """Muat kamus `kunci=nilai` sekali; aman bila file tidak ada."""
    target = Path(path or settings.INDONESIAN_VOCAB_PATH)
    if not target.is_file():
        return {}

    entries: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            entries[key.casefold()] = value
    return entries


def _replace_words(text: str, mapping: Mapping[str, str]) -> str:
    if not mapping or not text:
        return text
    keys = sorted((key.casefold() for key in mapping), key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(key) for key in keys) + r")\b", re.IGNORECASE)

    def _substitute(match: re.Match[str]) -> str:
        original = match.group(0)
        canonical = mapping[original.casefold()]
        if original[:1].isupper():
            canonical = canonical[:1].upper() + canonical[1:]
        return canonical

    return pattern.sub(_substitute, text)


def normalize_text(
    text: str,
    *,
    vocab: Mapping[str, str] | None = None,
    apply_eyd: bool = True,
) -> str:
    """Bersihkan satu potong teks transkrip tanpa mengubah makna."""
    if not text:
        return ""

    result = _WS_RE.sub(" ", str(text).replace("\r\n", "\n")).strip()
    if apply_eyd:
        result = _replace_words(result, _INFORMAL)
        result = _replace_words(
            result, load_vocab() if vocab is None else vocab
        )

    result = _GROUPED_NUMBER_RE.sub("", result)
    result = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", result)
    result = _SPACE_AFTER_OPEN_RE.sub(r"\1", result)
    result = _SPACE_BEFORE_CLOSE_RE.sub(r"\1", result)
    result = re.sub(r"\s*,\s*", ", ", result)
    result = re.sub(r"\s+:\s*", ": ", result)
    result = _WS_RE.sub(" ", result).strip()
    result = _SENTENCE_START_RE.sub(
        lambda match: match.group(1) + match.group(2).upper(), result
    )
    return result


def normalize_segments(
    segments: list,
    *,
    vocab: Mapping[str, str] | None = None,
    apply_eyd: bool = True,
) -> list:
    """Normalisasi teks segmen; ID, waktu, bahasa, dan source_ref dipertahankan."""
    return [
        replace(
            segment,
            text=normalize_text(segment.text, vocab=vocab, apply_eyd=apply_eyd),
        )
        for segment in segments
    ]
