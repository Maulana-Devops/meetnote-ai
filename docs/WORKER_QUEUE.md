# Worker antrean job (opsional)

Dokumen ini menjelaskan mode eksekusi job background yang **opsional**. Deploy
yang sudah berjalan tidak berubah: default tetap `JOB_RUNNER=background`
(FastAPI `BackgroundTasks`).

## Tujuan

Memisahkan proses yang menjalankan provider (STT, diarisasi, LLM) dari proses
API. Endpoint tetap mengembalikan `202` lebih cepat, sementara worker mengambil
pekerjaan dari tabel `job_queue` di database yang sama.

Tidak ada Redis/Celery/RabbitMQ dan tidak ada dependency baru. Satu proses
worker cukup untuk deployment komunitas/UMKM; beberapa proses worker bisa
berjalan paralel karena klaim baris memakai `UPDATE ... WHERE status='PENDING'`.

## Alur

```text
POST /meetings/{id}/transcription  (atau diarization/summary/action-items)
  -> prepare_*(): validasi + klaim tabel job, status PROCESSING, run_token baru
  -> JOB_RUNNER=worker: tulis 1 baris job_queue (PENDING)
  -> API mengembalikan 202

worker.py
  -> recover_stale(): klaim lama dikembalikan ke PENDING / ditandai FAILED
  -> claim_next(): ambil 1 baris PENDING, attempts += 1, status PROCESSING
  -> run_*(): provider dipanggil, hasil ditulis ke tabel job yang sama
  -> outcome_from_job(): baca status COMPLETED/FAILED dari tabel job asli
  -> mark_finished(): tutup baris antrean (hanya kategori error di log)
```

Status hasil tetap berada di `transcription_jobs`, `diarization_jobs`,
`summary_jobs`, dan `action_item_jobs`. UI/API tidak perlu mengenal tabel
antrean. `run_token` tetap dicek ulang, sehingga job lama tidak menimpa job
yang lebih baru.

## Mengaktifkan

1. Set di `backend/.env`:

   ```env
   JOB_RUNNER=worker
   ```

2. Jalankan worker bersama API:

   ```powershell
   docker compose up -d --build
   ```

   Compose sudah menyertakan service `worker` yang memakai image backend yang
   sama, volume `meetnote_data`/`meetnote_models`, dan `JOB_RUNNER=worker`.
   Service ini tidak membuka port.

   Alternatif tanpa Compose, dari folder `backend/`:

   ```powershell
   python worker.py
   ```

3. Smoke satu batch tanpa loop:

   ```powershell
   python worker.py --once
   ```

Kembali ke mode lama cukup dengan `JOB_RUNNER=background` dan menjalankan ulang
API. Baris `job_queue` lama tidak dihapus otomatis; ini disengaja agar tidak
ada penghapusan data.

## Konfigurasi

| Variabel | Default | Arti |
| --- | --- | --- |
| `JOB_RUNNER` | `background` | `background` = `BackgroundTasks`; `worker` = antrean DB |
| `JOB_QUEUE_POLL_SECONDS` | `1.0` | Jeda saat antrean kosong |
| `JOB_QUEUE_BATCH_SIZE` | `4` | Maksimal job per putaran |
| `JOB_QUEUE_STALE_SECONDS` | `3600` | Klaim yang lebih tua dianggap terputus |
| `JOB_QUEUE_MAX_ATTEMPTS` | `3` | Batas pengambilan ulang klaim stale |
| `SQLITE_WAL_ENABLED` | `false` | Set `true` bila API + worker memakai satu file SQLite |

Compose sudah menyetel `SQLITE_WAL_ENABLED=true` untuk `backend` dan `worker`.
WAL mengurangi kejadian `database is locked` saat pembaca dan penulis berjalan
bersamaan. Jika tidak diaktifkan, worker tetap berjalan dan klaim yang terkunci
dicoba lagi pada putaran berikutnya.

Retry provider (429/timeout/5xx) tetap dikendalikan oleh
`PROVIDER_RETRY_*` dan berjalan di dalam `run_*`, terpisah dari `attempts`
antrean.

## Perilaku saat worker mati

- API dalam mode worker **tidak** menandai job `PROCESSING` sebagai `FAILED`
  saat restart. Itu mencegah job yang masih antre ikut gagal.
- Saat worker hidup kembali, `recover_stale()` memeriksa klaim yang lebih tua
  dari `JOB_QUEUE_STALE_SECONDS`:
  - `attempts < JOB_QUEUE_MAX_ATTEMPTS` → kembali ke `PENDING` dengan
    `run_token` yang sama;
  - `attempts >= batas` → antrean `FAILED` dan job terkait ditandai `FAILED`
    dengan pesan generik. Tidak ada file/transkrip yang dihapus.

## Batasan

- SQLite tetap punya satu writer. Beberapa worker aman untuk klaim, tetapi
  tidak menambah throughput tulis database secara linear. Untuk skala besar,
  lihat roadmap PostgreSQL.
- Ini bukan broker distributed: tanpa leader election, heartbeat halus, atau
  dead-letter queue. Pemulihan memakai timestamp `updated_at` dan batas attempts.
- Mode tanpa autentikasi tetap berlaku. Worker tidak membuka port dan tidak
  boleh diekspos langsung.
- `alembic downgrade` sengaja dinonaktifkan. Gunakan backup/restore.

## Verifikasi

```powershell
python -m alembic history
python -m alembic check
python scripts/verify_migrations.py
python -m pytest tests/test_worker_queue.py -q
python scripts/check_secrets.py
```

Semua perintah di atas bisa dijalankan terhadap database temporer/provider
mock dan tidak menyentuh `meetnote.db`, `storage/`, atau backup pengguna.
