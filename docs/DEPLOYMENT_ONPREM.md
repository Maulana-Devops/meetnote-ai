# Deployment On-Prem (Docker Compose)

Panduan ini untuk organisasi kecil/komunitas yang ingin menjalankan MeetNote AI
di server atau komputer lokal sendiri. Tidak ada layanan cloud yang diwajibkan.

## 1. Prasyarat

- Docker Engine + Docker Compose Plugin terinstal.
- Rust tidak diperlukan; tidak ada model/bobot besar yang diunduh saat deploy.
- Untuk mencoba tanpa API key, pakai provider `mock`. Semua hasil AI berlabel
  `[MOCK]` dan bukan transkripsi sungguhan.

## 2. Menyiapkan konfigurasi

Dari root proyek:

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

Set minimal di `backend/.env`:

```dotenv
DEBUG=false
RUN_DB_MIGRATIONS=true
STT_PROVIDER=mock
DIARIZATION_PROVIDER=mock
LLM_PROVIDER=mock
CORS_ALLOWED_ORIGINS=http://localhost:4173,http://127.0.0.1:4173
```

Jangan mengisi API key untuk percobaan awal. Jangan pernah menaruh secret di
`frontend/.env` atau variabel `VITE_*`.

## 3. Menjalankan

```powershell
docker compose up -d --build
```

Lalu cek:

| Layanan | URL |
| --- | --- |
| Frontend | `http://localhost:4173` |
| Backend | `http://localhost:8000/api/v1/health` |
| Diagnostik | `http://localhost:8000/api/v1/health/diagnostics` |
| API docs | `http://localhost:8000/docs` |

Header `X-Request-ID` pada respons bisa dicocokkan dengan log backend JSON.

## 4. Data dan volume

Compose memakai volume bernama `meetnote_data` yang dilewat ke `/data` di
container:

```text
/data/meetnote.db       → database SQLite
/data/storage/meetings/ → file audio per meeting
/models/faster-whisper/ → bobot STT lokal opsional (volume meetnote_models)
```

Volume ini **terpisah** dari `backend/meetnote.db` dan `storage/` di host.
Dengan demikian `docker compose up` tidak menghapus atau menimpa DB/audio lama
milik pengguna. Untuk memindahkan data lama ke volume, gunakan prosedur
`docs/BACKUP_RESTORE.md` sebagai referensi konsistensi DB + folder audio.

## 4a. Opsi STT lokal (tanpa API key)

Secara default image tidak memuat model/bobot besar. Untuk memakai
`faster-whisper`, pasang dependency opsional di image/host dan unduh model ke
volume `meetnote_models` pada pemakaian pertama. Set di `backend/.env`:

```dotenv
STT_PROVIDER=faster_whisper
STT_LANGUAGE=id
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_VAD=true
STT_WORD_TIMESTAMPS=true
```

Compose sudah mengarahkan `STT_MODEL_DIR=/models/faster-whisper` dan
`INDONESIAN_VOCAB_PATH=/config/indonesian-vocab.txt`. Untuk `whisper.cpp`,
jalankan server OpenAI-compatible di host yang dapat dijangkau container, lalu
set `STT_PROVIDER=whisper_cpp` dan `WHISPER_CPP_BASE_URL`; audio harus WAV PCM
16-bit mono.

Diarisasi `pyannote` bersifat opt-in. Token Hugging Face hanya boleh ada di
environment backend, bukan di image, `frontend/.env`, variabel `VITE_*`, Git,
atau chat. Telemetri dimatikan dengan `PYANNOTE_METRICS_ENABLED=false`.
Angka CER/WER/DER/latency **belum diterbitkan**; metodologinya ada di
`docs/BENCHMARK_METHOD.md`.

## 5. Migrasi database

Saat startup, backend menjalankan `run_migrations()`:

- database baru → Alembic `upgrade head` membuat seluruh tabel;
- database lama yang belum punya `alembic_version` → migrasi aditif dijalankan,
  lalu `stamp head`; tidak ada tabel yang dijatuhkan;
- database yang sudah punya `alembic_version` → `upgrade head` (biasanya no-op).

`RUN_DB_MIGRATIONS=false` **hanya** untuk test suite. Jangan memakainya di
deployment.

## 6. Backup dan restore

Hentikan backend sebelum menyalin volume agar DB tidak berada di tengah
transaksi:

```powershell
docker compose stop backend
docker run --rm -v meetnote_data:/data -v ${PWD}\backups:/backup alpine `
  sh -c "mkdir -p /backup/meetnote && cp -a /data/. /backup/meetnote/"
docker compose start backend
```

Restore **tidak boleh** menimpa data secara otomatis. Lakukan pada deployment
baru/kosong, verifikasi DB dan folder audio berasal dari titik waktu yang sama,
lalu nyalakan backend. Lihat `docs/BACKUP_RESTORE.md` untuk detail hubungan
`audio_assets.storage_path` dengan file fisik.

## 7. Batasan yang masih berlaku

- Background job masih berjalan di proses FastAPI yang sama; belum ada worker
  atau antrean terdistribusi.
- Belum ada autentikasi/RBAC. Jangan mengekspos port `8000` ke Internet tanpa
  reverse proxy dan pembatasan akses.
- Endpoint sensitif perlu ditinjau terhadap OWASP Top 10 2025 sebelum dipakai
  banyak orang.
- Satu meeting = satu recording. Rekaman kedua hanya lewat delete-then-add.
- Nama file, path absolut, dan data pengguna tidak boleh muncul di dokumen
  publik; gunakan placeholder `<USERPROFILE>`, `<folder-rekaman>`, dan
  `<rekaman-pengguna>`.

## 8. Menghentikan

```powershell
docker compose down
```

Perintah ini hanya menghentikan container. Volume `meetnote_data` dan
`meetnote_models` **tidak** dihapus. Jangan menambahkan flag `-v` karena itu
akan menghapus data dan model yang sudah diunduh.
