# Sprint 3 — Audio File Upload & Recording Management

## Tujuan
Pengguna dapat mengunggah file audio lokal dari komputer dan mengelola rekaman
yang sudah tersimpan (hapus, lalu unggah/rekam ulang), tanpa mengganggu alur
perekaman langsung dari Sprint 2.

## Sudah tercapai
- [x] Audit Sprint 1 & Sprint 2 sebelum mengubah kode (test lama: 16 passed)
- [x] Endpoint `POST /api/v1/meetings/{id}/recording` **dipakai ulang** untuk upload lokal
- [x] `DELETE /api/v1/meetings/{id}/recording` — hapus metadata + file, status kembali `PENDING`
- [x] `GET /api/v1/config` — batas ukuran & daftar format untuk frontend (bukan secret)
- [x] Validasi MIME + ekstensi + ukuran di backend (sumber validasi utama)
- [x] Pemeriksaan signature audio sederhana (EBML/OggS/RIFF-WAVE/ID3/MP3 frame/ftyp)
- [x] Nama file generated UUID; path traversal dicegah saat hapus maupun playback
- [x] File sementara `.part` / `.delete` + rollback saat transaksi gagal
- [x] Frontend: file picker, drag-and-drop, nama file, ukuran, durasi, preview, remove
- [x] Frontend: indikator upload, pesan sukses/error, konfirmasi hapus
- [x] Satu `AudioAsset` per meeting — rekaman dan upload saling menonaktifkan di UI
- [x] Detail meeting: `Delete Recording`, lalu `+ Tambah Rekaman`
- [x] Test backend: 33 passed (16 lama + 17 baru)
- [x] `npm run build` berhasil (type-check + Vite build)

## Endpoint API

| Method | Path | Fungsi |
| --- | --- | --- |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/config` | Batas ukuran & format audio (publik) |
| GET | `/api/v1/meetings` | Daftar meeting + metadata rekaman |
| POST | `/api/v1/meetings` | Buat meeting (status `PENDING`) |
| POST | `/api/v1/meetings/{id}/recording` | Simpan rekaman **atau** file audio lokal |
| GET | `/api/v1/meetings/{id}/recording` | Metadata rekaman |
| GET | `/api/v1/meetings/{id}/recording/play` | Playback audio (`FileResponse`) |
| DELETE | `/api/v1/meetings/{id}/recording` | Hapus rekaman + file, status → `PENDING` |

Error: `400` ekstensi ditolak, `404` meeting/rekaman tidak ditemukan,
`409` duplikat rekaman, `413` terlalu besar, `415` MIME tidak didukung / signature
tidak cocok, `500` kegagalan storage/database.

### Kenapa tidak ada endpoint upload baru?

Endpoint `POST .../recording` Sprint 2 sudah menerima `multipart/form-data`
dengan field `file` dan `duration_seconds`, menyimpan file ke
`STORAGE_DIR/meetings/{id}/`, dan menulis metadata `AudioAsset`. Perbedaan
Sprint 3 hanya pada sumber Blob (file lokal vs MediaRecorder), jadi endpoint
yang sama dipakai ulang — tidak ada duplikasi API.

Satu perubahan kontrak kecil: ekstensi asli `.mp4` kini diterima sebagai input
(MP4 audio umum), tetapi nama file internal tetap `.m4a` agar konsisten.

## Format audio

| Format | MIME diterima | Ekstensi input | Nama internal |
| --- | --- | --- | --- |
| WebM | `audio/webm` | `.webm` | `.webm` |
| OGG | `audio/ogg` | `.ogg` | `.ogg` |
| WAV | `audio/wav`, `audio/x-wav` | `.wav` | `.wav` |
| MP3 | `audio/mpeg` | `.mp3` | `.mp3` |
| M4A / MP4 | `audio/mp4`, `audio/x-m4a` | `.m4a`, `.mp4` | `.m4a` |

Parameter MIME seperti `;codecs=opus` dibuang sebelum divalidasi. Batas ukuran
default **25 MB** (`MAX_AUDIO_FILE_BYTES=26214400`), dapat diubah lewat `.env`.

## Batasan validasi format

Backend memeriksa, berurutan:
1. **Ukuran** — tolak `413` jika melebihi `MAX_AUDIO_FILE_BYTES`.
2. **MIME type** — normalkan, lalu tolak `415` jika tidak ada dalam daftar.
3. **Ekstensi nama asli** — tolak `400` jika tidak dikenali (hanya validasi,
   bukan dipakai sebagai path).
4. **Signature sederhana** — jika signature dikenali dan **berbeda** dengan MIME
   yang dinyatakan, tolak `415`. Jika signature tidak dikenali, file tetap
   diterima agar payload MediaRecorder lama tetap kompatibel.

Ini **bukan** validasi konten yang sempurna: file bisa saja berisi data bukan
audio selama signature-nya tidak dikenali. Pemeriksaan decode penuh / FFprobe
tidak dilakukan di sprint ini (butuh dependensi tambahan). Frontend melakukan
pemeriksaan awal yang sama untuk UX, tetapi backend tetap sumber keputusan.

## Cara upload audio

1. Buat meeting baru atau buka detail meeting yang belum punya rekaman.
2. Klik **Choose Audio File** atau tarik file ke area dropzone.
3. File **tidak** langsung diunggah — muncul nama, ukuran, durasi (jika browser
   bisa membaca metadata), dan audio preview.
4. Klik **Upload Audio**. Indikator "Mengunggah…" muncul hingga selesai.
5. **Remove** membatalkan pilihan sebelum upload (dengan object URL dibersihkan).
6. Setelah sukses, halaman detail menampilkan banner sukses + metadata.

Binary audio tidak pernah masuk `localStorage`; preview memakai
`URL.createObjectURL` yang di-`revoke` saat diganti/dihapus/unmount.

## Cara menghapus rekaman

1. Buka detail meeting yang memiliki rekaman.
2. Klik **Delete Recording**, lalu konfirmasi pada dialog browser.
3. Backend memindahkan file ke nama `.delete`, menghapus baris `AudioAsset`,
   dan mengubah status meeting menjadi `PENDING`. Jika commit gagal, file
   dikembalikan ke posisi semula. Jika file sudah hilang, metadata tetap bisa
   dihapus dengan aman.
4. Halaman detail menampilkan tombol **+ Tambah Rekaman** — pengguna bisa
   merekam ulang atau mengunggah file baru lewat endpoint yang sama.

Path file diambil dari kolom `storage_path` di database, bukan dari input
pengguna, dan divalidasi dengan `is_relative_to()` terhadap `STORAGE_DIR`
sebelum penghapusan. File di luar storage tidak bisa dihapus.

## Perubahan database

Tidak ada perubahan skema. Tabel `meetings` dan `audio_assets` dari Sprint 2
dipakai apa adanya. Satu-satunya perubahan data: setelah `DELETE`, baris
`audio_assets` hilang dan `meetings.status` menjadi `PENDING`.

## Lokasi penyimpanan

Sama seperti Sprint 2: `storage/meetings/{meeting_id}/recording-{uuid}.{ext}`.
Metadata di `backend/meetnote.db` tabel `audio_assets`, path relatif disimpan
di kolom `storage_path`. Database dan file audio lama tidak dihapus.

## Pengujian

```powershell
cd backend
python -m pytest -q
```
Hasil: **33 passed, 1 warning** (warning deprecation Starlette/anyio).

```powershell
cd frontend
npm run build
```
Hasil: sukses, 38 modules transformed.

Test Sprint 3 mencakup: upload WebM/WAV/MP3/MP4, MIME tidak didukung, ekstensi
tidak didukung, signature tidak cocok, file terlalu besar, meeting tidak ada,
metadata & playback setelah upload, delete, delete saat rekaman tidak ada,
upload ulang setelah delete, path di luar storage, dan file sudah hilang.

## Tidak termasuk Sprint 3
Speech-to-text, Whisper, diarisasi, summarization AI, action items, auth,
kolaborasi, PostgreSQL, Docker, deployment, sistem antrean pekerjaan.
