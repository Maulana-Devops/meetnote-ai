"""Verifikasi Alembic untuk database kosong dan database lama.

Script ini memakai direktori temporer dan provider mock; tidak pernah
menyentuh ``meetnote.db``, ``storage/``, backup, atau data pengguna.

    python backend/scripts/verify_migrations.py

Dipakai CI sebagai bagian dari Definition of Done Fase 0.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "action_item_jobs",
    "action_item_sources",
    "action_items",
    "audio_assets",
    "diarization_jobs",
    "meeting_summaries",
    "meetings",
    "speakers",
    "summary_jobs",
    "transcript_segments",
    "transcription_jobs",
}


def _sqlite_tables(db: Path) -> list[str]:
    with sqlite3.connect(db) as connection:
        return sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        )


def _alembic_version(db: Path) -> str | None:
    with sqlite3.connect(db) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def _has_unique_audio_index(db: Path) -> bool:
    with sqlite3.connect(db) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            ("uq_audio_asset_meeting",),
        ).fetchone()
    return row is not None


def _run_child(mode: str, db: Path, storage: Path) -> dict[str, object]:
    """Jalankan satu skenario di subprocess dengan environment terisolasi."""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUTF8": "1",
            "DATABASE_URL": f"sqlite:///{db.as_posix()}",
            "STORAGE_DIR": str(storage),
            "RUN_DB_MIGRATIONS": "true",
            "STT_PROVIDER": "mock",
            "DIARIZATION_PROVIDER": "mock",
            "LLM_PROVIDER": "mock",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            mode,
            str(db),
            str(storage),
        ],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"skenario {mode} gagal:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )

    for line in reversed(completed.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            return json.loads(stripped)
    raise RuntimeError(f"skenario {mode} tidak menghasilkan JSON:\n{completed.stdout}")


def _child(mode: str, db: Path, storage: Path) -> None:
    os.environ.update(
        {
            "PYTHONUTF8": "1",
            "DATABASE_URL": f"sqlite:///{db.as_posix()}",
            "STORAGE_DIR": str(storage),
            "RUN_DB_MIGRATIONS": "true",
            "STT_PROVIDER": "mock",
            "DIARIZATION_PROVIDER": "mock",
            "LLM_PROVIDER": "mock",
        }
    )

    sys.path.insert(0, str(BACKEND_ROOT))

    from app import models  # noqa: E402,F401 - daftarkan model
    from app.database.migrations import (  # noqa: E402
        apply_additive_migrations,
        run_migrations,
    )
    from app.database.session import Base, SessionLocal, engine  # noqa: E402

    legacy_data_preserved: bool | None = None

    if mode == "fresh":
        run_migrations()
    elif mode == "legacy":
        # Simulasikan database sebelum Fase 0: ORM + migrasi aditif lama.
        Base.metadata.create_all(bind=engine)
        apply_additive_migrations()
        with SessionLocal() as session:
            meeting = models.Meeting(title="legacy-check", status="PENDING")
            session.add(meeting)
            session.commit()
            legacy_id = meeting.id

        # Jalur startup Fase 0 harus men-stamp tanpa mengubah baris lama.
        run_migrations()
        with SessionLocal() as session:
            row = session.get(models.Meeting, legacy_id)
            legacy_data_preserved = bool(row and row.title == "legacy-check")
    else:  # pragma: no cover - dipanggil hanya oleh orchestrator
        raise ValueError(f"mode tidak dikenal: {mode}")

    result: dict[str, object] = {
        "scenario": mode,
        "tables": _sqlite_tables(db),
        "version": _alembic_version(db),
        "unique_audio_index": _has_unique_audio_index(db),
        "legacy_data_preserved": legacy_data_preserved,
    }
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        _child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
        return 0

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="meetnote-fase0-") as tmp:
        root = Path(tmp)
        for mode in ("fresh", "legacy"):
            scenario_dir = root / mode
            scenario_dir.mkdir(parents=True)
            db = scenario_dir / "verify.db"
            storage = scenario_dir / "storage"
            storage.mkdir()

            try:
                result = _run_child(mode, db, storage)
            except (RuntimeError, json.JSONDecodeError) as exc:
                failures.append(str(exc))
                continue

            tables = set(result["tables"])
            missing = EXPECTED_TABLES - tables
            if missing:
                failures.append(f"{mode}: tabel kurang: {sorted(missing)}")
            if result["version"] != "0001":
                failures.append(f"{mode}: versi Alembic = {result['version']!r}")
            if result["unique_audio_index"] is not True:
                failures.append(f"{mode}: index uq_audio_asset_meeting tidak ada")
            if mode == "legacy" and result["legacy_data_preserved"] is not True:
                failures.append("legacy: data meeting lama tidak utuh")
            print(
                f"{mode}: tables={len(tables)} version={result['version']} "
                f"unique_index={result['unique_audio_index']} "
                f"legacy_data={result['legacy_data_preserved']}"
            )

    if failures:
        print("Verifikasi migrasi GAGAL:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("Verifikasi migrasi lulus: database kosong dan database lama aman.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
