# Sprint 10 — Export Notulen (TXT & PDF)

## 1. Tujuan

Mengekspor **data rapat yang sudah tersimpan** menjadi berkas TXT dan PDF yang
rapi, tanpa menjalankan AI lagi, tanpa mengubah database, tanpa membuka file
audio, dan tanpa meninggalkan file sementara. Tombol unduhan tersedia di halaman
detail meeting.

Sprint 10 **tidak** menambah fitur AI, auth, email, kalender, queue, microservices,
PostgreSQL, maupun perubahan pada alur rekam/transkripsi/diarisasi/ringkasan/action
items.

## 2. Audit baseline (sebelum perubahan)

| Aspek | Hasil audit aktual |
| --- | --- |
| Struktur | `backend/`, `frontend/`, `docs/`, `storage/`, root `.env.example`, `.gitignore`, `README.md` |
| Test backend baseline | **210 passed, 1 warning** (deprecation Starlette/anyio) |
| Build frontend baseline | `npm run build` sukses |
| Endpoint detail meeting | **Tidak ada** `GET /api/v1/meetings/{id}`; frontend memakai `GET /api/v1/meetings` lalu mencari berdasarkan id |
| Library PDF | Tidak ada (`reportlab`, `fpdf`, `weasyprint`, `pypdf`, dll. tidak terpasang) |
| Framework test frontend | Tidak ada (tidak ada Vitest/Jest/`test` script) |
| Perubahan Sprint 9 | Masih uncommitted; tidak diubah oleh Sprint 10 |

Semua angka dan kondisi di atas diverifikasi dengan menjalankan perintah, bukan
diasumsikan dari laporan sebelumnya.

## 3. Keputusan desain & evaluasi dependency PDF

### 3.1 Export di backend, bukan frontend

Backend sudah menjadi pemilik proses dokumen/data (Pydantic, SQLAlchemy,
workflow). frontend hanya meminta Blob dan menyimpannya. Ini menghindari
duplikasi aturan format dan menjaga kerahasiaan path storage.

### 3.2 Path endpoint

Path yang diminta dipertahankan persis:

- `GET /api/v1/meetings/{meeting_id}/export/txt`
- `GET /api/v1/meetings/{meeting_id}/export/pdf`

Tidak ada perubahan path, jadi tidak perlu justifikasi path alternatif. Router
baru `backend/app/api/v1/export.py` dengan prefix `/meetings` didaftarkan paling
akhir di `api_router` agar tidak menimpa route lain.

### 3.3 Alternatif library PDF yang dievaluasi

| Opsi | Keputusan | Alasan |
| --- | --- | --- |
| PDF writer buatan sendiri (xref + stream manual) | Ditolak | Risiko tinggi PDF invalid, xref salah, dan tidak ada dukungan Unicode/table/page-break yang andal |
| Pillow → gambar → PDF | Ditolak | Teks tidak bisa dipilih/dicari, bukan format notulen profesional, dan Pillow hanya dependency transitif yang tidak dideklarasikan |
| **reportlab 4.4.10** | **Dipilih** | Mature, pure-Python, Platypus menyediakan page break/table/header/footer/page number, serta mendukung font TTF Unicode. Font Bitstream Vera sudah dibundling dalam paket, jadi tidak perlu font sistem atau file baru di repo |
| weasyprint / fpdf2 | Ditolak | Butuh dependency sistem/html renderer tambahan atau dukungan TTF/table yang lebih kompleks untuk kebutuhan ini |

Versi **4.4.10** dipilih daripada 5.1.0 (terbaru saat audit) karena rilis 4.x
adalah jalur stabil yang kompatibel dengan Python 3.12 dan lebih konservatif
untuk proyek ini. `pypdf==7.1.1` ditambahkan **hanya untuk test** agar parser PDF
sungguhan membuktikan hasil export dapat dibaca (bukan sekadar cek header `%PDF`).

Keduanya ditambahkan ke `backend/requirements.txt`. Tidak ada dependency baru di
`frontend/package.json`; test frontend memakai `node:test` bawaan Node.js 24.

### 3.4 Prinsip implementasi

- **Read-only:** `load_notulen()` hanya `SELECT`; tidak ada `add()`, `commit()`,
  `delete()`, atau perubahan status meeting.
- **Tanpa AI:** tidak ada import/registry pemanggilan STT, diarisasi, atau LLM.
- **Tanpa audio:** `AudioAsset` hanya dibaca untuk `duration_seconds` (metadata).
  File di `STORAGE_DIR` tidak pernah dibuka; test sengaja memakai path audio yang
  tidak ada dan export tetap sukses.
- **Di memori:** TXT dikodekan UTF-8 ke `bytes`, PDF dibangun di `io.BytesIO`.
  Tidak ada `NamedTemporaryFile`, tidak ada file di `storage/`, tidak ada file
  sementara yang tertinggal.
- **Tidak mengarang:** bagian kosong menjadi `Belum tersedia.` dan status job
  (`NOT_STARTED/PROCESSING/COMPLETED/FAILED`) ikut dicantumkan agar export parsial
  tidak menyesatkan. Nama speaker memakai `display_name` bila ada, jika tidak
  label anonim `Speaker N`.
- **Keamanan:** `meeting_id` divalidasi sebagai UUID oleh FastAPI (422 bila salah);
  meeting tidak ada → 404. Judul dijadikan slug ASCII untuk nama file, sehingga
  tidak ada `/`, `\`, `..`, quote, karakter kontrol, atau path internal. Error tak
  terduga → 500 generik; kategori exception saja yang dicatat ke log, pesan
  aslinya (yang bisa memuat path/secret) tidak pernah masuk response/log.

## 4. File yang ditambah/diubah

**Backend**

- `backend/app/services/export.py` (baru) — snapshot data, render TXT, render PDF,
  slug nama file, font & sanitasi Unicode.
- `backend/app/api/v1/export.py` (baru) — dua endpoint export + response headers.
- `backend/app/api/v1/router.py` — mendaftarkan `export.router`.
- `backend/requirements.txt` — `reportlab==4.4.10`, `pypdf==7.1.1` (test).
- `backend/tests/test_sprint10.py` (baru) — 12 test export & regresi.

**Frontend**

- `frontend/src/utils/export.ts` (baru) — parser filename, fallback aman, `saveBlob`.
- `frontend/src/api.ts` — `downloadExport(meetingId, format)`.
- `frontend/src/components/MeetingDetail.tsx` — panel **Ekspor Notulen** dengan
  dua tombol, loading, error, dan pencegahan klik ganda.
- `frontend/package.json` — script `test` = `node --test tests/*.test.ts`.
- `frontend/tests/export.test.ts` (baru) — 7 test helper export.

**Dokumentasi**

- `docs/SPRINT10.md` (baru), `docs/README.md`, `docs/ARCHITECTURE.md`, `README.md`.

## 5. Endpoint & response

| Method | Path | Success | Content-Type | Content-Disposition |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/meetings/{meeting_id}/export/txt` | 200 | `text/plain; charset=utf-8` | `attachment; filename="notulen-<slug>.txt"` |
| GET | `/api/v1/meetings/{meeting_id}/export/pdf` | 200 | `application/pdf` | `attachment; filename="notulen-<slug>.pdf"` |

Error: `404` meeting tidak ditemukan, `422` UUID tidak valid, `500` kegagalan
pembuatan dokumen (pesan generik). Tidak ada redirect, tidak ada penulisan file,
dan tidak ada header yang membocorkan path server.

Contoh slug: judul `../../Rapat "Aneh"? — é` menghasilkan
`notulen-rapat-aneh.txt` (ASCII, tanpa path/quote).

## 6. Struktur TXT

```text
NOTULEN RAPAT
================================================================
Dibuat oleh MeetNote AI dari data yang tersimpan (tanpa proses AI saat export).

INFORMASI RAPAT
----------------------------------------------------------------
Judul           : ...
Tanggal dibuat  : YYYY-MM-DD HH:MM:SS
Status meeting  : ...
ID meeting      : <uuid>
Durasi rekaman  : m:ss (atau Belum tersedia.)
Status transkripsi   : ...
Status diarisasi     : ...
Status ringkasan     : ...
Status action items  : ...

PEMBICARA
----------------------------------------------------------------
- Speaker 1 (Nama dari pengguna)
- Speaker 2

RINGKASAN EKSEKUTIF
----------------------------------------------------------------
<overview>

TOPIK PEMBAHASAN
----------------------------------------------------------------
1. Judul topik
   Detail topik
   Sumber: m:ss–m:ss

KEPUTUSAN
----------------------------------------------------------------
1. Teks keputusan
   Sumber: m:ss–m:ss

ACTION ITEMS
----------------------------------------------------------------
1. [OPEN] Judul
   Deskripsi       : ...
   Penanggung jawab: Speaker 1 (Nama) / teks eksplisit
   Deadline        : YYYY-MM-DD (frasa) atau Belum tersedia.
   Sumber          : m:ss–m:ss
   (diedit manual)

TRANSKRIP
----------------------------------------------------------------
[0:00 - 0:02] Speaker 1 (Nama): Teks segmen
[2:00 - 4:00] Speaker 2: ...

----------------------------------------------------------------
Akhir dokumen.
```

## 7. Struktur PDF

- Font Bitstream Vera (TTF dari reportlab) dengan fallback Helvetica bila font
  tidak tersedia; karakter Latin-1/Extended (é, è, ñ) didukung, tanda hubung
  panjang/kutip kurung dinormalisasi ke ASCII, dan glyph di luar font diganti `?`
  agar PDF tetap valid. Teks di-escape sebagai XML sebelum masuk `Paragraph`.
- Halaman A4, margin 18–22 mm, header (nama aplikasi + "Notulen Rapat"), footer
  (judul meeting + `Halaman N`), garis pemisah header/footer, dan metadata
  dokumen (`/Title`, `/Author`, `/Subject`).
- Bagian: judul, informasi rapat (tabel dua kolom), pembicara, ringkasan
  eksekutif, topik, keputusan, action items (tabel dengan header berulang
  `repeatRows`), `PageBreak`, lampiran transkrip.
- Tabel memakai `Paragraph` per sel sehingga teks panjang dibungkus otomatis dan
  baris bisa pecah halaman; lebar kolom tetap dalam mm.
- PDF diuji dengan `pypdf.PdfReader`: minimal 2 halaman, metadata ada, dan teks
  utama (judul, Overview, action item, lampiran transkrip, nomor halaman) bisa
  diekstrak.

## 8. Perilaku data kosong/parsial

| Kondisi | Perilaku export |
| --- | --- |
| Meeting baru, tanpa rekaman/transkrip/ringkasan/action item | Tetap 200. Semua bagian berisi `Belum tersedia.`; status job `NOT_STARTED` tercantum |
| Transkrip ada, ringkasan belum | Ringkasan/topik/keputusan `Belum tersedia.`; transkrip tetap diekspor |
| Ringkasan ada, sebagian field kosong | Field kosong ditampilkan apa adanya; tidak dibuat teks pengganti selain penanda bagian kosong |
| Action item punya `deadline_text` tanpa `due_date` | Deadline menampilkan frasa tersebut; tidak dibuat tanggal rekaan |
| Segmen tanpa speaker | Prefix speaker tidak ditampilkan di TXT; PDF menampilkan `-` |
| File audio hilang dari storage | Export tetap sukses karena hanya metadata yang dibaca |

## 9. Frontend

Panel **Ekspor Notulen** muncul di halaman detail meeting, sebelum bagian
rekaman, dan tidak bergantung pada keberadaan audio.

- Tombol **Unduh TXT** dan **Unduh PDF**.
- `exporting: 'txt' | 'pdf' | null` — hanya satu format aktif; kedua tombol
  `disabled` selama proses sehingga klik berulang diabaikan.
- Label berubah menjadi **Menyiapkan…** pada format yang aktif.
- Error ditampilkan di `role="alert"` memakai pesan `detail` backend bila ada,
  atau pesan koneksi generik bila fetch gagal.
- `saveBlob()` membuat anchor sementara, memicu klik, lalu menghapus anchor di
  blok `finally` dan mencabut object URL segera setelahnya (default 1 detik,
  supaya browser sempat memulai unduhan). Tidak ada anchor/object URL yang
  tertinggal.
- `exportInFlightRef` menolak klik kedua bahkan sebelum React sempat me-render
  ulang status `disabled`, jadi duplikat unduhan tidak mungkin terjadi.
- Nama file diambil dari `Content-Disposition`; bila header tidak ada/tidak aman,
  fallback `notulen-<8 karakter id>.<ext>` dipakai.
- Tidak ada perubahan pada recording/playback, transkrip, speaker, ringkasan,
  atau action items.

## 10. Pengujian

### Backend — `cd backend && python -m pytest -q`

Kasus yang diuji (`tests/test_sprint10.py`, 12 test):

1. meeting tidak ditemukan → 404 untuk TXT dan PDF, tanpa path internal;
2. UUID tidak valid → 422;
3. TXT berisi semua bagian, info rapat, speaker, ringkasan, topik, keputusan,
   action item (judul/deskripsi/assignee/deadline/status/sumber/edit manual), dan
   transkrip berurutan sesuai `sequence` dengan timestamp `m:ss`;
4. data kosong → placeholder eksplisit + status `NOT_STARTED`;
5. PDF valid menurut `pypdf`, ≥2 halaman, metadata, teks dapat diekstrak, Unicode
   didukung, nomor halaman ada;
6. Content-Type dan Content-Disposition benar untuk kedua format;
7. nama file disanitasi (tanpa `/`, `\`, `..`, quote, karakter non-ASCII);
8. Unicode TXT dipertahankan;
9. export tidak memerlukan file audio yang benar-benar ada;
10. kegagalan internal → 500 generik, tidak membocorkan pesan/path ke response
    maupun log (hanya kategori exception);
11. export bersifat read-only dan tidak meninggalkan file di `storage/` (snapshot
    DB dan daftar file dibandingkan sebelum/sesudah);
12. judul dengan `&` tidak menghasilkan `&amp;` pada metadata/header PDF (escape
    XML hanya untuk `Paragraph`).

### Frontend — `cd frontend && npm test`

7 test `node:test` (tanpa dependency baru): header filename, format tanpa kutip,
path traversal ditolak, quote/newline/panjang ditolak, fallback nama file, header
kosong, dan pembersihan object URL/anchor.

### Regresi Sprint 1–9

Seluruh test backend lama tetap dijalankan dalam satu perintah `pytest -q`. Tidak
ada test lama yang diubah atau dihapus. `npm run build` tetap sukses.

Hasil eksekusi akhir: backend **222 passed, 1 warning**; frontend **7 passed**,
`npm run build` sukses. Warning tunggal berasal dari deprecation Starlette/anyio
yang sudah ada sejak baseline.

## 11. Cara manual menguji

1. Pastikan backend dan frontend berjalan seperti di `README.md`.
2. Buat meeting, unggah/rekam audio, jalankan transkripsi → diarisasi →
   ringkasan → action items (boleh memakai provider `mock`).
3. Buka detail meeting. Klik **Unduh TXT**; periksa isi dan nama file.
4. Klik **Unduh PDF**; buka dengan PDF viewer, periksa(header/footer, nomor
   halaman, tabel action item, lampiran transkrip di halaman berikutnya, dan
   karakter seperti `é`).
5. Saat tombol ditekan, pastikan label berubah dan klik kedua diabaikan.
6. Matikan/simulasikan error backend, pastikan pesan error muncul tanpa path
   internal.
7. Buka meeting kosong; pastikan export tetap berhasil dengan penanda
   `Belum tersedia.`.
8. Periksa `storage/` dan database — tidak ada berkas export yang dibuat dan
   tidak ada data yang berubah.

## 12. Keterbatasan & risiko

- Teks PDF dibatasi glyph font yang dibundling; karakter di luar Latin Extended
  (mis. CJK/emoji) diganti `?`. TXT tetap mempertahankan Unicode penuh.
- Tidak ada opsi pilih bagian (mis. hanya action items), watermark, tanda tangan,
  atau bahasa UI selain Indonesia untuk label dokumen.
- Export adalah snapshot saat request; bila ada job background yang selesai
  bersamaan, unduhan berikutnya baru memuat data terbaru.
- `reportlab` dan `pypdf` menambah dependency backend; keduanya pure-Python dan
  tidak memerlukan font/perangkat lunak sistem.
- Test frontend hanya mencakup helper murni dengan `node:test`; tidak ada
  component/DOM test framework, sehingga interaksi React diverifikasi lewat build
  dan peninjauan kode, bukan automation browser.
- Provider cloud tetap belum diuji live (tidak ada API key); ini tidak berubah
  dari Sprint 9.

## 13. Konfirmasi Git

Tidak ada `git commit`, `git push`, perubahan remote, penghapusan DB/audio, atau
perubahan Execution Policy Windows yang dilakukan pada Sprint 10. Audit kembali
menunjukkan direktori proyek **bukan repository Git** (`git status` mengembalikan
`fatal: not a git repository`), sehingga tidak ada operasi Git yang mungkin
dilakukan maupun diperlukan. Semua perubahan tersisa langsung di filesystem.
