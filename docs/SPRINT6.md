# Sprint 6 — Edit Transkrip & Kelola Speaker

## 1. Tujuan & ruang lingkup

Sprint 6 menambahkan koreksi **user-facing** atas hasil yang sudah ada:

- menyunting teks satu segmen transkrip;
- memberi, mengubah, dan menghapus nama tampilan speaker buatan pengguna;
- menetapkan atau melepaskan speaker pada satu segmen secara manual;
- melompat ke bagian rekaman lewat timestamp segmen.

Sprint ini **hanya mengelola hasil transkripsi/diarisasi yang sudah tersimpan**.
Tidak ada pemanggilan ulang STT/diarisasi, tidak ada penulisan ulang oleh AI,
tidak ada summarization/action items, dan tidak ada perubahan kontrak provider.

## 2. Audit awal & baseline

Sebelum menulis kode:

- Dokumen dibaca: `README.md`, `docs/ARCHITECTURE.md`,
  `docs/SPRINT1.md` … `docs/SPRINT5.md`.
- Kode diperiksa: `Meeting`, `AudioAsset`, `TranscriptSegment`,
  `Speaker`, `TranscriptionJob`, `DiarizationJob`, workflow transkripsi dan
  diarisasi, `api/v1/*`, `schemas/*`, router, migrasi aditif, `tests/conftest.py`,
  `tests/test_sprint5.py`, serta frontend `MeetingDetail.tsx`, `api.ts`,
  `types.ts`, `utils/format.ts`, dan `styles.css`.
- Backend baseline: `python -m pytest -q` → **95 passed, 1 warning**.
- Frontend baseline: `npm run build` → **sukses**, 38 modules transformed,
  `built in 1.60s`.
- Warning hanya `DeprecationWarning` Starlette/anyio
  (`anyio.abc.BlockingPortal`).

Sprint 5 dinyatakan selesai dan menjadi baseline. Semua perubahan Sprint 6
dibiarkan **uncommitted** sesuai permintaan.

## 3. Konvensi yang dipakai

| Konvensi | Penerapan di Sprint 6 |
| --- | --- |
| Pemisahan endpoint/service | Endpoint tipis di `api/v1/transcript_edits.py`, aturan di `services/transcript_editing.py` |
| Kepemilikan data | Selalu query dengan `meeting_id` + id objek, bukan id saja |
| Validasi di backend | Pydantic hanya membentuk request; aturan bisnis menghasilkan 400/404/409/500 |
| Error aman | Pesan 500 generik, detail SQLAlchemy tidak pernah dikirim ke UI |
| Migrasi aditif | Tidak ada kolom/tabel baru; `apply_additive_migrations()` tidak diubah |
| UUID | Id segmen/speaker tetap UUID string di database |
| Bahasa UI/pesan | Indonesia, mengikuti Sprint 1–5 |
| Komponen kecil | Editor dipecah jadi tiga komponen React, bukan satu `MeetingDetail` raksasa |
| Tanpa dependency baru | Backend dan frontend memakai library yang sudah ada |

## 4. Arsitektur & struktur file

```text
Browser (React)
  │ PATCH /meetings/{id}/transcript/{segment_id}        ← teks segmen
  │ PATCH /meetings/{id}/transcript/{segment_id}/speaker← speaker/manual
  │ PATCH /meetings/{id}/speakers/{speaker_id}          ← display_name
  ▼
FastAPI /api/v1/transcript_edits.py
  ▼
services/transcript_editing.py
  ├─ validasi meeting → job aktif → objek → input
  ├─ UPDATE kolom tunggal + commit (atau skip bila tidak berubah)
  └─ response: TranscriptSegmentRead / SpeakerRead
  ▼
SQLite: transcript_segments.text / .speaker_id, speakers.display_name
```

File baru:

```text
backend/app/api/v1/transcript_edits.py
backend/app/schemas/transcript_editing.py
backend/app/services/transcript_editing.py
backend/tests/test_sprint6.py
frontend/src/components/TranscriptEditor.tsx
frontend/src/components/TranscriptSegmentItem.tsx
frontend/src/components/SpeakerManager.tsx
docs/SPRINT6.md
```

File yang dimodifikasi:

- backend: `app/models/transcript.py`, `app/schemas/transcription.py`,
  `app/api/v1/router.py`;
- frontend: `src/api.ts`, `src/types.ts`, `src/components/MeetingDetail.tsx`,
  `src/styles.css`;
- dokumen: `README.md`, `docs/ARCHITECTURE.md`, `docs/README.md`.

## 5. Endpoint API

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| PATCH | `/api/v1/meetings/{meeting_id}/transcript/{segment_id}` | `{"text": "..."}` | `TranscriptSegmentRead` |
| PATCH | `/api/v1/meetings/{meeting_id}/transcript/{segment_id}/speaker` | `{"speaker_id": "uuid" \| null}` | `TranscriptSegmentRead` |
| PATCH | `/api/v1/meetings/{meeting_id}/speakers/{speaker_id}` | `{"display_name": "nama" \| null}` | `SpeakerRead` |

Semua response langsung memuat data terbaru dari database, termasuk
`speaker_label` dan `speaker_display_name` pada segmen. Tidak ada endpoint POST
baru, tidak ada job background, dan tidak ada perubahan pada endpoint Sprint 1–5.

Urutan validasi setiap endpoint: meeting ada → tidak ada job `PROCESSING` →
segmen/speaker ada dan masih satu meeting → input valid → commit.

## 6. Perilaku edit teks segmen

- Hanya kolom `text` yang ditulis. `id`, `meeting_id`, `sequence`,
  `start_seconds`, `end_seconds`, `created_at`, dan `speaker_id` dipertahankan.
- Teks di-`trim` sebelum disimpan. String kosong atau hanya spasi ditolak `400`.
- Batas panjang **10.000 karakter** setelah trim; lebih dari itu ditolak `400`.
- Jika teks baru identik dengan yang tersimpan, endpoint tetap `200` tetapi
  **tidak melakukan commit** (menghindari penulisan database yang tidak perlu).
- `full_text` pada GET transkrip dihitung ulang dari segmen, sehingga langsung
  mencerminkan suntingan.
- Tidak ada STT ulang dan tidak ada AI yang menyunting/merangkai ulang kalimat.
- Perubahan bertahan setelah refresh halaman karena tersimpan di SQLite.

## 7. Perilaku nama tampilan speaker

- `speaker_label` (`Speaker 1`, `Speaker 2`, …) bersifat **immutable** — label
  deterministik hasil diarisasi tidak bisa diganti lewat endpoint mana pun.
- `display_name` adalah **nama yang diketik pengguna**, bukan identitas yang
  disimpulkan dari audio. Aplikasi tidak melakukan pengenalan suara personal.
- Nilai `null` dihapus (kembali memakai label anonim). String kosong/spasi
  ditolak `400` — gunakan `null` untuk menghapus.
- Batas panjang **255 karakter**, mengikuti kolom `speakers.display_name`
  yang sudah ada sejak Sprint 5.
- Relasi speaker ↔ segmen tidak berubah: `speaker_id` segmen dan
  `segment_count` pada response tetap sama.
- Frontend menampilkan `display_name` bila ada, jika tidak `speaker_label`.
  Aturan yang sama dipakai di badge segmen, daftar speaker, dan pilihan speaker.
- UI menyediakan **Edit Nama**, **Save**, **Cancel**, dan **Pakai label**,
  dengan pesan sukses/error per baris. Membatalkan edit membersihkan pesan.

## 8. Penugasan speaker manual

- Menerima ID speaker **milik meeting yang sama** atau `null` (`Unassigned`).
- Speaker dari meeting lain dan ID yang tidak dikenal keduanya menghasilkan
  `404` dengan pesan generik yang sama, sehingga tidak membocorkan keberadaan
  speaker lintas meeting.
- Hanya `speaker_id` segmen yang berubah. Teks, timestamp, sequence, dan identitas
  segmen dipertahankan; response langsung memuat label dan nama tampilan speaker.
- Menetapkan speaker pada segmen yang sebelumnya `Speaker ?` didukung, termasuk
  segmen text-only Sprint 4 yang memang tidak punya mapping otomatis.
- Perubahan yang identik dengan data lama tidak di-commit.
- Penugasan gagal (`404`/`500`) tidak mengubah data segmen.

### Automatic vs user-corrected

Aplikasi **tidak menyimpan penanda asal** penugasan. `speaker_id` hanya berarti
"speaker yang sedang dipakai segmen ini", terlepas dari sumbernya. Alasannya ada
di bagian 9. Konsekuensinya:

- diarisasi adalah satu-satunya jalur otomatis; endpoint PATCH adalah satu-satunya
  jalur manual;
- menjalankan ulang diarisasi membangun ulang `Speaker` dari nol, sehingga
  **koreksi manual dan nama tampilan ikut terhapus** — ini perilaku Sprint 5 yang
  sengaja dipertahankan, dan diuji di `test_rerunning_diarization_resets_manual_edits`;
- edit ditolak (`409`) saat transkripsi/diarisasi `PROCESSING` agar koreksi tidak
  ditimpa oleh job yang sedang berjalan.

## 9. Database & keputusan migrasi

**Tidak ada perubahan skema sama sekali di Sprint 6.** Tidak ada tabel baru,
kolom baru, indeks baru, atau perubahan pada `app/database/migrations.py`.

Yang dipakai ulang:

- `transcript_segments.speaker_id` (nullable) → penugasan manual/unassignment;
- `speakers.display_name` (nullable) → nama buatan pengguna;
- `transcript_segments.text` → suntingan teks.

### Mengapa tidak menambah kolom provenance

Opsi yang dipertimbangkan: kolom tambahan seperti
`transcript_segments.speaker_is_manual` atau tabel audit edit.

Keputusan: **tidak ditambahkan**. Alasannya:

1. Tidak ada kebutuhan fungsional dari UI/API saat ini yang menampilkan asal
   penugasan; menambah kolom hanya akan menambah kontrak yang tidak dipakai.
2. Kolom baru menuntut `ALTER TABLE` aditif, response field tambahan, dan
   perubahan pada workflow diarisasi Sprint 5 — risiko regresi lebih besar daripada
   manfaatnya.
3. Sprint 5 sudah menetapkan bahwa menjalankan ulang diarisasi membangun ulang
   speaker. Menyimpan provenance saja tidak mencegah penimpaan tanpa mengubah
   perilaku tersebut.
4. Constraint Sprint 6 meminta perubahan skema hanya dengan alasan dan migrasi
   yang jelas, serta menghindari penulisan database yang tidak perlu.

Sebagai pengaman, `test_no_new_database_columns_for_sprint6` memastikan himpunan
kolom `transcript_segments` dan `speakers` tetap persis seperti baseline.

## 10. Navigasi timestamp audio

- Komponen segmen merender timestamp sebagai **tombol** bila
  `has_timestamps=true` (tombol dinonaktifkan saat job berjalan).
- Klik memanggil `handleSeek(start_seconds)` yang mengubah `currentTime`
  pada **satu elemen `<audio ref>` yang sudah ada**. Atribut `src` tidak diubah,
  sehingga tidak ada unduhan/pemutaran baru dan tidak ada waveform.
- Bila metadata belum siap (`readyState === 0`), seek ditunda lewat listener
  `loadedmetadata` sekali pakai.
- Bila waktu segmen melebihi `duration` yang diketahui, UI menampilkan pesan
  dan tidak mengubah posisi.
- Bila tidak ada rekaman, audio gagal dimuat (`onError`), atau browser menolak
  perubahan `currentTime`, UI menampilkan pesan yang jelas; timestamp tetap bisa
  dibaca.
- Segmen text-only Sprint 4 (`has_timestamps=false`) menampilkan label
  "Tanpa timestamp asli" dan bukan tombol.

## 11. Frontend

- `TranscriptEditor` merender daftar segmen berurutan dan pesan bantuan singkat.
- `TranscriptSegmentItem` menyimpan state edit per segmen: textarea, tombol
  **Edit / Save / Cancel**, validasi lokal (kosong & 10.000 karakter), pemilih
  speaker, dan timestamp yang bisa diklik. Flag `saving` mencegah dobel submit.
- `SpeakerManager` + `SpeakerRow` mengelola daftar speaker: **Edit Nama**,
  input, **Save**, **Cancel**, **Pakai label**, serta feedback sukses/error.
- `api.ts` memakai helper `patchJson<T>()` bersama untuk ketiga endpoint;
  error FastAPI (field `detail`) diterjemahkan ke pesan UI yang sama seperti
  endpoint lain.
- Setelah PATCH berhasil, state lokal diperbarui **dari response server** —
  teks segmen, `full_text`, badge speaker, dan daftar speaker langsung berubah
  tanpa menunggu refresh penuh. Jumlah segmen per speaker disegarkan lewat GET
  diarisasi di latar belakang.
- `types.ts` menambah `speaker_display_name` agar badge memakai prioritas
  nama → label → `Speaker ?`.
- `styles.css` menambah gaya kontrol kecil, select/textarea, dan baris speaker;
  tata letak tetap responsif.

## 12. Penanganan error

| Kondisi | Respons |
| --- | --- |
| Meeting tidak ada | `404` — `Meeting tidak ditemukan.` |
| Segmen tidak ada / bukan milik meeting | `404` — `Segmen transkrip tidak ditemukan pada meeting ini.` |
| Speaker tidak ada / bukan milik meeting | `404` — `Speaker tidak ditemukan pada meeting ini.` |
| Teks kosong/spasi atau > 10.000 karakter | `400` |
| Nama string kosong/spasi atau > 255 karakter | `400` (gunakan `null` untuk menghapus) |
| Job transkripsi/diarisasi `PROCESSING` | `409` |
| Field request tidak dikirim / tipe salah | `422` (validasi FastAPI standar) |
| Transaksi database gagal | `500` dengan pesan generik, `rollback` dilakukan |

Tidak ada pesan error yang memuat detail SQL, path storage, API key, atau
informasi kepemilikan meeting lain.

## 13. Pengujian

`backend/tests/test_sprint6.py` memakai fixture isolasi `s2_db`/`s2_client` dan
provider mock yang disuntik via monkeypatch (sama seperti Sprint 5). Database
produksi dan folder `storage/` tidak disentuh. Cakupan **30 test**:

- edit teks: hanya teks berubah, tersimpan, `full_text` ikut berubah, trim,
  blank/whitespace, panjang berlebih, meeting/segmen tidak ada, segmen lintas
  meeting, no-op tanpa commit, kegagalan commit → 500 generik;
- nama speaker: set/clear `null`, prioritas tampilan badge, label immutable,
  blank/overlong, speaker tidak ada, speaker lintas meeting, relasi segmen
  tetap utuh;
- penugasan: speaker lain satu meeting, unassign, segmen yang sebelumnya
  unassigned, speaker tidak ada/lintas meeting, segmen/meeting tidak ada,
  kegagalan commit → 500 generik, persist setelah fetch ulang;
- integritas: edit ditolak saat transkripsi/diarisasi `PROCESSING`, diarisasi
  ulang mereset koreksi manual (batasan yang didokumentasikan), endpoint baca
  Sprint 5 dan DELETE transkrip tidak berubah, skema kolom persis baseline,
  service tetap terpisah.

Hasil akhir:

- `python -m pytest -q` → **125 passed, 1 warning** (Sprint 1–6; warning hanya
  deprecation Starlette/anyio);
- `npm run build` → **sukses**, 41 modules transformed, `built in 1.43s`.

Belum ada test frontend otomatis karena infrastruktur belum ada; type-check
TypeScript + build produksi dipakai sebagai gerbang kualitas.

## 14. Keterbatasan

- Tidak ada penanda "manual vs otomatis" di database, tidak ada riwayat edit,
  undo, atau diff antarversi teks.
- Menjalankan ulang diarisasi menghapus nama tampilan dan menimpa penugasan
  manual (perilaku Sprint 5 yang dipertahankan).
- Edit per segmen dan per speaker dilakukan satu per satu; belum ada edit massal.
- Nama tampilan bukan verifikasi identitas; pengguna bertanggung jawab atas
  nama yang dimasukkan.
- STT cloud dan diarisasi Deepgram belum diverifikasi live; test otomatis
  memakai provider mock `[MOCK]`.
- Background task masih in-process, hilang saat restart, dan tidak cocok untuk
  multi-worker.
- Belum ada autentikasi/otorisasi, kolaborasi, PostgreSQL, summarization AI,
  action items, atau deployment produksi.
- Rekaman, transkripsi, dan diarisasi wajib dilakukan dengan sepengetahuan dan
  persetujuan peserta; aplikasi hanya mengingatkan, bukan menjamin kepatuhan.

## 15. Pengujian manual (disarankan)

1. Jalankan backend dengan `STT_PROVIDER=mock` dan `DIARIZATION_PROVIDER=mock`,
   lalu frontend dengan `npm run dev`.
2. Buat meeting, unggah/rekam audio, klik **Transcribe**, tunggu selesai, lalu
   klik **Diarize Speakers**.
3. Pada segmen: klik timestamp → pemutar harus melompat tanpa load ulang;
   klik **Edit**, ubah teks, **Save**, lalu refresh halaman → teks tetap.
4. Coba teks kosong dan teks sangat panjang → muncul pesan validasi, data lama
   tidak berubah.
5. Di bagian Diarisasi, klik **Edit Nama** pada `Speaker 1`, simpan "Rani" →
   badge segmen dan daftar speaker menampilkan "Rani"; klik **Pakai label** →
   kembali ke `Speaker 1`.
6. Pada pemilih speaker segmen, pilih speaker lain dan `Unassigned` → badge
   langsung berubah; refresh halaman → tetap.
7. Hapus rekaman sementara atau matikan server saat seek → pesan "Pemutar audio
   tidak tersedia" muncul, tidak ada exception di console.
8. Ulangi diarisasi setelah memberi nama → nama dan koreksi manual hilang
   sesuai batasan bagian 14.
