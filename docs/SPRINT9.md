# Sprint 9 — Pipeline Reliability & Data Integrity

Sprint 9 tidak menambah fitur AI baru. Fokusnya adalah mengaudit dan
mengerasikan pipeline yang sudah ada: siklus hidup empat jenis job, pencegahan
duplikasi, recovery, retry, storage, aturan delete, foreign key SQLite, logging,
health check, dan test. Semua perilaku Sprint 1–8 dipertahankan; tidak ada
commit/push Git.

## 1. Baseline audit

Audit dilakukan dengan membaca kode dan dokumen yang sebenarnya, bukan
mengasumsikan struktur:

- `README.md`, `docs/ARCHITECTURE.md`, `docs/README.md`, `docs/SPRINT1.md` …
  `docs/SPRINT8.md`;
- seluruh model dan enum status di `backend/app/models/`;
- keempat workflow (`transcription.py`, `diarization/workflow.py`,
  `summary/workflow.py`, `action_items/workflow.py`);
- `backend/app/main.py`, `backend/main.py`, startup recovery;
- semua endpoint start/stop/delete di `backend/app/api/v1/`;
- `core/storage.py`, `core/config.py`, `database/session.py`,
  `database/migrations.py`;
- seluruh test backend (`backend/tests/`).

Baseline sebelum perubahan: **195 test lulus**, frontend `npm run build` sukses.
Satu warning `anyio.abc.BlockingPortal` sudah ada sejak Sprint 8 dan tidak
berkaitan dengan Sprint 9.

## 2. Temuan reliability (terbukti)

| # | Temuan | Dampak | Status |
|---|---|---|---|
| 1 | SQLite `PRAGMA foreign_keys` tidak pernah aktif | `ON DELETE CASCADE`/`SET NULL` hanya teks DDL | Diperbaiki |
| 2 | `prepare_summary`/`prepare_action_items` cek-then-act tanpa kunci | Dua request bersamaan bisa menjadwalkan dua task | Diperbaiki |
| 3 | `run_*` tidak membawa identitas eksekusi | Task lama bisa menimpa hasil/FAILED job baru | Diperbaiki |
| 4 | `_mark_failed` transcription menimpa `Meeting.status` tanpa syarat | Job/meeting kontradiksi setelah retry | Diperbaiki |
| 5 | Recovery transcription memakai status meeting, bukan status job | Bisa menyentuh job `COMPLETED` | Diperbaiki |
| 6 | Blok save hanya menangkap `SQLAlchemyError` | Error lain bisa meninggalkan job `PROCESSING` | Diperbaiki |
| 7 | Detail `SQLAlchemyError`/path storage bocor di HTTP 500 | Informasi internal/direktori terekspos | Diperbaiki |
| 8 | `audio_assets.meeting_id` tidak unik | Upload bersamaan bisa duplikat metadata | Diperbaiki |
| 9 | Tidak ada deteksi orphan/`.part`/`.delete`/metadata tanpa file | Tidak ada visibilitas operasional | Diperbaiki (read-only) |
| 10 | Hapus transkrip/rekaman tidak memeriksa job ringkasan/action items | Data parsial bila task dependen masih jalan | Diperbaiki |
| 11 | `backend/main.py` punya lifespan berbeda (tanpa migrasi/recovery) | `uvicorn main:app` melewati langkah penting | Diperbaiki |
| 12 | Tidak ada logging job | Sulit menelusuri durasi/status/error category | Diperbaiki |
| 13 | Retry transcription/diarization menghapus hasil lama di `prepare_*` | Perilaku lama | **Sengaja dipertahankan** (lihat §7) |

Tidak ditemukan bukti: `COMPLETED` tersimpan sebelum hasil di-commit (status dan
hasil berada dalam satu transaksi), session bocor (semua `run_*`, `_mark_failed`,
`recover_*`, dan `get_db` memakai `try/finally: db.close()`), atau provider/SDK
baru yang diperlukan.

## 3. File yang dibuat / diubah

**Baru**

- `backend/app/core/job_logging.py` — logging JSON satu baris, tanpa field secret.
- `backend/app/services/job_guard.py` — mutex per (jenis job, meeting),
  `run_token`, klaim atomik, dan pengawal job aktif.
- `backend/tests/test_sprint9.py` — 15 test baru.
- `docs/SPRINT9.md` — dokumen ini.

**Diubah**

- `backend/app/database/session.py` — event listener SQLite: `foreign_keys=ON`,
  `busy_timeout=5000`.
- `backend/app/database/migrations.py` — unique index `audio_assets.meeting_id`
  (hanya bila tidak ada duplikat lama), kolom `run_token` aditif pada empat
  tabel job.
- `backend/app/models/{transcript,diarization,summary,action_item}.py` — kolom
  `run_token`.
- Keempat workflow — klaim dengan mutex/token, pengecekan ulang sebelum save,
  `_mark_failed` token-aware, penanganan Exception umum, recovery idempoten,
  logging.
- `backend/app/api/v1/{transcriptions,diarizations,summaries,action_items,recordings,meetings}.py`
  — pengawal delete, pesan 500 generik, `IntegrityError` → 409.
- `backend/app/api/v1/health.py` — `GET /api/v1/health/diagnostics`.
- `backend/app/core/storage.py` — `audit_storage()` read-only.
- `backend/app/main.py`, `backend/main.py` — lifespan tunggal, recovery
  diisolasi per jenis job.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/README.md`.

## 4. Siklus hidup job

Status tetap `NOT_STARTED → PROCESSING → COMPLETED / FAILED` untuk keempat job.
Perubahan hanya pada **bagaimana** transisi dijaga:

1. `prepare_*` mengambil mutex `job_lock(job_type, meeting_id)`.
2. Token baru (`uuid4`) ditulis bersama status `PROCESSING`.
3. `run_*` membaca token di awal, mencatat `job_started`, lalu memanggil provider.
4. Sebelum menulis hasil, `is_current()` memastikan job masih `PROCESSING` dan
   token masih sama. Bila tidak → `job_skipped` dengan status `SUPERSEDED`.
5. Hasil + status `COMPLETED` tetap ditulis dalam **satu transaksi**; commit gagal
   → rollback + `_mark_failed`.
6. Semua error (termasuk non-SQLAlchemy di blok save) sekarang memetakan ke
   `FAILED` dengan pesan aman.

`Meeting.status` hanya diubah oleh transkripsi. `_mark_failed` transcription
kini mengubah meeting menjadi `FAILED` hanya bila meeting masih `TRANSCRIBING`
dan job yang gagal masih aktif, sehingga kegagalan job lama tidak merusak job
baru. Kegagalan ringkasan/action items tidak pernah menyentuh `Meeting.status`,
transkrip, diarisasi, atau ringkasan/action item lama.

## 5. Perlindungan konkurensi

- **Dalam satu proses (kasus FastAPI `BackgroundTasks`)**: `job_lock` per
  `(job_type, meeting_id)` menjamin hanya satu `prepare_*` yang bisa lolos.
  Test `test_concurrent_prepare_summary_only_one_wins` memakai dua thread dan
  barrier; hasilnya satu `ok` dan satu `409`.
- **Klaim atomik pada baris yang sudah ada** (summary/action items):
  `UPDATE ... WHERE meeting_id = :id AND status != PROCESSING`, rowcount harus 1.
- **Baris baru** (transcription/diarization/audio): constraint UNIQUE tetap
  menjadi pagar; `IntegrityError` kini diterjemahkan menjadi `409`, bukan 500.
- **Batas jujur**: SQLite tidak punya `SELECT ... FOR UPDATE`. Dua worker proses
  terpisah masih bergantung pada UNIQUE + `busy_timeout`; ini bukan antrean
  distributed.

## 6. Recovery

Keempat `recover_stuck_*` sekarang:

- hanya menyentuh job `PROCESSING` (transcription tidak lagi melihat status
  meeting sebagai pemicu utama);
- menandai `FAILED`, mengosongkan `run_token`, dan memakai pesan aman yang sama;
- idempoten — pemanggilan kedua mengembalikan `0`;
- tidak pernah mengubah job `COMPLETED`, tidak menghapus hasil, dan tidak
  menghapus file;
- tidak menaikkan exception ke startup (dibungkus di `app/main.py`);
- transcription menyelaraskan meeting `TRANSCRIBING` yang tidak punya job
  `PROCESSING`: `COMPLETED → TRANSCRIBED`, selain itu `FAILED`.

Tidak ada klaim resume-from-checkpoint: job yang tertinggal tetap harus
dicoba ulang manual dari UI.

## 7. Retry

- **Summary & action items**: sudah aman sejak Sprint 7/8. Hasil lama baru
  diganti setelah hasil baru tervalidasi dan commit berhasil. Tidak ada
  penghapusan awal. Edit pengguna (`is_manually_edited`) tetap dipertahankan.
- **Transcription & diarisasi**: `prepare_*` tetap memanggil `clear_*` lebih awal.
  Ini **sengaja dipertahankan** karena (a) `docs/SPRINT5.md` dan test
  `test_retranscribing_clears_stale_diarization` mengunci perilaku ini sebagai
  bagian Sprint 1–8, dan (b) topik/keputusan serta `action_item_sources`
  merujuk ke ID segmen lama, sehingga mempertahankan segmen lama akan menciptakan
  referensi menggantung. Kini penghapusan itu ditolak (`409`) bila job
  ringkasan/action items masih berjalan, sehingga tidak ada data parsial.
- Status `PROCESSING` tidak bisa di-retry secara paralel.

## 8. Audit storage

`GET /api/v1/health/diagnostics` mengembalikan, secara read-only:

- `orphan_files` — file audio tanpa metadata;
- `temp_files` — sisa `.part`;
- `trash_files` — sisa `.delete`;
- `metadata_without_file` — metadata yang file fisiknya hilang;
- `invalid_metadata_paths` — path DB yang ditolak `resolve_storage_path()`;
- jumlah file dan metadata.

Semua path **relatif** terhadap `STORAGE_DIR`; tidak ada path absolut, nama file
asli pengguna, isi audio, atau transkrip yang dikembalikan/dilog. **Tidak ada
file yang dihapus otomatis** — keputusan tetap di tangan pengguna. Upload tetap
memakai `.part` + `os.replace` (atomic visibility), validasi sebelum menulis,
path traversal protection, dan rollback file saat commit gagal. Kekurangan
yang masih ada: tidak ada `fsync` (atomic ≠ crash-durable), dan orphan hasil
crash process hanya dilaporkan, tidak dibersihkan.

## 9. Aturan delete

| Operasi | Dependensi diperiksa | Perilaku |
|---|---|---|
| DELETE transkrip | transkripsi, diarisasi, ringkasan, action items | `409` bila ada yang `PROCESSING` |
| DELETE rekaman | semua jenis job | `409`; file dipindah ke `.delete`, dikembalikan bila commit/clear gagal |
| DELETE diarisasi | transkripsi + own job | transkrip/audio aman |
| DELETE ringkasan | semua job lain | ringkasan lama dihapus bila sukses |
| DELETE action items | semua job lain | hanya item AI + job yang dihapus |
| DELETE satu action item | tidak ada job | hanya item itu + `action_item_sources` |

Hapus transkrip tetap membersihkan ringkasan dan action items yang referensinya
jadi invalid (Sprint 7/8), sekarang dengan pengawal job aktif.

## 10. SQLite foreign key enforcement

`database/session.py` memasang `event.listens_for(engine, "connect")` yang
menjalankan `PRAGMA foreign_keys=ON` dan `PRAGMA busy_timeout=5000` pada
**setiap** koneksi baru. Test membuktikan `PRAGMA foreign_keys == 1` lewat
`engine.connect()` dan `engine.raw_connection()`, dan bahwa insert child tanpa
parent ditolak dengan `IntegrityError`. Delete meeting lewat SQL mentah kini
benar-benar menjalankan cascade DB.

Untuk database lama, SQLite tidak bisa `ALTER TABLE ADD CONSTRAINT`; migrasi
tetap aditif dan ORM `clear_*` tetap menjadi penjaga integritas. Migrasi baru:

- `ALTER TABLE ... ADD COLUMN run_token VARCHAR(36)` bila belum ada;
- `CREATE UNIQUE INDEX uq_audio_asset_meeting` hanya bila tidak ada duplikat
  lama (duplikat tidak dihapus, hanya dicatat).

## 11. Logging & health

`core/job_logging.py` memancarkan `job_event`, `job_started`, `job_finished`,
`job_skipped`, `job_failed`, `storage_event`, dan `recovery_event` dalam format
JSON satu baris di logger `meetnote`. Field yang tersedia: job ID, meeting ID,
jenis job, provider, model, status, `error_category` (nama kelas saja), dan
durasi ms. Tidak ada field untuk API key, Authorization, audio, transkrip, atau
pesan error bebas. Test memastikan secret tidak muncul di log maupun response.

`/api/v1/health` tidak berubah. `/api/v1/health/diagnostics` adalah endpoint
baru, read-only, dan non-sensitif.

## 12. Test backend

- Baseline: 195 test.
- Sprint 9: 15 test baru (FK, migrasi legacy, konkurensi, stale token, recovery
  idempoten, exception → FAILED, error leakage, storage audit, delete dependency,
  regresi pipeline mock).
- Total: **210 passed, 1 warning** (`python -m pytest -q`).
- Warning yang tersisa adalah `anyio.abc.BlockingPortal` dari Starlette,
  sudah ada sebelum Sprint 9.

## 13. Frontend build / type-check

`npm run build` (`tsc -b && vite build`) sukses, `✓ built in 1.82s`. Tidak ada
perubahan frontend di Sprint 9.

## 14. Regresi Sprint 1–8

Seluruh 195 test lulus tanpa modifikasi. Test yang mengunci kontrak provider,
format respons, urutan segmen, label speaker, referensi ringkasan/action item,
manual edit preservation, dan skema aditif tetap hijau. Perubahan pesan 500
hanya menghapus detail internal; test lama yang memeriksa prefix pesan tetap
lolos, dan test Sprint 6 yang memeriksa absennya `"database down"` kini lebih
kuat.

## 15. Risiko yang belum terselesaikan

- Multiprocess/multi-worker belum aman sepenuhnya; butuh antrean/DB lock yang
  benar-benar distributed bila aplikasi diskalakan. Tidak ditambahkan di sprint
  ini sesuai batasan (tanpa Celery/Redis/Kafka).
- Retry transcription/diarization tetap membersihkan hasil lama lebih awal
  (alasan lihat §7).
- `os.replace` belum didampingi `fsync`; crash daya bisa meninggalkan file kosong
  atau orphan, yang kini dapat dilihat lewat diagnostics tetapi tidak dibersihkan.
- Database lama dengan duplikat `audio_assets.meeting_id` tidak mendapat unique
  index sampai duplikatnya diselesaikan manual.
- Provider cloud belum diverifikasi live tanpa API key; semua test mock/fake HTTP.

## 16. Pengujian manual yang disarankan

1. Jalankan backend dan frontend, buat meeting, upload/record audio.
2. Set provider `mock` di `.env`, jalankan transkripsi → diarisasi → ringkasan →
   action items; amati status akhir `COMPLETED`.
3. Klik retry ringkasan dua kali dengan cepat; salah satu harus `409`.
4. Saat job ringkasan `PROCESSING`, coba DELETE transkrip/rekaman; harus `409`.
5. Hentikan server saat job `PROCESSING`, restart, lalu cek GET status:
   `FAILED`, hasil lama masih ada, dan pesan tidak membocorkan path.
6. Buka `/api/v1/health/diagnostics`; pastikan `sqlite_foreign_keys: 1`.
7. Buat file `.part` atau orphan di `storage/meetings/...`, refresh diagnostics,
   pastikan path relatif muncul dan file tidak dihapus.
8. Set `LLM_PROVIDER=openai` tanpa API key, coba ringkasan; pastikan pesan
   konfigurasi aman tanpa API key di response maupun log server.
