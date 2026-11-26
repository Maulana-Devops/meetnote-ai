"""Metrik benchmark Bahasa Indonesia tanpa dependency tambahan (Fase 1).

Fungsi di sini murni dan deterministik. Angka hanya boleh dipublikasikan
setelah diukur pada korpus yang sah; helper ini tidak membuat klaim kualitas.

DER di sini adalah **approximate frame-level DER** dengan pemetaan speaker
greedy. Ini cukup untuk regressions lokal, bukan pengganti evaluasi pyannote
resmi. Methodologinya didokumentasikan di `docs/BENCHMARK_METHOD.md`.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Mapping

_SOURCE_REF_RE = re.compile(r"^audio#t=(\d+\.\d{3})-(\d+\.\d{3})$")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def levenshtein(reference: list[str], hypothesis: list[str]) -> int:
    """Jarak edit dasar dengan memori O(min(n, m))."""
    if reference == hypothesis:
        return 0
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)

    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference

    previous = list(range(len(hypothesis) + 1))
    for index, ref_item in enumerate(reference, start=1):
        current = [index]
        for column, hyp_item in enumerate(hypothesis, start=1):
            cost = 0 if ref_item == hyp_item else 1
            current.append(
                min(
                    current[column - 1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """CER; whitespace diabaikan, tanda baca ikut dihitung."""
    ref_chars = [char for char in reference if not char.isspace()]
    hyp_chars = [char for char in hypothesis if not char.isspace()]
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    return levenshtein(ref_chars, hyp_chars) / len(ref_chars)


def word_error_rate(reference: str, hypothesis: str) -> float:
    r"""WER dengan token `\w+` case-insensitive."""
    ref_words = [word.casefold() for word in _WORD_RE.findall(reference)]
    hyp_words = [word.casefold() for word in _WORD_RE.findall(hypothesis)]
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return levenshtein(ref_words, hyp_words) / len(ref_words)


def is_valid_source_ref(value: str) -> bool:
    """Source_ref harus berupa rentang waktu relatif, bukan path/file pengguna."""
    match = _SOURCE_REF_RE.fullmatch(value or "")
    if not match:
        return False
    return float(match.group(1)) <= float(match.group(2))


def _as_turns(items: Iterable[Mapping[str, object]]) -> list[tuple[str, float, float]]:
    turns: list[tuple[str, float, float]] = []
    for item in items:
        speaker = str(item.get("speaker") or item.get("speaker_ref") or "").strip()
        start = float(item.get("start_seconds", 0))
        end = float(item.get("end_seconds", 0))
        if speaker and end > start:
            turns.append((speaker, start, end))
    return turns


def diarization_error_rate(
    reference_turns: Iterable[Mapping[str, object]],
    hypothesis_turns: Iterable[Mapping[str, object]],
    *,
    frame_seconds: float = 0.1,
    collar_seconds: float = 0.25,
) -> float:
    """Approximate frame-level DER dengan pemetaan speaker greedy."""
    if frame_seconds <= 0:
        raise ValueError("frame_seconds harus > 0")

    reference = _as_turns(reference_turns)
    hypothesis = _as_turns(hypothesis_turns)
    if not reference:
        return 0.0 if not hypothesis else 1.0

    # Pemetaan sederhana: pasangkan label hyp ke label ref dengan overlap terbesar.
    overlap: Counter[tuple[str, str]] = Counter()
    for hyp_speaker, hyp_start, hyp_end in hypothesis:
        for ref_speaker, ref_start, ref_end in reference:
            shared = min(hyp_end, ref_end) - max(hyp_start, ref_start)
            if shared > 0:
                overlap[(ref_speaker, hyp_speaker)] += shared

    mapping: dict[str, str] = {}
    used: set[str] = set()
    for (ref_speaker, hyp_speaker), _score in overlap.most_common():
        if hyp_speaker not in mapping and ref_speaker not in used:
            mapping[hyp_speaker] = ref_speaker
            used.add(ref_speaker)

    end_time = max(
        max(end for _speaker, _start, end in reference),
        max((end for _speaker, _start, end in hypothesis), default=0.0),
    )
    frames = int(end_time / frame_seconds) + 1
    missed = false_alarm = confusion = total_reference = 0

    for frame in range(frames):
        center = frame * frame_seconds + frame_seconds / 2
        ref_speakers = {
            speaker
            for speaker, start, end in reference
            if start - collar_seconds <= center <= end + collar_seconds
        }
        hyp_speakers = {
            mapping.get(speaker, speaker)
            for speaker, start, end in hypothesis
            if start - collar_seconds <= center <= end + collar_seconds
        }
        if ref_speakers:
            total_reference += 1
        if ref_speakers and not hyp_speakers:
            missed += 1
        elif hyp_speakers and not ref_speakers:
            false_alarm += 1
        elif ref_speakers and hyp_speakers and not (ref_speakers & hyp_speakers):
            confusion += 1

    if total_reference == 0:
        return 0.0 if not hypothesis else 1.0
    return (missed + false_alarm + confusion) / total_reference


__all__ = [
    "character_error_rate",
    "diarization_error_rate",
    "is_valid_source_ref",
    "levenshtein",
    "word_error_rate",
]
