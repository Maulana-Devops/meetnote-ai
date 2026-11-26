# Prosedur Backup & Restore — MeetNote AI

Dokumen ini menjelaskan cara menjaga konsistensi **database SQLite** dan **file
audio** MeetNote AI. Prosedur di bawah **tidak dijalankan** dalam Sprint 12;
tidak ada backup, restore, penghapusan, atau penimpaan data pengguna yang
dilakukan.

Semua perintah menggunakan **Windows PowerShell** dan tidak mengubah Windows
Execution Policy.

## 1. Apa yang perlu disimpan

| Komponen | Lokasi relatif terhadap root proyek | Wajib? | Catatan |
| --- | --- | --- | --- |
| Database utama | `backend/meetnote.db` | Ya | Berisi meeting, metadata audio, transkrip, speaker, ringkasan, action items, dan job |
| Audio produksi | `storage/meetings/<meeting_id>/recording-<uuid><ekstensi>` | Ya | File fisik audio berada di filesystem, bukan di dalam DB |
| Konfigurasi backend | `backend/.env` | Ya, disimpan aman | Berisi provider, port, storage, CORS, dan API key bila dipakai |
| Konfigurasi frontend | `frontend/.env` | Ya | Berisi `VITE_API_BASE_URL` |
| Contoh konfigurasi | `.env.example`, `backend/.env.example`, `frontend/.env.example` | Tidak | Sudah ada di repository; hanya placeholder |

Database test (`backend/api_test.db`, `backend/test.db`) dan storage test
(`backend/test_storage/`) **tidak perlu** ikut dalam backup produksi. Keduanya
dibuat/dipakai oleh test suite.

File `.env`, `*.db`, `storage/*`, `test_storage/`, dan `backups/` sudah dikecualikan
oleh `.gitignore`. Jangan pernah menaruh API key di chat, di `frontend/.env`, atau
di variabel berprefiks `VITE_*`.

## 2. Hubungan database dan audio

Hubungan yang harus tetap valid adalah:

```text
meetings.id
  └─ audio_assets.meeting_id
       └─ audio_assets.storage_path = "meetings/<meeting_id>/recording-<uuid><ekstensi>"
            └─ file fisik di STORAGE_DIR / storage_path
```

`storage_path` adalah **path relatif** terhadap `STORAGE_DIR` (default: folder
`storage/` di root proyek). Database tidak menyimpan path absolut dan tidak
menyimpan isi audio. Karena keduanya terpisah:

- menyalin DB tanpa folder `storage/` membuat metadata audio bersisa tetapi file
  tidak ada;
- menyalin folder `storage/` tanpa DB membuat file audio menjadi yatim;
- keduanya harus berasal dari **titik waktu yang sama**.

Endpoint `GET /api/v1/health/diagnostics` melaporkan kondisi ini lewat
`metadata_without_file`, `orphan_files`, `temp_files`, `trash_files`, dan
`invalid_metadata_paths`. Audit ini bersifat read-only.

## 3. Backup sederhana (disarankan)

Cara paling aman untuk instalasi lokal/single-user adalah **menghentikan backend
lebih dulu**, lalu menyalin DB dan folder storage.

### 3.1 Hentikan aplikasi

Hentikan proses uvicorn/backend dan pastikan tidak ada test pytest yang sedang
berjalan. Ini menghindari salinan DB yang berada di tengah transaksi.

### 3.2 Salin DB dan audio

Dari root proyek:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$root = (Get-Location).Path
$dest = Join-Path $root "backups\$stamp"

New-Item -ItemType Directory -Path (Join-Path $dest "db"),(Join-Path $dest "storage") -Force | Out-Null
Copy-Item "backend\meetnote.db" (Join-Path $dest "db\meetnote.db")
robocopy "storage" (Join-Path $dest "storage") /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
```

`robocopy` mengembalikan kode `0`–`7` untuk kondisi sukses; kode `8` atau lebih
menandakan error. Periksa output sebelum menganggap backup berhasil.

Perintah `/E` menyalin seluruh subtree termasuk folder kosong. **Jangan**
memakai `/MIR` untuk backup karena `/MIR` dapat menghapus file di tujuan yang
tidak ada di sumber.

### 3.3 Simpan konfigurasi secara terpisah

Simpan `.env` di lokasi aman di luar folder proyek atau lokasi terenkripsi.
Contoh (sesuaikan path):

```powershell
$secure = "C:\MeetNoteSecrets\$stamp"
New-Item -ItemType Directory -Path $secure -Force | Out-Null
Copy-Item "backend\.env" (Join-Path $secure "backend.env")
Copy-Item "frontend\.env" (Join-Path $secure "frontend.env")
```

Jangan memasukkan folder `$secure` ke dalam paket rilis atau repository.

## 4. Backup database tanpa menghentikan backend

Jika backend memang harus tetap hidup, SQLite menyediakan **Online Backup API**
yang menghasilkan snapshot konsisten untuk database. Dari root proyek:

```powershell
.\backend\.venv\Scripts\python.exe -c "import sqlite3,pathlib,datetime; src=sqlite3.connect('backend/meetnote.db'); out=pathlib.Path('backups',datetime.datetime.now().strftime('online-%Y%m%d-%H%M%S.db')); out.parent.mkdir(parents=True,exist_ok=True); dst=sqlite3.connect(out); src.backup(dst); dst.close(); src.close(); print(out)"
```

Batasan penting:

- perintah di atas hanya menyalin **database**, bukan folder `storage/`;
- folder audio tetap perlu disalin terpisah, dan keduanya tidak lagi otomatis
  menjadi satu titik waktu yang identik bila aktivitas upload terjadi bersamaan;
- untuk rilis lokal/single-user, menghentikan backend seperti pada bagian 3 lebih
  sederhana dan lebih mudah diverifikasi;
- jangan menyalin file `meetnote.db-journal`, `-wal`, atau `-shm` secara manual
  kecuali Anda memahami mode journal SQLite yang dipakai. Hentikan backend bila
  ragu.

## 5. Restore dengan konfirmasi

Restore **tidak boleh** menimpa data pengguna secara otomatis. Ikuti urutan ini.

### 5.1 Hentikan backend dan aplikasi

Pastikan uvicorn, pytest, dan frontend yang sedang memanggil API tidak aktif.

### 5.2 Buat backup kondisi saat ini

Sebelum menimpa apa pun, simpan kondisi saat ini:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$pre = "backups\pre-restore-$stamp"
New-Item -ItemType Directory -Path (Join-Path $pre "db"),(Join-Path $pre "storage") -Force | Out-Null
Copy-Item "backend\meetnote.db" (Join-Path $pre "db\meetnote.db")
robocopy "storage" (Join-Path $pre "storage") /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
```

### 5.3 Minta konfirmasi eksplisit

Ganti `<stamp>` dengan nama folder backup yang akan dipulihkan:

```powershell
$backup = "backups\<stamp>"
if ((Read-Host "Pulihkan dari $backup? Ketik YES untuk melanjutkan") -ne "YES") {
    throw "Restore dibatalkan."
}
```

### 5.4 Pulihkan database

```powershell
Copy-Item (Join-Path $backup "db\meetnote.db") "backend\meetnote.db" -Force
```

Jangan menghapus `backend/meetnote.db` terlebih dahulu. Salinan kondisi saat ini
sudah tersimpan di `backups\pre-restore-$stamp\db\meetnote.db`.

### 5.5 Pulihkan audio

```powershell
robocopy (Join-Path $backup "storage") "storage" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
```

Catatan:

- gunakan `/E`, **bukan `/MIR`**; `/MIR` akan menghapus file di `storage/` yang
  tidak ada di backup;
- file dengan nama sama akan ditimpa oleh salinan backup setelah konfirmasi;
- file audio tambahan yang tidak ada di backup sengaja dibiarkan dan akan
  dilaporkan sebagai `orphan_files` oleh diagnostics; keputusan penghapusan
  tetap di tangan pengguna;
- jangan menghapus file `.part` atau `.delete` otomatis; keduanya bisa berasal
  dari proses yang crash.

### 5.6 Pulihkan konfigurasi

Salin kembali `backend.env` dan `frontend.env` dari lokasi aman ke
`backend/.env` dan `frontend/.env` bila diperlukan. Pastikan API key tetap hanya
ada di backend.

## 6. Verifikasi hasil restore

### 6.1 Health dan diagnostics

Jalankan backend, lalu:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/health/diagnostics
```

Yang diharapkan:

- `status` = `healthy`;
- `sqlite_foreign_keys` = `1`;
- `invalid_metadata_paths` = `0`;
- `metadata_without_file` = kosong;
- `orphan_files`, `temp_files`, dan `trash_files` ditinjau manual, bukan dihapus
  otomatis.

### 6.2 Cek keberadaan file audio dari database

Dari root proyek:

```powershell
.\backend\.venv\Scripts\python.exe -c "import sqlite3,pathlib; con=sqlite3.connect('backend/meetnote.db'); rows=con.execute('select storage_path from audio_assets').fetchall(); root=pathlib.Path('storage'); missing=[p for (p,) in rows if not (root / p).is_file()]; print('audio_metadata=',len(rows),'missing=',len(missing)); print(missing[:10])"
```

`missing` harus bernilai `0`. Jika tidak, jangan menghapus baris database;
periksa apakah folder `storage/` yang salah dipulihkan atau apakah path relatif
di DB tidak cocok dengan `STORAGE_DIR` aktif.

### 6.3 Cek UI dan export

Buka beberapa meeting yang dipulihkan:

- daftar meeting tampil;
- audio bisa diputar dan di-seek;
- transkrip, speaker, ringkasan, dan action items tampil;
- `GET /api/v1/meetings/{meeting_id}/export/txt` dan
  `GET /api/v1/meetings/{meeting_id}/export/pdf` menghasilkan isi yang sesuai UI.

Export hanya membaca DB, jadi export tetap bisa berhasil walaupun file audio
hilang. Karena itu, pemeriksaan playback pada 6.2–6.3 tetap wajib.

## 7. Yang tidak boleh dilakukan

- Jangan menjalankan restore tanpa backup kondisi saat ini.
- Jangan menimpa DB/audio hanya karena diagnostics menunjukkan anomali.
- Jangan memakai `robocopy /MIR` untuk restore storage.
- Jangan menghapus `*.db`, `storage/`, `node_modules/`, `dist/`, atau
  `backend/test_storage/` saat melakukan packaging/backup.
- Jangan menjalankan migrasi destruktif atau `git init`/commit/push.
- Jangan menempelkan isi `.env` atau API key ke chat, log, atau dokumentasi.

## 8. Ringkasan urutan aman

```text
backup:   hentikan backend → salin meetnote.db → salin storage/ → simpan .env aman
restore:  hentikan backend → backup kondisi saat ini → konfirmasi YES
          → salin DB backup → salin storage backup → salin .env → verifikasi
```

Untuk daftar pemeriksaan fungsional setelah restore, lihat
`docs/MANUAL_ACCEPTANCE_TEST.md`. Untuk instalasi dari kondisi bersih, lihat
`docs/INSTALLATION.md`.
