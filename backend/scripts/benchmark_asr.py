"""Benchmark ASR/DER lokal dengan manifest JSONL (Fase 1).

Contoh baris manifest:

    {"audio_path": "rec.wav", "reference_text": "Halo semua, mulai rapat.",
     "reference_segments": [{"text": "Halo semua.", "start_seconds": 0, "end_seconds": 2}],
     "reference_diarization": [{"speaker": "A", "start_seconds": 0, "end_seconds": 2}]}

Jalankan:

    python backend/scripts/benchmark_asr.py --manifest manifest.jsonl --provider mock
    python backend/scripts/benchmark_asr.py --manifest manifest.jsonl --provider faster_whisper

Script tidak mengunduh model, tidak memakai API key, dan tidak menulis file
kecuali `--output` diberikan. Angka dari provider `mock` ditandai jelas dan
bukan klaim kualitas. Lihat `docs/BENCHMARK_METHOD.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.indonesian import (  # noqa: E402
    character_error_rate,
    diarization_error_rate,
    is_valid_source_ref,
    normalize_text,
    word_error_rate,
)
from app.services.stt.registry import create_provider  # noqa: E402


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Baris {line_number} bukan JSON valid.") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Baris {line_number} bukan objek JSON.")
        if not str(payload.get("reference_text") or "").strip():
            raise ValueError(f"Baris {line_number} tidak punya reference_text.")
        if not str(payload.get("audio_path") or "").strip():
            raise ValueError(f"Baris {line_number} tidak punya audio_path.")
        rows.append(payload)
    if not rows:
        raise ValueError("Manifest kosong.")
    return rows


def _display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def _configure_mock_fixture(row: dict[str, Any]) -> None:
    """Mock butuh fixture; isi dari referensi agar kontraknya bisa diuji."""
    segments = row.get("reference_segments")
    if isinstance(segments, list) and segments:
        settings.MOCK_STT_SEGMENTS_JSON = json.dumps(segments)
        settings.MOCK_STT_TEXT = ""
    else:
        settings.MOCK_STT_TEXT = str(row["reference_text"])
        settings.MOCK_STT_SEGMENTS_JSON = ""


def _measure_row(
    row: dict[str, Any],
    *,
    base: Path,
    provider_name: str,
    diarization_provider_name: str | None,
    frame_seconds: float,
    collar_seconds: float,
) -> dict[str, Any]:
    audio_path = Path(str(row["audio_path"]))
    if not audio_path.is_absolute():
        audio_path = base / audio_path

    if provider_name == "mock":
        _configure_mock_fixture(row)
    provider = create_provider(provider_name)

    started = time.perf_counter()
    try:
        result = provider.transcribe(
            audio_path,
            audio_path.name,
            "audio/wav" if audio_path.suffix.lower() == ".wav" else "application/octet-stream",
        )
    except Exception as exc:  # noqa: BLE001 - laporkan jenis error, bukan detail privat
        return {
            "audio": _display_path(audio_path, base),
            "error": exc.__class__.__name__,
        }
    latency = time.perf_counter() - started

    reference = normalize_text(str(row["reference_text"]), apply_eyd=False)
    hypothesis = normalize_text(result.text, apply_eyd=False)
    segments = result.segments
    source_refs = [segment.source_ref for segment in segments if segment.source_ref]
    languages = {segment.language for segment in segments}

    item: dict[str, Any] = {
        "audio": _display_path(audio_path, base),
        "provider": provider.name,
        "cer": round(character_error_rate(reference, hypothesis), 6),
        "wer": round(word_error_rate(reference, hypothesis), 6),
        "latency_seconds": round(latency, 6),
        "segments": len(segments),
        "has_timestamps": result.has_timestamps,
        "source_ref_valid": bool(source_refs)
        and all(is_valid_source_ref(value) for value in source_refs),
        "language_id": languages == {"id"},
    }
    if provider.name == "mock":
        item["note"] = "[MOCK] — pipeline smoke test, bukan ukuran kualitas."

    if diarization_provider_name and row.get("reference_diarization"):
        from app.services.diarization.registry import (
            create_provider as create_diarization_provider,
        )

        diarization = create_diarization_provider(diarization_provider_name)
        turns = diarization.diarize(audio_path, audio_path.name, "audio/wav").turns
        hypothesis_turns = [
            {
                "speaker": turn.speaker_ref,
                "start_seconds": turn.start_seconds,
                "end_seconds": turn.end_seconds,
            }
            for turn in turns
        ]
        item["der"] = round(
            diarization_error_rate(
                row["reference_diarization"],
                hypothesis_turns,
                frame_seconds=frame_seconds,
                collar_seconds=collar_seconds,
            ),
            6,
        )
    else:
        item["der"] = None
    return item


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--diarization-provider", default=None)
    parser.add_argument("--frame-seconds", type=float, default=0.1)
    parser.add_argument("--collar-seconds", type=float, default=0.25)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        rows = _load_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"Manifest tidak valid: {exc}", file=sys.stderr)
        return 1

    base = args.manifest.resolve().parent
    items = [
        _measure_row(
            row,
            base=base,
            provider_name=args.provider,
            diarization_provider_name=args.diarization_provider,
            frame_seconds=args.frame_seconds,
            collar_seconds=args.collar_seconds,
        )
        for row in rows
    ]

    valid = [item for item in items if "error" not in item]
    report: dict[str, Any] = {
        "provider": args.provider,
        "diarization_provider": args.diarization_provider,
        "items": items,
        "summary": {
            "count": len(items),
            "completed": len(valid),
            "mean_cer": _mean([item["cer"] for item in valid]),
            "mean_wer": _mean([item["wer"] for item in valid]),
            "mean_latency_seconds": _mean(
                [item["latency_seconds"] for item in valid]
            ),
            "mean_der": _mean(
                [item["der"] for item in valid if item.get("der") is not None]
            ),
            "all_source_refs_valid": bool(valid)
            and all(item["source_ref_valid"] for item in valid),
            "all_language_id": bool(valid)
            and all(item["language_id"] for item in valid),
        },
        "caveat": "Angka hanya valid untuk manifest/konfigurasi yang dipakai. "
        "Provider mock menghasilkan teks [MOCK] dan bukan klaim kualitas.",
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Laporan ditulis: {args.output}")
    else:
        print(payload)
    return 0 if len(valid) == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
