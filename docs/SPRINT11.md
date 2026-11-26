# Sprint 11 — Validasi Integrasi & Kesiapan Rilis

## 1. Tujuan dan ruang lingkup

Sprint 11 adalah sprint validasi, bukan penambahan fitur AI. Tujuannya:

1. memverifikasi integrasi nyata Sprint 1–10 dari filesystem aktual, bukan dari
   laporan sebelumnya;
2. menjalankan regresi alur penuh memakai provider mock / HTTP client palsu;
3. melakukan audit reliability, security, UX, dan Git secara read-only;
4. memperbaiki hanya temuan yang relevan untuk kesiapan rilis;
5. mendokumentasikan kesiapan deployment beserta batasannya.

Tidak ada perubahan arsitektur, tidak ada auth baru, tidak ada queue/Redis/Celery,
tidak ada PostgreSQL, tidak ada microservice, tidak ada dependency baru, dan tidak
ada pernyataan bahwa provider cloud sudah diuji live. Path export tidak diubah:

- `GET /api/v1/meetings/{meeting_id}/export/txt`
- `GET /api/v1/meetings/{meeting_id}/export/pdf`

## 2. Baseline dan source of truth

Semua angka baseline dijalankan ulang sebelum perubahan:

| Gate | Perintah | Hasil baseline |
| --- | --- | --- |
| Backend | `python -m pytest -q` | `222 passed, 1 warning in 125.69s` |
| Frontend test | `npm test` | `7 pass, 0 fail` |
| Frontend build | `npm run build` | sukses, `42 modules transformed`, `built in 2.06s` |

Warning yang muncul adalah `DeprecationWarning` Starlette/anyio
(`anyio.abc.BlockingPortal`) yang sudah ada sejak sprint sebelumnya. Tidak ada
test yang dihapus atau dilemahkan.

## 3. Metodologi audit

- Membaca `README.md`, `docs/ARCHITECTURE.md`, dan `docs/SPRINT1.md`–
  `docs/SPRINT10.md` secara lengkap.
- Memeriksa endpoint, workflow, provider, model, skema, service, dan komponen
  frontend yang benar-benar ada di filesystem.
- Menjalankan test baseline sebelum menyusun test baru.
- Membedakan defect nyata dari keterbatasan yang sudah disengaja/didokumentasikan.
- Mengklasifikasikan temuan menjadi `BLOCKER`, `HIGH`, `MEDIUM`, `LOW`.
- Menandai setiap temuan dengan `FIXED`, `ACCEPTED RISK`, `DEFERRED`, atau
  `BLOCKER` pada bagian 12.
- Tidak menjalankan `git init`, commit, push, pull, remote change, atau penghapusan
  data.

## 4. Inventarisasi struktur dan dokumen

| Item | Kondisi aktual |
| --- | --- |
| `backend/`, `frontend/`, `docs/`, `storage/` | ada |
| `docs/SPRINT1.md`–`docs/SPRINT10.md` | lengkap dan tidak kosong |
| `docs/SPRINT11.md` | awalnya belum ada; dibuat sprint ini |
| `backend/tests/test_sprint10.py` | test terakhir sebelum sprint ini |
| `frontend/tests/export.test.ts` | satu-satunya file test frontend |
| `backend/meetnote.db`, `api_test.db`, `test.db` | ada; tidak dihapus/ditimpa |
| `storage/` | hanya `.gitkeep`; tidak dihapus |
| `frontend/node_modules/`, `frontend/dist/` | ada; tidak dihapus |

Tidak ada file audio produksi yang disentuh. Semua test memakai
`backend/api_test.db` dan `backend/test_storage` yang diatur oleh
`backend/tests/conftest.py`.

## 5. Audit endpoint dan workflow

Endpoint yang diverifikasi mencakup health/config, meetings, recordings,
transcriptions, diarizations, transcript edits, summaries, action items, dan
export. Temuan positif utama:

- semua ID melewati tipe `uuid.UUID`, termasuk parameter export dan edit;
- ownership data diverifikasi lewat `meeting_id` + id objek di service editing;
- job aktif dicegah dengan `job_guard` dan run token di keempat workflow;
- stale task tidak dapat menimpa status job yang lebih baru;
- hasil AI divalidasi lebih dulu (segmen, waktu, speaker) sebelum ditulis;
- ringkasan lama tidak berubah sampai hasil baru valid;
- item action hasil edit pengguna dipertahankan saat regenerasi;
- transkripsi ulang membersihkan turunan yang tidak relevan;
- export hanya membaca data tersimpan, tidak memanggil AI, tidak menulis DB,
  tidak mengakses audio, dan tidak membuat file sementara.

Tidak ditemukan endpoint duplikat atau perubahan kontrak yang tidak sengaja.

## 6. Audit provider dan model

Provider yang tersedia: mock dan real (OpenAI untuk STT/LLM, Deepgram untuk
diarisasi). Semua test memakai mock atau HTTP client palsu. Tidak ada API key
bernama (`OPENAI_API_KEY`, `STT_API_KEY`, `DIARIZATION_API_KEY`, `LLM_API_KEY`,
dan sejenisnya) yang dibaca atau dicetak nilainya. Satu variabel lingkungan
tidak terkait ditemukan, tetapi tidak dipakai aplikasi.

Konfigurasi dipisahkan lewat `SecretStr`, dan `GET /api/v1/config` hanya
mengembalikan nama provider serta status `configured`. Tidak ada klaim live
provider cloud. Validasi nyata dengan kredensial pengguna masih menjadi
pengujian manual yang harus dilakukan terpisah.

## 7. Audit frontend dan UX

Area yang ditinjau: dashboard, daftar meeting, halaman baru, detail recording,
upload/playback, editor transkrip, speaker manager, ringkasan, action items, dan
export.

Hal yang sudah baik:

- tidak ada `dangerouslySetInnerHTML`;
- tidak ada API key di frontend; base URL hanya dari `VITE_API_BASE_URL`;
- error API dibaca dari `detail` dengan fallback yang aman;
- `downloadExport()` memiliki penjaga klik ganda;
- `saveBlob()` mencabut object URL; hook audio juga mencabut URL;
- label, `aria-label`, `role="alert"`, dan `role="status"` tersedia di komponen
  utama;
- React/TypeScript strict build lolos.

Temuan yang diperbaiki:

- polling job berhenti setelah ~120 detik tanpa pesan, padahal timeout diarisasi
  backend 180 detik. Sekarang batas polling ~210 detik dan setiap job menampilkan
  pesan "Tekan Refresh" bila batas tercapai;
- indikator kesehatan bisa hijau walaupun `/health` gagal. Sekarang status health
  mengikuti hasil `fetchHealth()`;
- footer masih menyebut Sprint 4. Sekarang menyebut Sprint 11.

Validasi visual desktop/tablet/mobile tetap memerlukan pengecekan manual karena
tidak ada automation browser; tidak ada framework UI/test baru yang ditambahkan.

## 8. Pengujian regresi end-to-end

File baru `backend/tests/test_sprint11.py` berisi tujuh test yang mencakup:

1. alur penuh 16 langkah: meeting → audio → playback → transkripsi → diarisasi →
   edit teks → nama speaker → assignment speaker → ringkasan → action items →
   edit/status → ekspor TXT/PDF → konsistensi;
2. regenerasi ringkasan dan action items dengan item manual tetap utuh;
3. kegagalan provider menghasilkan snapshot ekspor yang aman, lalu retry sukses;
4. transkripsi ulang membersihkan turunan dan ekspor tidak menggantung;
5. klik ulang, hapus saat job aktif, recovery restart, dan retry;
6. konsistensi DB/storage pasca-alur penuh;
7. default konfigurasi rilis (`DEBUG=false`, CORS tidak wildcard).

Semua provider disuntik lewat seam `_create_provider`, database dan storage
terisolasi, serta tidak ada jaringan/kredensial/audio produksi.

## 9. Reliability dan recovery

Skenario yang diverifikasi:

- restart saat job: task `PROCESSING` dipulihkan menjadi `FAILED` secara idempoten,
  lalu retry dapat berhasil;
- timeout/429/500/invalid response: dipetakan ke error job yang aman, bukan
  `COMPLETED` palsu;
- klik berulang: `409` saat job aktif;
- hapus rekaman saat job aktif: `409`, file masih ada;
- edit saat job aktif: ditolak sampai job selesai;
- ekspor parsial/gagal: `500` generik, tidak ada detail internal, tidak ada file
  sementara;
- DB/storage tidak tersedia: error ditangani atau dilaporkan diagnostics secara
  read-only, bukan penghapusan otomatis;
- stale run token tidak dapat menulis job yang sudah digantikan.

Tidak ada retry otomatis/backoff provider; retry saat ini adalah aksi pengguna.
Ini sengaja dicatat sebagai `DEFERRED`, bukan defect rilis lokal.

## 10. Security audit

Audit read-only menunjukkan:

- tidak ada secret hardcoded; `SecretStr` dipakai untuk semua kunci;
- path traversal ditolak oleh `resolve()` + `is_relative_to(root)`;
- upload memakai MIME allowlist, ekstensi, ukuran, signature bila dikenali, UUID
  filename, penulisan `.part` lalu `os.replace`;
- delete memakai `.delete`, guard job aktif, dan rollback;
- semua query SQLAlchemy memakai ORM/filter parametrik;
- error ke klien bersifat generik; log hanya kategori error, bukan pesan/secret;
- CORS dibatasi origin yang dikonfigurasi;
- `/health/diagnostics` hanya mengembalikan flag FK dan anomali relatif.

 Temuan yang masih terbuka untuk deployment publik adalah tidak adanya
 autentikasi/otorisasi dan keterbatasan konkurensi satu proses. Keduanya sudah
 tercatat sebagai batasan arsitektur dan ditandai `DEFERRED` untuk sprint ini.

## 11. Audit Git dan filesystem

- Direktori kerja: `<USERPROFILE>\Projects\meetnote-ai`.
- Tidak ada `.git` di root, parent, atau subdirektori.
- `git rev-parse --show-toplevel` menghasilkan
  `fatal: not a git repository (or any of the parent directories): .git`, exit `128`.
- Hanya `.gitignore` dan `storage/.gitkeep` yang menyebut Git.
- Tidak ada `.gitattributes`, `.gitmodules`, `HEAD`, `config`, `index`,
  `COMMIT_EDITMSG`, `Zone.Identifier`, atau artefak salin/pindah.
- `git version 2.56.1.windows.1` terpasang, tetapi tidak dipakai untuk operasi
  repository.
- Konfigurasi global hanya memuat `credential.helper` style setting.

Tidak ada commit, push, remote change, `git init`, atau penghapusan metadata.
Seluruh perubahan sprint ini tetap berada di working directory.

## 12. Daftar temuan dan status

| ID | Temuan | Kat. | Status | Catatan |
| --- | --- | --- | --- | --- |
| REL-01 | Polling frontend berhenti diam-diam sebelum timeout provider | MEDIUM | **FIXED** | Batas ~210 dtk + pesan Refresh |
| SEC-01 | `DEBUG=true` sebagai default | MEDIUM | **FIXED** | Default diubah ke `false` |
| SEC-02 | CORS origin hardcode | MEDIUM | **FIXED** | `CORS_ALLOWED_ORIGINS` + method/header dibatasi |
| UX-01 | Indikator health salah hijau saat `/health` gagal | LOW | **FIXED** | Status mengikuti hasil health |
| DOC-01 | Footer menyebut Sprint 4 | LOW | **FIXED** | Label diperbarui ke Sprint 11 |
| DOC-02 | README/arsitektur belum Sprint 11 | LOW | **FIXED** | Dokumen sprint ini ditambahkan/diperbarui |
| SEC-03 | Signature audio asing diterima | LOW | **ACCEPTED RISK** | Disengaja untuk kompatibilitas MediaRecorder |
| OPS-01 | Diagnostics terbuka | LOW | **ACCEPTED RISK** | Datanya non-sensitif; batasi di gateway bila dipublikasikan |
| TEST-01 | Tidak ada component/DOM test | MEDIUM | **ACCEPTED RISK** | Manual UX checklist; tanpa framework baru |
| PROV-01 | Provider cloud belum live-tested | MEDIUM | **ACCEPTED RISK** | Tidak ada kredensial; wajib smoke test manual |
| BASE-01 | Deprecation warning anyio | LOW | **ACCEPTED RISK** | Warning lama, bukan kegagalan |
| AUTH-01 | Tidak ada autentikasi/otorisasi | HIGH | **DEFERRED** | Prasyarat deployment publik; di luar cakupan sprint |
| CONC-01 | Job lock hanya dalam satu proses | HIGH | **DEFERRED** | Butuh queue/distributed lock untuk multi-worker |
| RETRY-01 | Tanpa backoff otomatis 429/5xx | MEDIUM | **DEFERRED** | Manual retry tersedia dan teruji |
| OBS-01 | Startup recovery hanya kategori error | LOW | **DEFERRED** | Sengaja aman dari kebocoran pesan/secret |
| BUILD-01 | Frontend tanpa lockfile/pin eksak | LOW | **DEFERRED** | Build terverifikasi pada environment saat ini |
| EXPORT-01 | Export hanya snapshot utuh | LOW | **DEFERRED** | Sesuai keputusan Sprint 10 |
| — | **BLOCKER terbuka** | — | **Tidak ada** | Rilis lokal dapat dilanjutkan; deployment publik tidak |

## 13. Perbaikan yang diterapkan

1. `backend/app/core/config.py`: `DEBUG` default `False`, menambah
   `CORS_ALLOWED_ORIGINS`.
2. `backend/app/main.py`: CORS memakai origin dari konfigurasi; method dan header
   dibatasi.
3. `.env.example` dan `backend/.env.example`: `DEBUG=false`, contoh
   `CORS_ALLOWED_ORIGINS`, komentar development.
4. `frontend/src/components/MeetingDetail.tsx`: konstanta polling, batas 140
   percobaan, notifikasi Refresh untuk 4 job.
5. `frontend/src/App.tsx`: health indicator mengikuti `fetchHealth()`; footer
   Sprint 11.
6. `backend/tests/test_sprint11.py`: 7 test integrasi/reliability/hardening baru.

Tidak ada dependency, endpoint, model database, atau arsitektur yang diubah.

## 14. Hasil quality gate

Perintah dan hasil akhir setelah perbaikan:

```text
backend  > python -m pytest -q
          229 passed, 1 warning in 126.42s (0:02:06)

frontend > npm test
          tests 7 / pass 7 / fail 0 / duration_ms 228.78

frontend > npm run build
          ✓ 42 modules transformed
          ✓ built in 1.97s
```

Warning backend masih sama: `DeprecationWarning` `anyio.abc.BlockingPortal`
dari Starlette TestClient. Tidak ada `skip`, `xfail`, `todo`, atau penghapusan
test.

## 15. Kesiapan rilis dan pengujian manual

**Siap untuk:** demonstrasi lokal, pengembangan, dan rilis internal single-user
dengan provider mock atau kredensial pengguna yang dikonfigurasi sendiri.

**Belum siap untuk:** deployment publik/multi-user tanpa auth, multi-worker tanpa
antrean, atau klaim provider cloud tanpa smoke test dengan kredensial sah.

Pengecekan manual yang masih diperlukan:

- tampilan desktop/tablet/mobile untuk semua halaman dan state;
- izin mikrofon, start/stop/pause recording, upload dan hapus/re-upload;
- playback dan seek pada segmen;
- edit transkrip, nama speaker, assignment speaker;
- generate/regenerate ringkasan dan action items, edit/status;
- unduh TXT/PDF lalu cocokkan isi dengan UI;
- timeout/429/500 provider nyata dengan kredensial pengguna;
- restart server saat job berjalan, lalu verifikasi `FAILED` + retry;
- akses `/api/v1/health/diagnostics` di lingkungan terpencil.

## 16. Kesimpulan

Sprint 11 menyelesaikan validasi integrasi Sprint 1–10, menambah 7 test backend
baru, memperbaiki temuan rilis yang relevan, dan mendokumentasikan batasan
deployment. Tidak ada `BLOCKER` terbuka dalam cakupan lokal yang ditetapkan.
Status akhir: **Sprint 11 selesai untuk rilis lokal/internal**. Seluruh perubahan
masih uncommitted dan tidak ada operasi Git yang dijalankan.
