# Sprint 13 — Git Initialization Gate & Manual Acceptance Testing

## 1. Executive summary

Sprint 13 dilanjutkan setelah pengguna **menolak** persetujuan untuk menjalankan
`git init -b main`. Sesuai gate, tidak ada operasi Git write yang dilakukan.
Pekerjaan yang aman tetap diselesaikan:

- pre-Git audit read-only selesai;
- klasifikasi file A/B/C dibuat;
- rencana inisialisasi Git disajikan dan **tidak dieksekusi**;
- manual acceptance dijalankan hanya untuk skenario yang bisa dibuktikan otomatis
  dengan DB/storage test terisolasi;
- regression test backend, frontend, dan production build dijalankan ulang;
- checklist `docs/MANUAL_ACCEPTANCE_TEST.md` diperbarui dengan bukti, tanggal, dan
  status aktual;
- dokumentasi Sprint 13 dibuat.

Tidak ada database pengguna, audio pengguna, storage, backup, `node_modules`, atau
`dist` yang dihapus. Tidak ada commit, push, remote change, atau upload ke GitHub.
Repository tetap **belum diinisialisasi**.

## 2. Pre-Git audit

Audit read-only dilakukan pada 2026-11-24 dari
`<USERPROFILE>\Projects\meetnote-ai`.

### 2.1 Status Git

```text
.git di root / parent / recursive  => tidak ada
git rev-parse --show-toplevel      => fatal: not a git repository
git remote -v                      => fatal: not a git repository
git --version                      => git version 2.56.1.windows.1
```

### 2.2 Temuan filesystem

| Area | Temuan |
| --- | --- |
| Root | `backend/`, `frontend/`, `docs/`, `storage/`, `.env.example`, `.gitignore`, `README.md` |
| Backend | `app/`, `tests/`, `main.py`, `requirements.txt`, `.env.example`, 3 file DB |
| Frontend | `src/`, `tests/`, `dist/`, `node_modules/`, `package.json`, `package-lock.json`, konfigurasi, `.env.example` |
| Docs | `SPRINT1.md`–`SPRINT12.md`, `ARCHITECTURE.md`, `README.md`, 3 panduan; `SPRINT13.md` dibuat sprint ini |
| Storage produksi | `storage/` hanya berisi `.gitkeep` |
| Test data | `backend/test_storage/meetings/` berisi 2 file audio hasil test |
| Backup | `backups/` belum ada |
| Cache | `__pycache__/*.pyc` ada, termasuk stale `test_debug_tmp.*.pyc`; sudah terabaikan |
| Log/temp | Tidak ada `*.log`, `*.tmp`, `*.bak`, `*.orig`, `Zone.Identifier`, atau metadata Git |
| Build | `frontend/dist/` berisi 3 file; `tsconfig.tsbuildinfo` ada |

### 2.3 Environment

Hanya `.env.example` yang ditemukan di root, `backend/`, dan `frontend/`. Tidak
ada file `.env` aktif. Nama variabel saja yang dibaca: `APP_NAME`, `DEBUG`,
`DATABASE_URL`, `BACKEND_PORT`, `CORS_ALLOWED_ORIGINS`, `STORAGE_DIR`,
`MAX_AUDIO_FILE_BYTES`, `STT_*`, `DIARIZATION_*`, `LLM_*`, dan
`VITE_API_BASE_URL`. Nilai secret **tidak dibaca atau ditampilkan**.

### 2.4 Dependency

- Backend: seluruh dependency langsung dipatok eksak di `requirements.txt`.
- Frontend: `package-lock.json` ada, `lockfileVersion=3`, dan `rootMatch=true`
  terhadap `package.json`.
- Tidak ada upgrade dependency.

## 3. Git initialization status

| Item | Status |
| --- | --- |
| Persetujuan eksplisit | **Ditolak** oleh pengguna |
| `git init -b main` | Tidak dijalankan |
| `git add` / staging | Tidak dijalankan |
| `git commit` | Tidak dijalankan |
| `git push` | Tidak dijalankan |
| Remote | Tidak diubah |
| Upload ke GitHub | Tidak dilakukan |
| Status repository | **Belum diinisialisasi** |

Rencana yang disajikan pada Fase 2 tetap berlaku bila pengguna memberikan
persetujuan: inisialisasi di root proyek dengan branch `main`, validasi ignore
rules, preview `git add -n .`, staging eksplisit setelah persetujuan terpisah,
dan validasi staging tanpa commit.

## 4. File inclusion/exclusion review

### A. Aman untuk version control

- `.gitignore`, `.env.example`, `README.md`
- `backend/main.py`, `backend/requirements.txt`, `backend/.env.example`
- `backend/app/**/*.py`
- `backend/tests/*.py` — source test
- `frontend/.env.example`, `index.html`, `package.json`, `package-lock.json`,
  `tsconfig.json`, `vite.config.ts`
- `frontend/src/**/*`, `frontend/tests/*.test.ts`
- `docs/*.md`
- `storage/.gitkeep`

### B. Harus dikecualikan

- `.env`, `.env.*`, `*.env` kecuali `*.env.example`
- `*.db`, `*.sqlite`, `*.sqlite3`, sidecar `*.db-journal`/`-wal`/`-shm`
- `backend/meetnote.db`, `backend/api_test.db`, `backend/test.db`
- `backend/test_storage/**` — audio hasil test
- `storage/**` kecuali `.gitkeep` — audio pengguna
- `backups/**`
- `frontend/node_modules/**`, `frontend/dist/**`, `frontend/tsconfig.tsbuildinfo`
- `__pycache__/**`, `*.pyc`, `.pytest_cache/**`, `.venv/**`, `venv/**`, `.vite/**`
- `*.part`, `*.delete`, `*.log`, `*.tmp`, `*.bak`, `*.orig`

### C. Memerlukan keputusan pengguna

| Item | Rekomendasi |
| --- | --- |
| `frontend/dist/` | Tetap dikecualikan; build dari source |
| `backend/meetnote.db` | Tetap dikecualikan; dapat berisi data lokal |
| `backend/test_storage/**` | Tetap dikecualikan; source test tetap dimasukkan |
| Stale `test_debug_tmp.*.pyc` | Dibiarkan dan terabaikan |
| `backups/**` | Tetap dikecualikan; simpan `.env` terpisah |

`.gitignore` sudah mencakup seluruh kategori sensitif. Tidak ada perubahan yang
diperlukan.

## 5. Manual acceptance progress

Checklist diperbarui di `docs/MANUAL_ACCEPTANCE_TEST.md` dengan kolom `Bukti` dan
`Tanggal`.

| Metrik | Hasil |
| --- | --- |
| Total skenario | 26 |
| PASS | 6 |
| FAIL | 0 |
| BLOCKED | 1 |
| NOT TESTED | 19 |

Angka di atas adalah baseline pada akhir Sprint 13. Status terkini setelah
lanjutan Phase A/B 24–26 Nov ada di `docs/MANUAL_ACCEPTANCE_TEST.md` bagian 5.

### 5.1 Skenario PASS — clean installation (MAT-01)

MAT-01 dijalankan pada 2026-11-24 dengan prinsip **tidak menyentuh instalasi
utama**. Source/config disalin ke direktori temporer terpisah; seluruh DB, audio,
`node_modules`, `dist`, `.venv`, dan cache dikecualikan. Verifikasi awal menunjukkan
semua file sumber requisite hadir dan **nol** berkas terlarang (`*.db`, `*.wav`,
`*.webm`, `*.mp3`, `*.pyc`, `*.tsbuildinfo`) atau direktori terlarang
(`node_modules`, `dist`, `test_storage`, `__pycache__`) di clean dir.

```text
CLEAN_DIR=<USERPROFILE>\AppData\Local\Temp\opencode\meetnote-clean-20261124-114319
Python: py -3.12 --version => Python 3.12.10
Node: v24.22.1, npm: 11.19.1
```

Langkah instalasi sesuai `docs/INSTALLATION.md`:

```text
py -3.12 -m venv .venv                       -> sukses
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -> sukses
npm ci                                       -> added 69 packages, 0 vulnerabilities
npm run build                                -> 42 modules transformed, built in 1.24s
```

Versi terpasang membuktikan dependency sesuai pin: fastapi 0.115.12, SQLAlchemy
2.0.42, uvicorn 0.34.2. Tidak ada upgrade dependency.

Aplikasi dijalankan dari clean dir dengan DB dan storage **baru** di dalam clean
dir, provider mock, serta port alternatif agar tidak bentrok:

```text
DATABASE_URL=sqlite:///./clean_acceptance.db
STORAGE_DIR=<clean_dir>\storage\meetings
STT_PROVIDER=mock, DIARIZATION_PROVIDER=mock, LLM_PROVIDER=mock
DEBUG=false, BACKEND_PORT=8015
CORS_ALLOWED_ORIGINS=http://localhost:4175,http://127.0.0.1:4175
Frontend: vite preview --host 127.0.0.1 --port 4175 --strictPort
```

Bukti aktual:

```text
MAT01_BACKEND_HEALTH: {"status":"healthy","application":"MeetNote AI"}
MAT01_BACKEND_CONFIG: {"max_audio_file_bytes":26214400,"allowed_mime_types":["audio/mp4","audio/mpeg","audio/ogg","audio/wav","audio/webm","audio/x-m4a","audio/x-wav"],"allowed_extensions":[".m4a",".mp3",".mp4",".ogg",".wav",".webm"],"stt_provider":"mock","stt_configured":true,"diarization_provider":"mock","diarization_configured":true,"llm_provider":"mock","llm_configured":true}
MAT01_DIAGNOSTICS: {"status":"healthy","application":"MeetNote AI","sqlite_foreign_keys":1,"storage":{"storage_root_configured":true,"files_total":0,"metadata_total":0,"orphan_files":[],"temp_files":[],"trash_files":[],"metadata_without_file":[],"invalid_metadata_paths":0,"note":"Audit read-only; tidak ada file yang dihapus otomatis."}}
MAT01_FRONTEND: HTTP 200 contentLength=409
MAT01_FRESH_DB_EXISTS: True
MAT01_ORIGINAL_DB_HASH_BEFORE: 979D2C7ECEC87F21BD1DB1034606F47305AD9451A00EAA63B44DA022285E2F14
MAT01_ORIGINAL_DB_HASH_AFTER:  979D2C7ECEC87F21BD1DB1034606F47305AD9451A00EAA63B44DA022285E2F14
MAT01_ORIGINAL_DB_UNCHANGED: True
```

Catatan penting:

- `backend/clean_acceptance.db` baru dibuat di clean dir; `backend/meetnote.db`
  proyek utama tetap utuh (hash SHA-256 identik sebelum/sesudah).
- `backend/.venv`, `frontend/node_modules`, dan `frontend/dist` proyek utama tidak
  ditimpa; versi clean dir terpasang secara independen.
- Penyalinan `.env.example` ke `.env` tidak diperlukan karena konfigurasi mock
  diberikan lewat environment variable proses; tidak ada secret yang dibaca atau
  ditulis.
- Diagnostics menunjukkan storage kosong (0 file/0 metadata) dan tanpa anomali,
  sesuai kondisi instalasi baru.
- Frontend `HTTP 200` membuktikan build hasil `npm ci` tersaji tanpa error.
  Tampilan visual dan interaksi masih memerlukan MAT-04 dan tidak diklaim lulus.
- Kedua proses backend/frontend clean dir sudah dihentikan setelah pengujian.

### 5.1b Skenario PASS — otomatis, terisolasi (MAT-02, MAT-03, MAT-26)

Environment:

```text
DATABASE_URL=sqlite:///./api_test.db
STORAGE_DIR=<USERPROFILE>\Projects\meetnote-ai\backend\test_storage
STT_PROVIDER=mock, DIARIZATION_PROVIDER=mock, LLM_PROVIDER=mock
BACKEND_PORT=8013, DEBUG=false
Frontend: vite preview --host 127.0.0.1 --port 4173
Tanggal: 2026-11-24
```

Bukti aktual:

```text
MAT-02_HEALTH: {"status":"healthy","application":"MeetNote AI"}
MAT-03_FRONTEND: HTTP 200 contentLength=409
MAT-26_DIAGNOSTICS: {"status":"healthy","sqlite_foreign_keys":1,"files_total":2,"metadata_total":2,"orphan_files":0,"temp_files":0,"trash_files":0,"metadata_without_file":0,"invalid_metadata_paths":0,"orphan_paths":"","missing_paths":""}
```

Catatan penting:

- MAT-03 hanya membuktikan HTTP 200; tampilan visual belum diverifikasi.
- MAT-26 memakai DB/storage test; metadata dan file audio test sama-sama 2, tanpa
  anomali.
- Proses backend dan frontend yang dipakai untuk acceptance sudah dihentikan.
- Database dan audio pengguna (`backend/meetnote.db`, `storage/`) tidak dipakai.

### 5.1c Skenario PASS — interaksi browser (MAT-04)

Pada 2026-11-24 pengguna membuat meeting lewat UI di
`http://127.0.0.1:5173` dengan backend `http://127.0.0.1:8000`, DB test
`manual_acceptance.db`, storage `<clean_dir>\storage\meetings`, provider mock.

Bukti UI dari pengguna: halaman detail menampilkan judul `Rapat PHT`, ID
`edc18f01-b934-4d02-9956-8f12bec25759`, bagian Rekaman, Transkripsi, Diarisasi,
AI Summary, dan Action Items. Bukti API read-only:

```text
MEETINGS_COUNT=1
{"title":"Rapat PHT","id":"edc18f01-b934-4d02-9956-8f12bec25759",
 "status":"PENDING","created_at":"2026-11-24T04:51:57",
 "has_recording":true,"recording":{"id":"6f4e3ac1-a8d8-45a7-b988-95665217fdbd",
 "original_filename":"recording-1795496292027.webm",
 "storage_filename":"recording-202edd4a4e424344915dd0231617fca0.webm",
 "mime_type":"audio/webm","file_size_bytes":320963,"duration_seconds":19.904,
 "created_at":"2026-11-24T04:58:35"}}
DIAGNOSTICS: files_total=1, metadata_total=1, orphan_files=[],
temp_files=[], trash_files=[], metadata_without_file=[], invalid_metadata_paths=0
```

Catatan:

- Meeting dibuat dengan status awal `PENDING`; status akhir `FAILED` berasal dari
  kegagalan transkripsi mock, bukan dari pembuatan meeting atau rekaman.
- File audio WebM 19,904 detik / 320.963 byte benar-benar tersimpan di storage test
  dan sesuai metadata — ini membuktikan mikrofon dan MediaRecorder browser
  berfungsi. Indikator rekaman serta perilaku Pause/Resume kemudian dikonfirmasi
  pengguna secara eksplisit untuk MAT-05/MAT-06 pada 26 Nov (lihat 5.1u).
- Error transkripsi adalah perilaku disengaja: `registry.py` membuat
  `MockSttProvider()` tanpa segmen, sehingga `mock.py` melempar
  "Provider mock tidak diberi teks/segmen konfigurasi". Tidak ada env var untuk
  mengisinya; memperbaikinya memerlukan perubahan kode yang dilarang sprint ini.
  **Pembaruan Phase A/B:** setelah persetujuan eksplisit pengguna, env var fixture
  ditambahkan dan alur MAT-10 lulus; lihat 5.1f.
- Untuk MAT-07 dibuat fixture `test-fixtures/sample-silence.m4a` (1.747 byte,
  signature `ftyp`, AAC-LC 44,1 kHz mono) di clean dir. Validasi backend:
  `detected=audio/mp4`, ekstensi `.m4a` diterima, `signature_conflicts=False`.
  Karena satu meeting hanya boleh satu rekaman (409 jika duplikat), uji upload
  harus memakai meeting baru, bukan `Rapat PHT`.
- Temuan tambahan: upload `.mp4` lewat browser ditolak lebih awal oleh frontend
  dengan pesan `MIME type video/mp4 tidak didukung` (`useAudioFile.ts:88`). Browser
  memetakan ekstensi `.mp4` ke `video/mp4`, sedangkan `ACCEPTED_MIME` frontend dan
  `ALLOWED_AUDIO_TYPES` backend hanya memuat MIME `audio/*`. Akibatnya tombol/file
  picker yang menampilkan "M4A/MP4" (`AudioUploader.tsx:20,83`) tidak konsisten
  dengan validasi MIME. Backend tetap menerima kontainer MP4 jika MIME dikirim
  eksplisit sebagai `audio/mp4` (`extension_for_content_type` → `.m4a`); fixture
  `sample-silence.mp4` lolos `signature_conflicts=False`. Ini dicatat sebagai
  keterbatasan UI, bukan kegagalan MAT-07, dan **tidak diperbaiki dengan mengubah
  kode** sesuai aturan sprint.
- Defek UI lain ditemukan dan diperbaiki setelah persetujuan eksplisit pengguna:
  `NewMeeting.tsx:35` memasukkan `hasSelectedFile` ke `uploadDisabled`, sehingga
  memilih file lewat `AudioUploader` langsung mendisable tombol Upload Audio
  (`AudioUploader.tsx:49,76`). Perbaikan satu baris menghapus `hasSelectedFile`
  dari `uploadDisabled`; tombol rekaman tetap dijaga `recorderDisabled`. Build
  frontend tetap sukses (42 modules) dan 7 test tetap pass.
- MAT-07 akhirnya PASS: pengguna mengupload `Recording.m4a` miliknya sendiri
  (418.072 byte) lewat UI → `mime_type=audio/x-m4a`, `duration_seconds=18.88`,
  `storage_filename=recording-0b7018d34ec54ac38254e70a9a3d6d57.m4a`, diagnostics
  `files_total=1`, `metadata_total=1`, tanpa anomali.
- Transkripsi pada meeting tersebut awalnya berakhir `FAILED` dengan pesan mock;
  ini tidak mengubah status MAT-07. Pengguna lalu menyetujui perubahan test-only
  pada `registry.py`/`config.py`, sehingga MAT-10 akhirnya `PASS` (lihat 5.1f).

### 5.1d Skenario PASS — playback/seek (MAT-08)

Pada 2026-11-24 pengguna menguji pemutar audio native di browser pada meeting
`Rapat PHT` (`edc18f01-b934-4d02-9956-8f12bec25759`). Audio terdengar jelas.
Seek baru bisa diandalkan setelah rekaman diputar penuh sekali sehingga browser
selesai meng-buffer; setelah itu progress bar bisa digeser ke posisi yang
diinginkan dan audio lanjut tepat di posisi tersebut. Tidak ada error 404/415.

```text
PLAY: HTTP 200 content-type=audio/webm content-length=604929
      content-disposition=inline accept-ranges=bytes
RANGE bytes=100000-100100: HTTP 206 Partial Content
      content-range=bytes 100000-100100/604929
METADATA: duration_seconds=37.503 mime_type=audio/webm
      file_size_bytes=604929
      storage_filename=recording-728c0de90ed7459c9250329b997abdf7.webm
```

Catatan:

- Endpoint `/recording/play` memang mendukung Range (`accept-ranges: bytes`,
  `206`), jadi perilaku awal terkait buffering browser, bukan penolakan server.
- Refresh halaman mengulang kondisi awal: rekaman perlu ter-buffer lagi sebelum
  seek konsisten.
- Recording aktif saat MAT-08 berbeda dari file M4A pada bukti MAT-07; OpenCode
  tidak mengganti atau menghapus file audio apa pun.
- Transkrip awalnya tidak muncul karena `MockSttProvider()` menghasilkan respons
  kosong; kemudian diatasi lewat fixture test-only pada MAT-10 (lihat 5.1f) dan
  tidak mengubah bukti MAT-08.

### 5.1e Skenario PASS — menghapus audio (MAT-09)

Pada 2026-11-24 pengguna menekan `Delete Recording` pada `Rapat PHT`, menerima
konfirmasi `Hapus rekaman ini dari server? Tindakan ini tidak dapat dibatalkan.`,
dan melaporkan penghapusan berhasil tanpa error. Pengguna kemudian menambahkan
rekaman baru, sehingga kondisi server akhir bukan lagi keadaan pasca-hapus murni.

```text
FILE_LAMA: recording-728c0de90ed7459c9250329b997abdf7.webm (604929 B) -> tidak ada
FILE_BARU: recording-8e148889ca8140aab226b6d04c3529b9.webm (208523 B, 12.873 dtk)
CREATED_AT: 2026-11-24T11:09:29
DIAGNOSTICS: files_total=1 metadata_total=1 orphan_files=[]
             metadata_without_file=[] invalid_metadata_paths=0
```

Catatan:

- Status `PENDING` langsung setelah hapus tidak dicatat terpisah karena pengguna
  segera menambahkan rekaman baru; UI menampilkan pesan sukses tanpa error.
- `recordings.py:283-322` memindahkan file ke nama `.delete` sebelum commit, lalu
  menghapus sisa file tersebut setelah commit berhasil. Jadi tidak adanya file
  `.delete` di akhir adalah perilaku yang dirancang, bukan penghapusan paksa.
- Rekaman baru awalnya berakhir `FAILED` karena mock STT tanpa segmen; setelah
  fixture test-only diaktifkan, rekaman yang sama berhasil ditranskripsi pada
  MAT-10 (lihat 5.1f). Ini bukan kegagalan MAT-09.

### 5.1f Skenario PASS — transkripsi (MAT-10)

Setelah pengguna menyetujui perubahan test-only kedua, provider `mock` dapat
diisi lewat `MOCK_STT_SEGMENTS_JSON`. Backend test direstart dengan 3 segmen
fixture, pengguna menekan **Transcribe** di UI, lalu API read-only menunjukkan:

```text
STATUS: COMPLETED  PROVIDER: mock  MODEL: mock-1  HAS_TIMESTAMPS: true
ERROR: ""
SEGMENTS: 3
  [0.0-3.0]   [MOCK] Rapat dibuka.
  [3.0-7.0]   [MOCK] Poin pertama dibahas.
  [7.0-11.0]  [MOCK] Tindak lanjut dicatat.
MEETING_STATUS: TRANSCRIBED
```

Perubahan kode yang disetujui:

- `backend/app/core/config.py`: `MOCK_STT_TEXT`, `MOCK_STT_SEGMENTS_JSON`
- `backend/app/services/stt/registry.py`: parse fixture dan meneruskannya ke
  `MockSttProvider`; provider lain tidak berubah
- `backend/tests/test_mock_stt_fixture.py`: 4 test baru
- Regression backend: `233 passed, 1 warning` (Sebelumnya 229)

Catatan: tidak ada provider live, kredensial, atau secret yang dipakai. Teks
selalu berawalan `[MOCK]` agar tidak tertukar dengan transkripsi asli.

### 5.1g Bukti API lanjutan (MAT-11–MAT-24)

Setelah MAT-10, OpenCode membuat file audio uji sendiri di
`<clean_dir>\test-fixtures\sample-voice-synthetic.wav` (WAV 12 detik, 384.044
byte, nada 220 Hz yang dihasilkan lokal dengan `wave`; bukan audio pengguna).
Pengujian berikut memakai DB `manual_acceptance.db`, storage test yang sama, dan
provider `mock` untuk STT/diarisasi/LLM. Semua bukti di bawah adalah **API/DB**,
bukan konfirmasi browser; status manual MAT-11–MAT-24 tetap `NOT TESTED`,
kecuali MAT-11, MAT-12, MAT-13, MAT-14, MAT-15, MAT-16, MAT-17, MAT-18, MAT-19,
MAT-20, MAT-21, MAT-22, MAT-23, dan MAT-24 yang kemudian dikonfirmasi di UI pada
bagian 5.1i, 5.1j, 5.1k, 5.1l, 5.1h, 5.1m, 5.1n, 5.1o, 5.1p, 5.1q, 5.1r, 5.1s,
dan 5.1t.

| ID | Hasil | Bukti ringkas |
| --- | --- | --- |
| MAT-11 | Lulus API + UI | Diarisasi `COMPLETED`, `turns_count=2`, `mapped_segments=2`; `Speaker 1` dan `Speaker 2` masing-masing 1 segmen. Percobaan pertama dengan segmen 0–3/3–7/7–11 hanya memetakan 1 segmen karena turn mock default hanya 0–4 dtk; diulang dengan fixture 0–2/2–4. UI dikonfirmasi pengguna pada `cd8f6299-…` (lihat 5.1i). |
| MAT-12–14 | Lulus API + UI | Teks segmen `0.0–2.0` diubah; timestamp tetap. Nama tampilan `Speaker 1` → `Rani` persist. Assignment segmen dipindah ke `Speaker 2`; after re-fetch `Speaker 1 count=0`, `Speaker 2 count=2`. Summary/action items tetap `COMPLETED`. UI MAT-12, MAT-13, dan MAT-14 dikonfirmasi pengguna pada `cd8f6299-…` (lihat 5.1j, 5.1k, dan 5.1l). |
| MAT-15 | Lulus API + UI | Summary `COMPLETED`, `is_mock=True`, overview `[MOCK] Ringkasan dari …`, 1 topik dengan 3 referensi segmen pada meeting `1799ace9-…`; tanpa error. UI dikonfirmasi pengguna dengan WAV bersuara pada `38b174b1-…` (lihat 5.1h). |
| MAT-16 | Lulus API + UI | Topic `start=5.0`, `end=15.642`, `refs=2` pada meeting `e32b6779-…`; klik `▶ 0:05.0–0:15.6` menggeser posisi ke ~`0:05`. Permintaan pengguna: klik harus langsung memutar, bukan sekadar seek; perbaikan frontend `playAfterSeek` sudah dikonfirmasi pengguna (langsung berjalan tanpa Play manual). Lihat 5.1m. |
| MAT-17–20 | Lulus API + UI | Ekstrak 1 item `[MOCK]` (UI MAT-17 pada `e32b6779-…`, lihat 5.1n), edit judul/deskripsi/assignee/deadline/due date (`is_manually_edited=True`, UI MAT-18 pada `de18f75b-…`, lihat 5.1o), status `OPEN → COMPLETED → CANCELLED → OPEN` dikonfirmasi UI (lihat 5.1p), hapus satu item (`200 OK`, lihat 5.1q), hapus semua lewat UI dengan dialog konfirmasi pada `38b174b1-…` dan `cd8f6299-…` (`200 OK`, lihat 5.1q). Transkrip, audio, dan summary tidak ikut terhapus. MAT-19/20 juga sudah UI. |
| MAT-21 | Lulus API + UI | UI mengunduh `notulen-cd8f6299 (2).txt` (1.864 byte) di `<USERPROFILE>\Downloads`; SHA256 identik dengan API `/export/txt`. Isi memuat judul, status `COMPLETED`, 2 speaker, ringkasan, topik, action item, dan 2 baris transkrip. Nama fallback aman karena CORS tidak mengekspos `Content-Disposition`. Lihat 5.1r. |
| MAT-22 | Lulus UI | UI mengunduh `notulen-cd8f6299 (2).pdf` (44.446 byte); `%PDF-1.4`, `%%EOF`, 2 halaman. Teks diekstrak dengan `pypdf`: semua bagian dan frasa Indonesia terbaca tanpa mojibake, isi sesuai TXT. Tidak ada file sementara di server (diagnostics 10 file/10 metadata). Lihat 5.1r. |
| MAT-23 | Lulus API + UI | Poller DB 1 ms menangkap `PROCESSING → COMPLETED`. UI: pada `501f58dd…`, F5 saat `PROCESSING` (jeda 8 detik di salinan backend test) tetap menampilkan status background, lalu 2 segmen muncul sendiri; API akhir `COMPLETED`, meeting `TRANSCRIBED`, tanpa job `PROCESSING`. Lihat 5.1s. |
| MAT-24 | Lulus API + UI | Dry-run API: job `PROCESSING` dimatikan → start ulang → `FAILED` + pesan restart, meeting `FAILED`, 0 segmen; retry → `COMPLETED` 2 segmen. UI: penjaga otomatis mematikan backend saat `PROCESSING` dan menyalakan ulang; setelah F5 pengguna melihat `FAILED` + pesan restart, retry menghasilkan `COMPLETED` 2 segmen / meeting `TRANSCRIBED`. Tidak ada job `PROCESSING` menetap. Lihat 5.1t. |
| MAT-26 | Konsisten | Diagnostics berulang: 2→3→4→6 file/metadata, `orphan_files=[]`, `metadata_without_file=[]`, `invalid_metadata_paths=0`. |

Temuan dokumentasi:

- MAT-19 checklist menulis `IN_PROGRESS → DONE`, tetapi skema `ActionItemUpdate`
  memakai `OPEN | COMPLETED | CANCELLED`. `IN_PROGRESS` ditolak `422`. Ini
  dicatat sebagai ketidaksesuaian dokumen, bukan bug aplikasi.
- Script bantu `inspect_jobs.py`, `poll_job.py`, `kill_on_processing.py`, dan
  `simulate_stuck.py` dibuat di folder Temp, bukan di proyek.
- DB/audio proyek utama (`backend/meetnote.db`, `storage/`) tidak disentuh;
  tidak ada provider live, kredensial, atau secret yang dipakai.

### 5.1h Skenario PASS — AI Summary dengan audio bersuara (MAT-15)

Setelah pengguna menyatakan hasil pada WAV nada murni kurang bermakna karena
tidak ada suara, OpenCode membuat `test-fixtures\sample-voice-tts.wav` memakai
Windows SAPI/TTS (`Microsoft Zira Desktop`, en-US). File ini benar-benar berisi
ucapan, bukan nada: 22.050 Hz mono, 15,642 detik, 689.852 byte, peak `23007`,
RMS `3205,6`, 74% sampel nonzero. Tidak ada API/cloud atau kredensial yang
dipakai.

Backend test direstart hanya dengan env `MOCK_STT_SEGMENTS_JSON` tiga segmen
yang sepadan dengan isi ucapan. Meeting baru `Uji Suara TTS 20261124`
(`38b174b1-5d7e-4a0d-97f2-369810754ffe`) dibuat; upload `audio/wav` diterima;
transkripsi `COMPLETED` dengan 3 segmen; summary `COMPLETED`, `is_mock=True`.
Playback: `HTTP 200`, `content-type: audio/wav`, `content-length: 689852`,
`accept-ranges: bytes`. Diagnostics: 7 file / 7 metadata tanpa anomali.

Pengguna lalu mengonfirmasi UI secara eksplisit:

```text
Status transkripsi: COMPLETED  Provider: mock  Model: mock-1  Segmen: 3
  0:00-0:05  [MOCK] The meeting is open. We are reviewing the AI summary feature.
  0:05-0:10  [MOCK] The decision today is that summaries are generated only from stored transcripts.
  0:10-0:15  [MOCK] Action item: the user will verify the result in the browser.
Status ringkasan: COMPLETED  Provider: mock  Model: mock-1
Topik: 1  Keputusan: 0
Notice: [MOCK] Provider simulasi sedang dipakai. Ini bukan ringkasan AI sungguhan.
Overview: [MOCK] Ringkasan dari 3 segmen transkrip rapat Uji Suara TTS 20261124.
Topics: [MOCK] Topik dari transkrip -> 0:00.0-0:15.6
  [MOCK] Cuplikan awal: [MOCK] The meeting is open. We are reviewing the AI summary feature.
Decisions: Tidak ada keputusan eksplisit yang tercatat dari transkrip.
Tidak ada error merah.
```

Catatan: audio kini benar-benar bersuara, tetapi teks transkrip masih berasal
dari fixture `mock` yang saya samakan dengan ucapan. Ini **bukan** STT/AI
sungguhan; MAT-25 saat itu masih `BLOCKED` tanpa provider live yang disetujui,
lalu dibuktikan lewat kegagalan mock terkontrol pada 26 Nov (lihat 5.1v).

### 5.1i Skenario PASS — diarisasi dengan audio bersuara (MAT-11)

Untuk menghindari hasil yang ambigu, OpenCode membuat WAV TTS pendek
`test-fixtures\sample-voice-diarization.wav` (22.050 Hz mono, 4,544 dtk,
200.434 byte; peak `20879`, RMS `2735,9`, 64% sampel nonzero) berisi dua
kalimat: "Speaker one says hello. Speaker two replies." Backend test direstart
dengan fixture `0–2`/`2–4`; meeting `Uji Diarisasi UI 20261124`
(`cd8f6299-e7d6-42fb-86df-ecb40e80cf01`) dibuat, upload diterima, dan
transkripsi disiapkan lewat API dengan 2 segmen tanpa speaker. Diarisasi
sengaja dibiarkan `NOT_STARTED` agar aksi UI pengguna yang memicunya.

Pengguna mengklik **Diarize Speakers** dan melaporkan:

```text
Status diarisasi: COMPLETED  Provider: mock  Model: mock-1
Speaker: 2  Segmen dipetakan: 2
Notice: [MOCK] Provider simulasi sedang dipakai. Ini bukan hasil diarisasi sungguhan.
Speaker 1 — 1 segmen
Speaker 2 — 1 segmen
Tidak ada error merah.
```

Verifikasi API read-only:

```text
turns_count=2  mapped_segments=2  is_mock=true
[0.0-2.0]  Speaker 1 | [MOCK] Speaker one says hello.
[2.0-4.0]  Speaker 2 | [MOCK] Speaker two replies.
```

Catatan: label tetap anonim dan tidak menebak identitas dunia nyata. Pengguna
juga mencatat tombol `Edit Nama` tidak menampilkan durasi/minit; ini dicatat
sebagai pengamatan UI kecil, bukan kriteria MAT-11.

### 5.1j Skenario PASS — menyunting teks segmen (MAT-12)

Pada meeting yang sama (`cd8f6299-e7d6-42fb-86df-ecb40e80cf01`), pengguna
mengklik **Edit** pada segmen pertama `0:00–0:02`, menambahkan `ai ai kapten`
sehingga teks menjadi `[MOCK] Speaker one says hello.ai ai kapten`, lalu
mengklik **Save**. UI menampilkan `Teks segmen disimpan.` dan langsung
menampilkan teks baru.

Verifikasi API read-only:

```text
SEG 1: [0.0-2.0]  Speaker 1 | [MOCK] Speaker one says hello.ai ai kapten
SEG 2: [2.0-4.0]  Speaker 2 | [MOCK] Speaker two replies.
```

Timestamp, speaker, dan segmen kedua tidak berubah. Pengguna tidak menyebut
secara eksplisit bahwa `Ctrl+F5` dilakukan, tetapi persistensi di server
terbukti dari `GET` setelah edit. Status transkripsi tetap `COMPLETED`;
diagnostics 8 file / 8 metadata tanpa anomali.

Catatan: pengguna memilih menambahkan teks, bukan mengganti seluruhnya. Kriteria
MAT-12 adalah teks tersimpan dan timestamp/speaker tidak berubah.

### 5.1k Skenario PASS — mengubah nama tampilan speaker (MAT-13)

Pada meeting `cd8f6299-e7d6-42fb-86df-ecb40e80cf01`, pengguna mengklik
**Edit Nama** pada `Speaker 1`, mengisi `Capten 1`, klik **Save**, lalu melakukan
reload. Verifikasi API read-only:

```text
Speaker 1: speaker_label=Speaker 1 (tidak berubah)  display_name=Capten 1  segment_count=1
Speaker 2: speaker_label=Speaker 2  display_name=(kosong)  segment_count=1
SEG [0.0-2.0]: speaker_display_name=Capten 1 | [MOCK] Speaker one says hello.ai ai kapten
SEG [2.0-4.0]: speaker_display_name=(kosong)  | [MOCK] Speaker two replies.
```

Label anonim tidak dapat diubah; hanya nama tampilan yang berubah. Teks hasil
MAT-12 tetap utuh dan diagnostics 8 file / 8 metadata tanpa anomali. Catatan:
pengguna mengisi `Capten 1` (mungkin typo dari `Kapten`); kriteria MAT-13 tetap
terpenuhi karena nama tampilan tersimpan dan label/ID speaker tidak berubah.

### 5.1l Skenario PASS — memindahkan assignment speaker (MAT-14)

Pada meeting yang sama, pengguna mengganti dropdown speaker segmen `0:00–0:02`
dari `Capten 1` menjadi `Speaker 2`. Perubahan langsung tersimpan (tanpa tombol
Save). UI menunjukkan:

```text
SEG [0:00-0:02]  Speaker 2 | [MOCK] Speaker one says hello.ai ai kapten
SEG [0:02-0:04]  Speaker 2 | [MOCK] Speaker two replies.
Capten 1 (Speaker 1) — 0 segmen
Speaker 2 — 2 segmen
```

Verifikasi API: `Speaker 1 display=Capten 1 count=0`, `Speaker 2 count=2`;
kedua segmen `speaker_label=Speaker 2`; diarisasi tetap `COMPLETED` dengan
`mapped_segments=2`. Speaker lama tidak dihapus, hanya kehilangan segmen. Teks
hasil MAT-12 dan timestamp tidak berubah. Diagnostics 8 file / 8 metadata tanpa
anomali.

### 5.1m Skenario PASS — referensi waktu topik dan autoplay (MAT-16)

Meeting uji dibuat terpisah agar referensi tidak mulai dari `0:00`:
**Uji Referensi Waktu 20261124** (`e32b6779-92a9-41d5-8b7d-b00f72b838a8`).
Memakai WAV TTS lokal 15,642 dtk / 689.852 B; transkrip 2 segmen
`5.0–10.0` dan `10.0–15.642` dari fixture mock; summary `COMPLETED` dengan
1 topik `start=5.0`, `end=15.642`, `refs=2`. Playback `HTTP 200`,
`audio/wav`, `accept-ranges: bytes`; diagnostics 9 file / 9 metadata tanpa
anomali.

Pengguna mengklik `▶ 0:05.0–0:15.6` di **AI Summary → Topics** setelah
meng-buffer audio dan menggeser pemutar ke `0:00`. Klik menggeser posisi ke
~`0:05`. Permintaan pengguna: tombol harus langsung memutar, bukan hanya
menggeser posisi. Perbaikan frontend:

- `frontend/src/components/MeetingDetail.tsx`: fungsi `playAfterSeek(audio)`
  memanggil `audio.play()` setelah `currentTime` di-set, baik untuk seek
  langsung maupun setelah `loadedmetadata`; `play()` dibungkus `.catch()` agar
  penolakan autoplay browser tidak menampilkan error mengganggu.
- `frontend/src/components/TranscriptEditor.tsx`: teks bantuan diperbarui
  menjadi “Klik timestamp untuk memutar rekaman dari posisi itu.”

Perbaikan disalin ke clean dir (hash `MATCH`), frontend `npm test` 7 pass/0 fail,
`npm run build` 42 modules transformed sukses. Setelah **Ctrl+F5**, pengguna
mengonfirmasi audio langsung berjalan dari ~`0:05` tanpa menekan Play, suara
mulai dari “The decision today…”, tanpa error. Status MAT-16 menjadi `PASS`.

### 5.1n Skenario PASS — membuat action items (MAT-17)

Pada meeting `e32b6779-92a9-41d5-8b7d-b00f72b838a8` (state awal
`NOT_STARTED`, 0 item), pengguna mengklik **Generate Action Items** di bagian
**Action Items**. UI menampilkan notifikasi `Action items selesai diekstrak dari
transkrip tersimpan.`, status ekstraksi `COMPLETED`, provider `mock`, model
`mock-1`, notice `[MOCK]`, serta 1 item:

```text
[MOCK] Tindak lanjut dari transkrip   OPEN   ▶ 0:05.0–0:15.6
[MOCK] Cuplikan: [MOCK] The decision today is that summaries are generated only from stored transcripts.
Penanggung jawab: —
```

Verifikasi API read-only: `status=COMPLETED`, `provider=mock`,
`model=mock-1`, `is_mock=True`, `items=1`, `error=` kosong. Item:
`title=[MOCK] Tindak lanjut dari transkrip`, `status=OPEN`,
`is_manually_edited=False`, `assignee_text` dan `deadline_text` kosong
(tidak dikarang), `segment_ids` berisi 2 referensi. Diagnostics 9 file /
9 metadata tanpa anomali. Tombol berubah menjadi `Regenerate Action Items`
setelah hasil ada; ini alur yang sama, bukan item kedua.

Catatan 25 Nov: state `e32b6779…` sempat hilang setelah transkrip dihapus
(menghapus segmen juga menghapus ringkasan dan action item). Meeting tersebut
dipulihkan lewat API dengan fixture mock yang sudah diperbaiki; item MAT-17
dibuat ulang. Bukti MAT-17 tanggal 24 Nov tetap sah sebagai bukti yang pernah
terverifikasi.

### 5.1o Skenario PASS — mengedit action item (MAT-18)

Pada 25 Nov, pengguna mengklik **Edit** pada action item di meeting buangan
**Uji Env Fixture 20261125** (`de18f75b-211d-4d54-a68c-21310d77621c`) —
meeting ini dibuat untuk membuktikan perbaikan `MOCK_STT_SEGMENTS_JSON`, dan
browser masih berada di halaman itu ketika MAT-18 dijalankan. Pengguna
mengganti judul dan deskripsi lalu klik **Simpan**.

Verifikasi API read-only:

```text
title=[MOCK] Tindak lanjut dari transkrip  →  Tindak Lanjut MAT-18
description=Verifikasi hasil di browser oleh pengguna MAT-18.
status=OPEN  is_manually_edited=True
assignee_text=(kosong)  deadline_text=(kosong)  due_date=(kosong)
start=5.0  end=15.642  segment_ids=2
```

Transkrip meeting itu tetap `COMPLETED` dengan 2 segmen. Kriteria MAT-18
(perubahan tersimpan lewat UI) terpenuhi. Item di `e32b6779…` sengaja
dibiarkan `OPEN` dan belum diedit untuk keperluan MAT-19.

Catatan perbaikan lingkungan 25 Nov: nilai `MOCK_STT_SEGMENTS_JSON` yang
ditampilkan sebelumnya mengandung backslash sebelum tanda kutip, sehingga
`json.loads` menolaknya dengan pesan `MOCK_STT_SEGMENTS_JSON bukan JSON yang
valid.` Nilai diperbaiki menjadi JSON polos; backend di-restart, dan uji
transkripsi API menghasilkan 2 segmen `5.0–10.0` / `10.0–15.642` tanpa error.
Diagnostics akhir 10 file / 10 metadata tanpa anomali.

### 5.1p Skenario PASS — mengubah status action item (MAT-19)

Pada meeting `e32b6779-92a9-41d5-8b7d-b00f72b838a8`, item
`c3f646c2-99ae-4912-becb-11376933982e` berstatus `OPEN`. Pengguna
mengklik tombol UI secara berurutan:

```text
✓ Selesai   → COMPLETED
Batalkan    → CANCELLED
Buka lagi   → OPEN
```

Setelah `Ctrl+F5`, verifikasi API menunjukkan status akhir `OPEN`,
judul `[MOCK] Tindak lanjut dari transkrip`, deskripsi dan 2 referensi
segmen tidak berubah, transkrip dan ringkasan tetap `COMPLETED`, diagnostics
10 file / 10 metadata tanpa anomali. `is_manually_edited` menjadi `True`
karena perubahan status melalui UI juga dicatat sebagai suntingan manual;
judul/deskripsi tidak diubah.

Catatan: checklist lama menulis `OPEN → IN_PROGRESS → DONE`, tetapi skema
implementasi memakai `OPEN | COMPLETED | CANCELLED`; nilai `IN_PROGRESS`
ditolak `422`. Status akhir dikembalikan `OPEN` agar MAT-20 dapat menghapus
item yang sama.

### 5.1q Skenario PASS — menghapus action item (MAT-20)

Dua bagian checklist dikonfirmasi terpisah lewat UI pada 25 Nov.

**Bagian 1 — hapus satu item.** Pada **Uji Referensi Waktu 20261124**
(`e32b6779-92a9-41d5-8b7d-b00f72b838a8`), pengguna mengklik tombol **Hapus**
pada baris action item `f4df41ee-9134-4b28-a7ad-b4a609843e4e` dan menyetujui
dialog `Hapus action item "…"?`. Log API:

```text
POST   /api/v1/meetings/e32b6779…/action-items                     202 Accepted
DELETE /api/v1/meetings/e32b6779…/action-items/f4df41ee…           200 OK
```

Item yang dihapus adalah hasil generate/regenerate terakhir (bukan
`c3f646c2…` dari MAT-19, yang sudah tergantikan). Verifikasi setelah refresh:
`items=0`, transkrip `COMPLETED` dengan 2 segmen.

**Bagian 2 — hapus semua.** Pengguna mengklik **Hapus Semua Action Items** pada
**Uji Suara TTS 20261124** (`38b174b1-5d7e-4a0d-97f2-369810754ffe`) dan
**Uji Diarisasi UI 20261124** (`cd8f6299-e7d6-42fb-86df-ecb40e80cf01`),
lalu menyetujui dialog *“Hapus seluruh action items? Transkrip dan rekaman audio
tidak akan dihapus.”* Log API mencatat `DELETE /api/v1/meetings/{id}/action-items`
→ `200 OK` untuk kedua meeting. Frontend memanggil endpoint itu hanya setelah
`window.confirm` bernilai benar, jadi dialog terkonfirmasi.

Verifikasi DB read-only setelah `Ctrl+F5`:

```text
38b174b1…  items=0  transkrip=COMPLETED/3  summary=COMPLETED  audio=689852 B
cd8f6299…  items=0  transkrip=COMPLETED/2  audio=200434 B
diagnostics: 10 file / 10 metadata, tanpa anomali
```

Transkrip, audio, dan summary tidak ikut terhapus — sesuai pesan dialog dan
implementasi `delete_action_items` / `delete_action_item`. Meeting
`Uji Diarisasi 20261124` (`c01d7eef…`) yang disarankan untuk bagian 2 masih
memiliki 1 item (`607bce17…`) karena browser berada di meeting lain saat
penghapusan; bukti di dua meeting test lainnya tetap memenuhi kriteria MAT-20.

### 5.1r Skenario PASS — ekspor TXT dan PDF (MAT-21/22)

Pada 25 Nov, pengguna mengklik **Unduh TXT** dan **Unduh PDF** di panel
**Ekspor Notulen**. Unduhan terjadi di **Uji Diarisasi UI 20261124**
(`cd8f6299-e7d6-42fb-86df-ecb40e80cf01`) — bukan `c01d7eef…` yang disarankan —
setelah meeting itu sendiri diberi diarisasi, ringkasan, dan action item, sehingga
ekspor kedua memuat konten lengkap. File di `<USERPROFILE>\Downloads`:

```text
notulen-cd8f6299 (2).txt   1.864 byte   SHA256 = API /export/txt
notulen-cd8f6299 (2).pdf  44.446 byte   %PDF-1.4 ... %%EOF, 2 halaman
```

Isi TXT/PDF: judul `Uji Diarisasi UI 20261124`; status transkripsi, diarisasi,
ringkasan, dan action items `COMPLETED`; `Speaker 1` dan `Speaker 2`; ringkasan
`[MOCK] Ringkasan dari 2 segmen transkrip rapat Uji Diarisasi UI 20261124.`;
1 topik; 1 action item `[OPEN] [MOCK] Tindak lanjut dari transkrip`; 2 baris
transkrip `[0:05 - 0:10]` dan `[0:10 - 0:15]`.

Verifikasi PDF dengan `pypdf`: teks halaman dapat diekstrak (1.358 karakter),
frasa Indonesia seperti `RINGKASAN EKSEKUTIF`, `dibuat`, `transkrip`, dan
`Belum tersedia` terbaca tanpa mojibake. Satu catatan: entitas `&bull;` untuk
penanda speaker diekstrak pypdf sebagai karakter replacement, tetapi seluruh
kata Indonesia terbaca dan tidak memengaruhi isi.

Catatan nama file: backend mengirim `Content-Disposition` berisi nama ramah,
tetapi CORS tidak mengekspos header itu, sehingga frontend memakai fallback aman
`notulen-<8 karakter id>.<ext>`; browser menambah suffix `(2)` karena file dengan
nama sama sudah ada. Kriteria "nama aman" tetap terpenuhi. Folder Unduhan juga
memiliki dua ekspor awal dari meeting yang sama saat datanya belum lengkap
(1.390 / 43.774 byte); file lama itu sengaja tidak dihapus.

Diagnostics akhir: 10 file / 10 metadata, tanpa file sementara, orphan, atau
metadata tanpa file.

### 5.1s Skenario PASS — refresh halaman saat job berjalan (MAT-23)

Karena provider mock menyelesaikan transkripsi dalam milidetik, dengan
persetujuan pengguna saya menambahkan jeda buatan **8 detik** hanya di salinan
backend test-terisolasi (`<clean_dir>\backend\app\services\stt\mock.py`, env
`MOCK_STT_DELAY_SECONDS=8`). Kode repo, skema, dependency, dan data pengguna
tidak diubah. Uji API pendahulu menunjukkan status `PROCESSING` teramati dan
berakhir `COMPLETED` dalam 8,4 detik dengan 2 segmen.

Pada 25 Nov, pengguna mengklik **Transcribe** di **Uji Refresh Browser 2
20261125** (`501f58dd-e8ad-4bee-a548-16c4f9499f08`), lalu menekan **F5** dalam
1–3 detik dan tidak mengklik apa pun selama ~10 detik. Setelah refresh, UI
menampilkan tombol `Memproses…` dan pesan *“⏳ Transkripsi sedang diproses di
background. Silakan tunggu atau tekan Refresh.”*; setelah jeda berakhir, UI
menampilkan 2 segmen dan tombol kembali `Transcribe`. Pengguna mengonfirmasi
tampilan akhir itu.

Log API menunjukkan satu `POST .../transcription` → `202 Accepted`, polling
`GET .../transcription` tetap berlangsung dari halaman hasil refresh, tanpa
`409`. Verifikasi akhir: `status=COMPLETED`, `segments=2`, `error` kosong,
meeting `TRANSCRIBED`, rekaman masih ada, dan tidak ada job `PROCESSING` yang
menetap di seluruh meeting. Diagnostics 12 file / 12 metadata tanpa anomali.

Catatan: percobaan pertama pada `262b7ff8…` tidak dipakai sebagai bukti karena
pengguna menghapus rekaman di tengah uji, yang menghapus seluruh state
transkripsi sesuai desain. Percobaan kedua memakai meeting baru yang sengaja
disiapkan.

### 5.1t Skenario PASS — restart backend saat job berjalan (MAT-24)

Dry-run API pendahulu memakai meeting buangan `09d9a0b1…`: job `PROCESSING`
sengaja dimatikan bersama backend lalu aplikasi distart ulang dengan env yang
sama. Startup recovery mengubah job menjadi `FAILED` dengan pesan *“Proses
transkripsi terhenti karena aplikasi dimulai ulang. Silakan coba lagi.”*, meeting
menjadi `FAILED`, 0 segmen. Retry menghasilkan `COMPLETED` dengan 2 segmen dan
meeting `TRANSCRIBED` dalam 8,4 detik. Ini membuktikan jalur recovery sebelum
uji UI.

Untuk bagian UI, backend berjalan sebagai proses tersembunyi yang dikelola
harness, sehingga restart dilakukan dari sisi harness, bukan Ctrl+C manual.
Karena jeda mock 8 detik lebih pendek dari waktu reaksi, saya menjalankan penjaga
otomatis (`mat24-watcher.ps1`) yang memantau `GET .../transcription` tiap 300 ms
dan langsung mematikan/menstart ulang backend begitu status `PROCESSING` muncul.

Pada 26 Nov pukul 09:13:27, penjaga mendeteksi `PROCESSING` pada **Uji Restart
Backend 2 20261125** (`47e69116-2ba5-49c6-ab44-798ecc3fc2e6`) dan mematikan
backend; start ulang selesai 09:13:30. Marker hasil: `STATUS_AFTER=FAILED`,
`ERROR=Proses transkripsi terhenti karena aplikasi dimulai ulang. Silakan coba
lagi.`, `SEGMENTS=0`, `HEALTH=healthy`. Setelah F5, pengguna mengonfirmasi UI
menampilkan status `FAILED` beserta pesan tersebut dan tombol retry tersedia.
Pengguna mengklik retry; verifikasi API langsung menunjukkan `COMPLETED`, 2
segmen (`5.0–10.0` dan `10.0–15.642`), meeting `TRANSCRIBED`. Log mencatat dua
`POST .../transcription` → `202 Accepted` (sebelum mati dan saat retry), tanpa
`409` atau duplikat data. Setelah bukti diambil, pengguna menghapus transkrip
(`DELETE .../transcription` → `200 OK`), sehingga state akhir meeting kembali
`NOT_STARTED`; ini tidak mengubah bukti MAT-24.

Verifikasi akhir: 0 job `PROCESSING` yang menetap, diagnostics 15 file / 15
metadata tanpa orphan, file sementara, atau metadata tanpa file. Percobaan UI
pertama (`b89329e7…`) tidak dipakai karena job selesai sebelum backend sempat
dimatikan.

### 5.1u Skenario PASS — rekaman browser dan Pause/Resume/Stop (MAT-05/06)

Pada 26 Nov, pengguna membuat meeting **Uji Rekam Browser 20261126**
(`289175d8-e414-48fb-a82d-e6147d25eaba`) lewat halaman **New Meeting**,
mengizinkan akses mikrofon di browser, lalu menekan **● Start Recording**.
Indikator berubah menjadi `recording` dan timer berjalan. Pengguna menekan
**❚❚ Pause**, menunggu ~2 detik, lalu **▶ Resume**, dan mengonfirmasi indikator
berubah menjadi `paused` lalu `recording` serta **timer berhenti saat jeda dan
lanjut kembali**. Setelah **■ Stop Recording**, muncul satu **Preview Rekaman**;
pengguna menekan **Save Recording** dan melihat pesan **“✅ Rekaman berhasil
disimpan ke server.”** di halaman detail bersama pemutar audio.

Verifikasi API: satu `AudioAsset` (`9a00ab41-d519-4e94-8845-0c879d811c94`),
`original_filename=recording-1795659875641.webm`,
`storage_filename=recording-92da0dc86e244c1a92f87e9da345cf55.webm`,
`mime_type=audio/webm`, `file_size_bytes=830759`, `duration_seconds=51.401`;
`GET .../recording/play` → `206 Partial Content`. Hanya ada satu asset pada
meeting ini, sehingga `Stop` menghasilkan satu file, bukan beberapa. Log backend
mencatat `POST .../recording` → `201 Created`. Diagnostics akhir 16 file / 16
metadata tanpa orphan, file sementara, atau metadata tanpa file.

Catatan jujur: durasi aktual 51,401 detik jauh lebih panjang dari ~6 detik yang
saya sarankan dalam instruksi; kriteria MAT-05/06 tidak menentukan durasi, jadi
bukti tetap diterima apa adanya. Selama eksplorasi, pengguna sempat menghapus dan
merekam ulang beberapa kali (`DELETE .../recording` → `200 OK`, `POST` → `201`)
serta menjalankan transkrip (`POST .../transcription` → `202 Accepted`), sehingga
status meeting akhir menjadi `TRANSCRIBED`. Itu di luar kriteria MAT-05/06 dan
tidak dihapus.

### 5.1v Skenario PASS — perilaku error provider (MAT-25)

MAT-25 awalnya `BLOCKED` karena live provider tidak boleh dijalankan tanpa
kredensial/persetujuan. Checklist mengizinkan **skenario gagal terkontrol**, jadi
pada 26 Nov saya memakai jalur itu: menambah env `MOCK_STT_FORCE_ERROR=1` hanya di
salinan backend test-terisolasi
(`<clean_dir>\backend\app\services\stt\mock.py`), yang melempar
`SttProviderError` dengan pesan tetap: *“Kegagalan mock terkontrol untuk MAT-25
(simulasi provider tidak tersedia).”* Tidak ada live provider, API key, secret,
atau URL internal yang dipakai.

Pada **Uji Error Dry Run MAT-25 20261126** (`38a0fd73-f993-4e4a-8f80-52dc19aac4eb`)
— pengguna ternyata mengklik meeting dry-run ini, bukan `d89e34f0…` yang saya
siapkan — UI menampilkan pesan yang dilaporkan pengguna persis:

```text
Transkripsi gagal: Kegagalan mock terkontrol untuk MAT-25 (simulasi provider tidak tersedia).
```

Verifikasi API saat error: `status=FAILED`, `error` sama persis, 0 segmen,
meeting `FAILED`. Dua `POST .../transcription` → `202 Accepted` (klik awal dan
retry) menghasilkan **1 baris job** dan 0 segmen, jadi retry tidak membuat
duplikat. Respons API diperiksa terhadap pola `api_key`/`authorization`/`sk-`/
`Bearer`/URL internal/token/`secret` → **AMAN**. Pesan UI tidak memuat detail
teknis selain kalimat ramah tersebut.

Setelah flag error dilepas dan backend distart ulang dengan fixture segmen
normal, pengguna mengklik **Transcribe** sekali sebagai retry. Verifikasi akhir:
`COMPLETED`, `error` kosong, 2 segmen (`5.0–10.0`, `10.0–15.642`, keduanya
berawalan `[MOCK]`), meeting `TRANSCRIBED`, `provider=mock`, `model=mock-1`,
1 job `COMPLETED`, 0 job `FAILED`, 0 job `PROCESSING`. Diagnostics 18 file / 18
metadata tanpa orphan, file sementara, atau metadata tanpa file.

Catatan: seluruh bukti memakai provider mock; tidak ada panggilan provider nyata
dan tidak ada kredensial yang diperlihatkan.

### 5.1w Lampiran — unggah rekaman milik pengguna (26 Nov)

Sebagai tindak lanjut pertanyaan pengguna mengenai "rekaman sendiri", saya
menguji berkas `<USERPROFILE>\Documents\<folder-rekaman>\<rekaman-pengguna>.m4a`
(1.561.477 byte, durasi 63,957 detik menurut atom `mvhd`). Berkas asli hanya
dibaca: SHA256 sebelum dan sesudah sama
(`1452F106F914E4853B74936F9B1A05375802EC7911D06535CBD7CE43A5291C82`).

Meeting baru `e6a13b74-189d-4fc0-8715-5f55f0c76bcb` (*Uji File Sendiri
20261126*) dibuat di DB/storage test-terisolasi. Unggah lewat API
menghasilkan `AudioAsset` `b660bd14-65ea-4fc3-8eea-9006ed0c660a`,
`mime_type=audio/mp4`, `duration_seconds=63.957`, `file_size_bytes=1561477`.
Endpoint `GET .../recording/play` → `206 Partial Content`, dan SHA256 salinan di
storage identik dengan berkas asli. Transkripsi `COMPLETED`, 2 segmen
`[MOCK]` dengan timestamp `5.0–10.0` dan `10.0–15.642`, `provider=mock`,
`model=mock-1`. Diagnostics 19 file / 19 metadata tanpa anomali.

Ini membuktikan jalur unggah/playback untuk file pengguna berfungsi, **bukan**
transkripsi suara asli. `MockSttProvider.transcribe()` di
`backend/app/services/stt/mock.py` tidak membaca isi audio; ia hanya mengubah
`MOCK_STT_SEGMENTS_JSON` (2 entri) menjadi segmen. Itulah sebabnya rekaman
browser 51,401 detik, WAV 15,642 detik, dan M4A 63,957 detik semuanya
menghasilkan dua segmen yang sama. Transkrip dari suara nyata memerlukan
provider live dengan kredensial yang tidak dipakai dalam acceptance ini.

### 5.2 Skenario BLOCKED

Tidak ada. MAT-25 diselesaikan lewat kegagalan mock terkontrol (lihat 5.1v).

### 5.3 Masih NOT TESTED

```text
(tidak ada — seluruh skenario MAT-01–MAT-26 telah dibuktikan pada 24–26 Nov)
```

Matriks pelaksanaan bertahap sudah ada di `docs/MANUAL_ACCEPTANCE_TEST.md` bagian
4. Instruksi tersebut harus dijalankan pengguna; OpenCode tidak boleh menandai
status menjadi `PASS` tanpa bukti.

## 6. Automated regression results

### 6.1 Backend

Perintah:

```powershell
cd backend
python -m pytest -q
```

Hasil:

```text
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 94%]
.............                                                            [100%]
============================== warnings summary ===============================
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\testclient.py:37
  <USERPROFILE>\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\testclient.py:37: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
229 passed, 1 warning in 165.29s (0:02:45)
```

| Metrik | Hasil |
| --- | --- |
| Passed | 229 |
| Failed | 0 |
| Skipped | 0 |
| Xfailed | 0 |
| Warning | 1 |

Sama dengan baseline Sprint 12 (229 passed). Warning lama tetap
`DeprecationWarning` Starlette/anyio.

### 6.2 Frontend

Perintah:

```powershell
cd frontend
npm test
```

Hasil:

```text
> meetnote-ai-frontend@0.1.0 test
> node --test tests/*.test.ts

✔ mengambil nama file dari header Content-Disposition backend (2.966ms)
✔ mendukung header tanpa tanda kutip dan huruf besar (0.3047ms)
✔ menolak header dengan path traversal lalu memakai fallback (0.2516ms)
✔ menolak quote, newline, dan nama file terlalu panjang (0.2342ms)
✔ fallback memakai 8 karakter ID pertama dan ekstensi sesuai format (2.7096ms)
✔ header kosong memakai fallback (0.2156ms)
✔ saveBlob membuat anchor, mengkliknya, lalu membersihkan object URL (19.1314ms)
ℹ tests 7
ℹ suites 0
ℹ pass 7
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 330.1175
```

Sama dengan baseline Sprint 12: 7 pass, 0 fail.

### 6.3 Production build

Perintah:

```powershell
cd frontend
npm run build
```

Hasil:

```text
> meetnote-ai-frontend@0.1.0 build
> tsc -b && vite build

vite v6.4.6 building for production...
transforming...
✓ 42 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                  0.41 kB │ gzip:  0.28 kB
dist/assets/index-CUETBaZr.css   12.98 kB │ gzip:  2.97 kB
dist/assets/index-vOnPmIIv.js   283.29 kB │ gzip: 84.00 kB
✓ built in 2.99s
```

Sama dengan baseline Sprint 12: 42 modules transformed, build sukses.

## 7. Security findings

- Persetujuan Git write ditolak dan dihormati; tidak ada `git init`, `add`,
  `commit`, `push`, atau remote change.
- Tidak ada isi `.env` yang dibaca/ditampilkan; hanya nama variabel dari file
  contoh yang dicatat.
- Tidak ada API key yang diminta, dibaca, dipakai, atau dikirim ke provider.
- Acceptance otomatis memakai provider `mock`, DB `api_test.db`, dan storage
  `backend/test_storage`.
- Tidak ada penghapusan DB, audio, backup, `node_modules`, atau `dist`.
- Tidak ada migrasi destruktif, perubahan fitur inti, atau upgrade dependency.
- `.gitignore` terbukti mencakup secrets, DB, audio, backup, cache, dan artefak
  build.
- Log sementara proses acceptance ditulis di
  `<USERPROFILE>\AppData\Local\Temp\opencode`, bukan di folder proyek, dan proses
  sudah dihentikan.

Temuan positif tambahan: diagnostics pada storage test menunjukkan 0 orphan, 0
temp file, 0 trash file, 0 metadata tanpa file, dan 0 invalid path.

## 8. Remaining risks

| ID | Risiko | Status |
| --- | --- | --- |
| GIT-01 | Repository belum diinisialisasi | `BLOCKED` oleh keputusan pengguna |
| MAN-01 | 19 skenario acceptance masih `NOT TESTED` | Ditutup 26 Nov — seluruh 26 skenario telah dibuktikan |
| MAT-25 | Live provider error test tidak dijalankan | Ditutup 26 Nov lewat kegagalan mock terkontrol; live provider tetap tidak dipakai |
| AUTH-01 | Tidak ada autentikasi/otorisasi | `DEFERRED` |
| CONC-01 | Job lock hanya satu proses | `DEFERRED` |
| PROV-01 | Provider cloud belum live-tested | `ACCEPTED RISK` |
| DEPS-01 | Backend belum punya constraints file | `DEFERRED` |
| OBS-01 | Tanpa automation browser | `ACCEPTED RISK` |
| BASE-01 | Warning anyio/Starlette | `ACCEPTED RISK` |

Tidak ada `BLOCKER` teknis baru untuk rilis lokal/internal. Manual acceptance
telah selesai 24–26 Nov dengan PASS 26 / FAIL 0 / BLOCKED 0 / NOT TESTED 0. Yang
masih menahan langkah berikutnya hanyalah keputusan Git yang belum diberikan dan
risiko yang sengaja `DEFERRED`/`ACCEPTED RISK` di tabel atas.

## 9. Release classification

- **Local development ready:** Ya.
- **Local/internal release ready:** Ya, secara teknis dan bersyarat untuk
  single-user/demo internal. Penerimaan manual sudah lengkap (PASS 26); bukti ada
  di `docs/MANUAL_ACCEPTANCE_TEST.md` bagian 5 dan lampiran 5.1w di bawah.
- **Public release ready:** Tidak. Auth dan konkurensi antar-proses masih
  `DEFERRED`; live provider smoke test sengaja tidak dijalankan tanpa kredensial.

Automated tests lulus seluruhnya dan dipakai sebagai bukti MAT-02/MAT-03/MAT-26,
bukan pengganti bukti interaksi pengguna untuk skenario manual.

## 10. Recommended next sprint

1. Tunggu persetujuan eksplisit terpisah bila Git initialization/commit/push
   masih diinginkan; jangan menganggap persetujuan sprint sebagai persetujuan Git
   write. Repository hingga dokumen ini ditutup tetap tanpa `.git`.
2. Pertahankan `docs/MANUAL_ACCEPTANCE_TEST.md` sebagai sumber status terkini;
   MAT-04–MAT-25 sudah dibuktikan, MAT-01/MAT-02/MAT-03/MAT-26 otomatis/terisolasi.
3. Bila kelak live provider diizinkan, jalankan smoke test terpisah dengan
   kredensial yang dimasukkan pengguna sendiri; jangan meminta API key di chat dan
   jangan mengubah label `[MOCK]` pada bukti yang sudah ada.
4. Pertimbangkan constraints file backend dan automation browser sebagai
   hardening terpisah.
5. Sebelum commit, pastikan artefak terabaikan (`*.db`, `test_storage/`, WAV
   fixture, `__pycache__`, `node_modules/`, `dist/`, `*.tsbuildinfo`) tidak ikut
   ter-stage; `.gitignore` sudah mencakupnya.
6. Perbarui laporan rilis hanya berdasarkan bukti yang benar-benar diperoleh.

## Penutup

Seluruh pekerjaan aman Sprint 13 selesai: audit, klasifikasi file, rencana Git,
acceptance otomatis terbatas, regression test, dan dokumentasi. Repository tetap
belum diinisialisasi, tidak ada commit/push, dan tidak ada data pengguna yang
dihapus. Saat Sprint 13 berakhir, manual acceptance sebagian besar masih
menunggu; lanjutan Phase A/B 24–26 Nov menyelesaikan ke-26 skenario seperti
dirangkum di `docs/MANUAL_ACCEPTANCE_TEST.md` bagian 5 dan lampiran 5.1w.
