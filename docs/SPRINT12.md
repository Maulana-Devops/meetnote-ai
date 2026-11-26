# Sprint 12 — Repository Setup, Release Packaging & Manual Acceptance Testing

> **Catatan status (26 Nov 2026):** dokumen ini adalah snapshot Sprint 12. Status
> manual acceptance di dalamnya (`NOT TESTED`, MAT-25 `BLOCKED`) sudah digantikan
> oleh lanjutan Phase A/B 24–26 Nov: **PASS 26 / FAIL 0 / BLOCKED 0 /
> NOT TESTED 0**. Sumber terkini adalah `docs/MANUAL_ACCEPTANCE_TEST.md` bagian 5.

## 1. Ringkasan pekerjaan

Sprint 12 adalah sprint stabilisasi repository dan packaging, bukan penambahan
fitur AI. Pekerjaan yang diselesaikan:

- audit struktur backend, frontend, config, dokumentasi, dependency, env, DB,
  storage, dan artefak build dari filesystem aktual;
- audit Git secara read-only;
- audit dependency backend dan frontend, termasuk sinkronisasi lockfile;
- pembuatan `docs/INSTALLATION.md`, `docs/BACKUP_RESTORE.md`, dan
  `docs/MANUAL_ACCEPTANCE_TEST.md`;
- penyesuaian `.gitignore` untuk folder backup dan artefak SQLite sementara;
- pembaruan indeks dokumentasi, README, dan arsitektur;
- eksekusi ulang seluruh automated regression test dan production build;
- penyusunan laporan kesiapan rilis.

Tidak ada dependency yang di-upgrade, tidak ada test yang dilemahkan, tidak ada
database/audio/storage/node_modules/dist yang dihapus, dan tidak ada operasi Git
write (`init`, `add`, `commit`, `push`, remote change). Tidak ada backup/restore
data pengguna yang benar-benar dijalankan.

## 2. Temuan audit repository

### 2.1 Struktur aktual

| Area | Temuan |
| --- | --- |
| Root | `backend/`, `frontend/`, `docs/`, `storage/`, `.env.example`, `.gitignore`, `README.md` |
| Backend | `app/`, `tests/`, `main.py`, `requirements.txt`, `.env.example`, DB lokal |
| Frontend | `src/`, `tests/`, `dist/`, `node_modules/`, `package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`, `.env.example` |
| Dokumentasi | `SPRINT1.md`–`SPRINT11.md`, `ARCHITECTURE.md`, `README.md`; Sprint 12 ditambahkan |
| Audio produksi | Tidak ada file di `storage/` selain `.gitkeep` pada saat audit |
| Audio test | Ditemukan file di `backend/test_storage/meetings/`; tidak disentuh |
| Build | `frontend/dist/` berisi 3 file; tidak dihapus |
| Cache/sementara | Tidak ada `*.log`, `*.tmp`, `*.bak`, `*.orig`; ada `frontend/tsconfig.tsbuildinfo` yang sudah diabaikan `.gitignore` |

### 2.2 Database dan storage

Database yang ditemukan dan **tidak diubah**:

| File | Ukuran saat audit |
| --- | --- |
| `backend/meetnote.db` | 12.288 byte |
| `backend/api_test.db` | 188.416 byte |
| `backend/test.db` | 167.936 byte |

Lokasi audio produksi mengikuti `storage/meetings/<meeting_id>/` dengan metadata
`audio_assets.storage_path` berupa path relatif. Hubungan ini menjadi dasar
prosedur di `docs/BACKUP_RESTORE.md`.

### 2.3 File konfigurasi

- Hanya ada `.env.example` di root, `backend/`, dan `frontend/`; tidak ada file
  `.env` aktif yang ditemukan.
- `.gitignore` sudah mengecualikan `.env`, `.env.*`, `*.db`, `storage/*`,
  `test_storage/`, `node_modules/`, `dist/`, dan `*.tsbuildinfo`.
- Sprint 12 menambah pengecualian `backups/`, `*.db-journal`, `*.db-wal`,
  `*.db-shm`, `*.part`, dan `*.delete`.

## 3. Status Git

Audit Git read-only dilakukan dengan hasil:

```text
Test-Path .git (root, <USERPROFILE>\Projects, <USERPROFILE>, C:\Users)
  => False untuk keempatnya

git rev-parse --show-toplevel
  fatal: not a git repository (or any of the parent directories): .git
  exit code 1

git remote -v
  fatal: not a git repository (or any of the parent directories): .git
  exit code 1

Get-ChildItem -Force -Directory -Filter '.git' -Recurse -Depth 5
  => tidak ada output
```

Kesimpulan: proyek **belum** memiliki repository Git dan tidak memiliki remote
yang relevan. Tidak ada metadata Git yang dibuat, dipindah, atau dihapus.

Rekomendasi (belum dijalankan, menunggu persetujuan pengguna):

```powershell
# RENCANA — JANGAN dijalankan tanpa persetujuan
git init
git config user.name "<nama>"
git config user.email "<email>"
git status --short
git add .gitignore README.md docs backend/app backend/main.py backend/requirements.txt backend/.env.example frontend/src frontend/tests frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/.env.example storage/.gitkeep
git status --short
git commit -m "Initial import: MeetNote AI Sprint 12"
git remote add origin <url-repository>
git push -u origin main
```

Sebelum `git add`, periksa ulang `git status --short` untuk memastikan tidak ada
`.env`, `*.db`, audio, `backups/`, `node_modules/`, atau `dist/` yang ikut.

## 4. Dependency management

### 4.1 Backend

`backend/requirements.txt` memakai pin eksak untuk seluruh dependency langsung:

| Paket | Versi |
| --- | --- |
| `fastapi` | `0.115.12` |
| `uvicorn[standard]` | `0.34.2` |
| `python-multipart` | `0.0.20` |
| `sqlalchemy` | `2.0.42` |
| `pydantic` | `2.11.4` |
| `pydantic-settings` | `2.9.1` |
| `httpx` | `0.28.1` |
| `reportlab` | `4.4.10` |
| `pytest` | `8.3.5` |
| `pypdf` | `7.1.1` (test-only) |

Temuan:

- tidak ada versi mengambang pada dependency langsung;
- `uvicorn[standard]` dan beberapa paket lain masih memiliki dependency
  transitif yang tidak terkunci lewat constraints file;
- lockfile/constraints backend belum ada. Ini bukan kegagalan rilis lokal karena
  semua dependency langsung sudah pin, tetapi dapat menyebabkan instalasi beda
  environment di masa depan.

Tidak ada upgrade mayor/minor yang dilakukan.

### 4.2 Frontend

`frontend/package.json` memakai rentang caret, tetapi `package-lock.json`
tersedia:

- `package-lock.json`: ada, 61.783 byte;
- `lockfileVersion`: `3`;
- root lockfile identik dengan `package.json` (nama, versi, dependencies,
  devDependencies);
- `npm ls --depth=0` menunjukkan versi terpasang sama dengan lockfile.

Versi terpasang/terkunci:

| Paket | Versi |
| --- | --- |
| `react` | `19.3.1` |
| `react-dom` | `19.3.1` |
| `@types/react` | `19.3.0` |
| `@types/react-dom` | `19.3.0` |
| `@vitejs/plugin-react` | `4.7.0` |
| `typescript` | `5.9.3` |
| `vite` | `6.4.6` |

Kesimpulan: gunakan `npm ci` untuk instalasi reproducible. `npm update` tidak
dijalankan dan tidak disarankan tanpa alasan teknis + test ulang.

### 4.3 Secret hygiene

Pencarian pola secret (`sk-...`, `AIza...`, dan `*_API_KEY=<nilai>`) tidak
menemukan kredensial. Ketiga `.env.example` hanya berisi placeholder, dengan
`STT_API_KEY=`, `DIARIZATION_API_KEY=`, dan `LLM_API_KEY=` kosong. API key tidak
pernah diminta atau dibaca nilainya.

## 5. File dokumentasi baru atau diperbarui

| File | Status | Isi |
| --- | --- | --- |
| `docs/INSTALLATION.md` | Baru | Prasyarat Python 3.12/Node 24, venv, `pip install`, `npm ci`, konfigurasi `.env`, cara start backend/frontend, health endpoint, lokasi data, troubleshooting PowerShell |
| `docs/BACKUP_RESTORE.md` | Baru | Hubungan DB↔audio, backup dengan backend dihentikan, SQLite Online Backup API, restore dengan konfirmasi, verifikasi diagnostics, larangan `/MIR` dan penghapusan otomatis |
| `docs/MANUAL_ACCEPTANCE_TEST.md` | Baru | 26 skenario MAT-01–MAT-26 dengan tujuan, prasyarat, langkah, expected, status `NOT TESTED`, dan catatan; pemisahan otomatis vs manual |
| `docs/SPRINT12.md` | Baru | Laporan 12 bagian ini |
| `docs/README.md` | Diperbarui | Indeks Sprint 12 + 3 dokumen baru |
| `README.md` | Diperbarui | Status Sprint 12, versi Node, batasan Sprint 12, tautan dokumentasi |
| `docs/ARCHITECTURE.md` | Diperbarui | Catatan Sprint 12: tanpa komponen arsitektur baru, packaging, backup DB/storage, checklist manual |
| `.gitignore` | Diperbarui | `backups/`, SQLite sidecar, `.part`, `.delete` |

## 6. Perubahan konfigurasi

Satu-satunya perubahan konfigurasi repository adalah `.gitignore`. Tidak ada
perubahan pada:

- kode backend/frontend stabil;
- `requirements.txt`, `package.json`, `package-lock.json`;
- `.env.example` (tetap placeholder);
- schema database atau migrasi;
- endpoint API;
- Windows Execution Policy.

Alasan perubahan `.gitignore`: prosedur backup/restore Sprint 12 memperkenalkan
folder `backups/`, dan SQLite dapat meninggalkan file journal/WAL/SHM. Keduanya
harus tercegah masuk ke repository atau paket rilis.

## 7. Hasil backend tests

Perintah:

```powershell
cd backend
python -m pytest -q
```

Hasil aktual Sprint 12:

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
229 passed, 1 warning in 129.98s (0:02:09)
```

Ringkasan:

| Metrik | Hasil |
| --- | --- |
| Passed | 229 |
| Failed | 0 |
| Skipped | 0 |
| Xfailed | 0 |
| Warning | 1 |

Warning adalah `DeprecationWarning` Starlette/anyio yang sudah ada sejak sprint
sebelumnya. Seluruh test Sprint 1–11 masih berjalan. Tidak ada test yang dihapus,
diubah agar lulus, atau diberi marker skip/xfail baru.

## 8. Hasil frontend tests

Perintah:

```powershell
cd frontend
npm test
```

Hasil aktual:

```text
> meetnote-ai-frontend@0.1.0 test
> node --test tests/*.test.ts

✔ mengambil nama file dari header Content-Disposition backend (1.9288ms)
✔ mendukung header tanpa tanda kutip dan huruf besar (0.3525ms)
✔ menolak header dengan path traversal lalu memakai fallback (0.3052ms)
✔ menolak quote, newline, dan nama file terlalu panjang (0.295ms)
✔ fallback memakai 8 karakter ID pertama dan ekstensi sesuai format (1.5028ms)
✔ header kosong memakai fallback (0.5941ms)
✔ saveBlob membuat anchor, mengkliknya, lalu membersihkan object URL (11.776ms)
ℹ tests 7
ℹ suites 0
ℹ pass 7
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 227.7322
```

Ringkasan: 7 passed, 0 failed, 0 skipped, 0 todo. Tidak ada framework test baru
yang ditambahkan; suite tetap memakai `node:test` bawaan Node.js 24.

## 9. Hasil production build

Perintah:

```powershell
cd frontend
npm run build
```

Hasil aktual:

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
✓ built in 1.91s
```

`tsc -b` berjalan sebagai bagian dari script build, sehingga TypeScript check
ikut terverifikasi tanpa perintah terpisah. Artefak `frontend/dist/` sudah ada
sebelum sprint dan tidak dihapus; build hanya memperbarui isinya.

## 10. Manual acceptance test yang belum dijalankan

`docs/MANUAL_ACCEPTANCE_TEST.md` berisi 26 skenario:

- MAT-01–MAT-03: instalasi bersih, health, frontend accessible;
- MAT-04–MAT-09: meeting, rekaman browser, pause/resume/stop, upload, playback,
  hapus audio;
- MAT-10–MAT-22: transkripsi, diarisasi, edit transkrip/speaker, ringkasan,
  topik/keputusan, action items, export TXT/PDF;
- MAT-23–MAT-25: refresh saat job, restart backend saat job, error provider;
- MAT-26: konsistensi DB/storage.

Status awal seluruh skenario: `NOT TESTED`. Tidak ada satu pun yang diklaim
lulus. Yang benar-benar dijalankan Sprint 12 hanyalah automated regression test
dan build pada bagian 7–9.

Pemisahan:

- **Dapat otomatis:** MAT-02, MAT-03, MAT-26, dan sebagian MAT-10–MAT-22 sudah
  tercakup oleh test backend dengan mock.
- **Wajib manual:** MAT-01, MAT-04–MAT-09, MAT-23–MAT-25, serta verifikasi visual
  dan interaksi browser untuk MAT-10–MAT-22.

## 11. Risiko yang masih tersisa

| ID | Risiko | Dampak | Status |
| --- | --- | --- | --- |
| AUTH-01 | Tidak ada autentikasi/otorisasi | Endpoint terbuka; tidak aman untuk multi-user/publik | `DEFERRED` — prasyarat public release |
| CONC-01 | Job lock hanya dalam satu proses | Tidak aman untuk multi-worker/container | `DEFERRED` — prasyarat public release |
| PROV-01 | Provider cloud belum live-tested | Perilaku nyata 429/timeout/response belum terverifikasi | `ACCEPTED RISK` — butuh smoke test dengan kredensial pengguna |
| MAN-01 | Manual acceptance belum dijalankan | UX browser, mikrofon, recording, dan visual belum dibuktikan | `NOT TESTED` |
| DEPS-01 | Backend belum punya constraints/lockfile | Dependency transitif dapat berubah antar-environment | `DEFERRED` |
| OBS-01 | Tidak ada automation browser | Regresi UI tidak terdeteksi otomatis | `ACCEPTED RISK` |
| BASE-01 | Warning anyio/Starlette | Noise pada log test | `ACCEPTED RISK` — bukan kegagalan |
| GIT-01 | Repository belum diinisialisasi | Tidak ada version control/remote | `DEFERRED` — butuh persetujuan |

Klasifikasi akhir:

- **Local development ready:** Ya.
- **Local/internal release ready:** Ya, untuk single-user dengan batasan
  terdokumentasi.
- **Public release ready:** Tidak. Automated tests lulus tidak cukup untuk
  menyatakan public release siap karena auth, konkurensi antar-proses, manual
  acceptance, dan live provider smoke test belum selesai.

Tidak ada `BLOCKER` untuk rilis lokal/internal. Item AUTH-01 dan CONC-01
menjadi penghalang public release.

## 12. Rekomendasi sprint berikutnya

1. **Git initialization (setelah persetujuan):** jalankan rencana pada bagian 3,
   verifikasi `git status`, lalu buat commit awal tanpa `.env`, DB, audio,
   `backups/`, `node_modules/`, atau `dist/`.
2. **Manual acceptance execution:** jalankan 26 skenario MAT dan isi kolom
   status/catatan; prioritas MAT-01, MAT-05–MAT-09, MAT-23–MAT-25.
3. **Authentication & basic authorization:** tambahkan lapisan auth sebelum
   publikasi; minimal API token/user login dengan isolasi data per user.
4. **Multi-worker strategy:** evaluasi queue/distributed lock bila diperlukan;
   jangan menjalankan banyak worker dengan job guard in-process saat ini.
5. **Provider smoke test:** dengan kredensial pengguna dan persetujuan, uji
   STT/diarisasi/LLM nyata termasuk 429, timeout, dan invalid response.
6. **Backend constraints file:** hasilkan constraints terpinned untuk dependency
  transitif tanpa upgrade massal, lalu uji instalasi ulang di venv bersih.
7. **Browser test opsional:** bila diperlukan, tambahkan automation UI dengan
   dependency yang disetujui dan jangan melemahkan `node:test` yang ada.

## Penutup

Sprint 12 dinyatakan **selesai** sesuai Definition of Done: audit repository,
status Git, dependency management, dokumentasi instalasi, backup/restore,
manual acceptance checklist, regression test, dan production build semuanya
selesai. Tidak ada data pengguna yang dihapus dan tidak ada commit/push yang
dilakukan. Seluruh perubahan tetap berada di working directory.
