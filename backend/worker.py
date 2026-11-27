"""Proses worker untuk antrean job background berbasis database.

Jalankan sebagai proses terpisah dari FastAPI::

    python worker.py            # loop terus-menerus
    python worker.py --once     # satu batch, berguna untuk smoke test/CI

Worker memakai DATABASE_URL dan STORAGE_DIR yang sama dengan API. Tidak ada
Redis/Celery dan tidak ada dependency baru. Job yang dijalankan tetap memakai
fungsi ``run_*`` yang sama dengan mode BackgroundTasks.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
import uuid
from collections.abc import Callable

_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.core.config import settings  # noqa: E402
from app.core.job_logging import error_category  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.services import job_queue  # noqa: E402
from app.services.action_items.workflow import run_action_items  # noqa: E402
from app.services.diarization.workflow import run_diarization  # noqa: E402
from app.services.job_queue import JobQueueStatus  # noqa: E402
from app.services.summary.workflow import run_summary  # noqa: E402
from app.services.transcription import run_transcription  # noqa: E402

# Import models sebelum create_all/migrasi di aplikasi lain mendaftarkan tabel.
import app.models  # noqa: E402,F401

import logging  # noqa: E402

logger = logging.getLogger("meetnote.worker")


def _default_runners() -> dict[str, Callable[[uuid.UUID], None]]:
    return {
        job_queue.TRANSCRIPTION: run_transcription,
        job_queue.DIARIZATION: run_diarization,
        job_queue.SUMMARY: run_summary,
        job_queue.ACTION_ITEMS: run_action_items,
    }


def process_batch(
    db,
    *,
    runners: dict[str, Callable[[uuid.UUID], None]],
    worker_id: str,
    batch_size: int,
    stale_seconds: float,
    max_attempts: int,
) -> tuple[int, int]:
    """Satu putaran: pulihkan klaim lama lalu proses maksimal ``batch_size``.

    Mengembalikan ``(diproses, dipulihkan)``. Fungsi ini sengaja menerima
    ``runners`` agar bisa diuji dengan provider/runner tiruan.
    """
    recovered = job_queue.recover_stale(
        db,
        stale_seconds=stale_seconds,
        max_attempts=max_attempts,
    )
    processed = 0
    while processed < batch_size:
        row = job_queue.claim_next(db, worker_id)
        if row is None:
            break

        runner = runners.get(row.job_type)
        if runner is None:
            status, category = JobQueueStatus.FAILED, "UnknownJobType"
        else:
            try:
                runner(uuid.UUID(row.meeting_id))
                status, category = job_queue.outcome_from_job(db, row)
            except Exception as exc:  # run_* normalnya menelan error; ini pagar.
                status, category = JobQueueStatus.FAILED, error_category(exc)

        job_queue.mark_finished(
            db,
            row.id,
            status,
            error_category=category,
        )
        logger.info(
            "queue_finished job_type=%s meeting_id=%s status=%s error_category=%s",
            row.job_type,
            row.meeting_id,
            status,
            category,
        )
        processed += 1
    return processed, recovered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker antrean job MeetNote AI")
    parser.add_argument("--once", action="store_true", help="proses satu batch lalu keluar")
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--stale-seconds", type=float, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    args = parser.parse_args(argv)

    configure_logging()
    if settings.JOB_RUNNER != "worker":
        logger.warning(
            "worker_started_with_background_mode hint=set_JOB_RUNNER=worker"
        )
    if settings.DATABASE_URL.startswith("sqlite") and not settings.SQLITE_WAL_ENABLED:
        logger.warning(
            "sqlite_wal_disabled hint=set_SQLITE_WAL_ENABLED=true_for_concurrent_workers"
        )

    poll_seconds = args.poll_seconds or settings.JOB_QUEUE_POLL_SECONDS
    batch_size = args.batch_size or settings.JOB_QUEUE_BATCH_SIZE
    stale_seconds = args.stale_seconds or settings.JOB_QUEUE_STALE_SECONDS
    max_attempts = args.max_attempts or settings.JOB_QUEUE_MAX_ATTEMPTS
    worker_id = f"{socket.gethostname()}:{os.getpid()}"[:100]
    runners = _default_runners()

    logger.info(
        "worker_started worker_id=%s batch=%s poll=%s",
        worker_id,
        batch_size,
        poll_seconds,
    )
    while True:
        with SessionLocal() as db:
            processed, recovered = process_batch(
                db,
                runners=runners,
                worker_id=worker_id,
                batch_size=batch_size,
                stale_seconds=stale_seconds,
                max_attempts=max_attempts,
            )
        if recovered:
            logger.warning("queue_stale_recovered count=%s", recovered)
        if args.once:
            return 0
        if processed == 0:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
