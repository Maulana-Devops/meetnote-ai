# Sprint 8 — Action Items Management

Sprint 8 menambah kemampuan mengekstrak dan mengelola **action items** hanya dari
transkrip rapat yang sudah tersimpan. Tidak ada provider AI baru, tidak ada
SDK/dependency baru, tidak ada perubahan kontrak STT/diarisasi/Sprint 1–7, dan
tidak ada commit/push Git. Semua perubahan bersifat aditif.

---

## 1. Audit baseline sebelum implementasi

Implementasi diawali dengan membaca implementasi aktual (bukan asumsi) pada:

- `README.md`, `docs/ARCHITECTURE.md`, `docs/README.md`, `docs/SPRINT1.md` …
  `docs/SPRINT7.md`;
- model: `meeting.py`, `transcript.py`, `diarization.py`, `summary.py`,
  `audio_asset.py`, serta `models/__init__.py`;
- skema Pydantic dan router `app/api/v1/*` (terutama `summaries.py`);
- workflow `services/summary/workflow.py`, `services/transcription.py`,
  `services/diarization/workflow.py`;
- lapisan LLM `services/llm/base.py`, `errors.py`, `registry.py`, `mock.py`,
  `openai_provider.py`;
- migrasi `app/database/migrations.py` dan `session.py`;
- frontend `MeetingDetail.tsx`, `api.ts`, `types.ts`, `styles.css`,
  `StatusBadge.tsx`;
- konfigurasi `core/config.py`, `main.py`, serta conftest test.

Temuan audit yang menentukan desain:

1. Sprint 7 sudah punya abstraksi LLM yang benar: `LlmProvider`, registry,
   `MockLlmProvider`, `OpenAiLlmProvider` dengan Structured Outputs
   `json_schema` strict, dan error bertipe (`LlmError`). Sprint 8 **memperpanjang**
   lapisan ini, bukan membuat provider baru.
2. `SummaryJob` memakai status `NOT_STARTED/PROCESSING/COMPLETED/FAILED`, job
   disimpan satu per meeting, task berjalan via `BackgroundTasks` dengan
   `SessionLocal()` sendiri. Ini pola yang dipakai ulang.
3. `renderSourceRef()` dan `handleSeek()` di `MeetingDetail.tsx` sudah memakai
   satu `<audio ref>`. Sprint 8 cukup memakai ulang keduanya.
4. `clear_transcription()` sudah membersihkan diarisasi dan ringkasan secara
   lokal-import untuk menghindari siklus modul; Sprint 8 mengikuti pola sama.
5. Baseline terverifikasi: backend `152 passed, 1 warning`, frontend
   `npm run build` sukses. Warning adalah `DeprecationWarning` anyio/Starlette
   yang sudah ada sejak Sprint 7.

---

## 2. Daftar file yang diubah / ditambah

**Backend — baru**

- `app/models/action_item.py` — `ActionItem`, `ActionItemSource`,
  `ActionItemJob`, konstanta status.
- `app/schemas/action_item.py` — `ActionItemRead`, `ActionItemListRead`,
  `ActionItemUpdate`, `ActionItemSpeakerOption`.
- `app/services/action_items/__init__.py`
- `app/services/action_items/workflow.py` — persiapan, background run,
  validasi, penyimpanan, regenerasi aman, edit, delete, recovery.
- `app/api/v1/action_items.py` — router REST Sprint 8.
- `tests/test_sprint8.py` — 43 test mock-only.

**Backend — dimodifikasi (aditif)**

- `app/services/llm/base.py` — `ACTION_ITEMS_FORMAT_NAME`, `ActionItemInput`,
  `ExtractedActionItem`, `ActionItemExtractionResult`,
  `ACTION_ITEMS_SYSTEM_PROMPT`, `ACTION_ITEMS_JSON_SCHEMA`,
  `format_action_items_input()`, `parse_action_items_payload()`, method
  `extract_action_items()` pada protocol `LlmProvider`.
- `app/services/llm/errors.py` — docstring diperluas untuk action items.
- `app/services/llm/mock.py` — opsi `action_result`/`action_payload`/
  `action_error` dan implementasi `extract_action_items()`.
- `app/services/llm/openai_provider.py` — satu jalur `_request_json()` untuk
  kedua schema + `extract_action_items()`; model diambil dari response bila ada.
- `app/models/__init__.py`, `app/models/meeting.py` — ekspor & relasi.
- `app/schemas/__init__.py` — ekspor skema.
- `app/api/v1/router.py` — daftarkan router action items.
- `app/main.py` — panggil `recover_stuck_action_items()` saat startup.
- `app/services/transcription.py` — `clear_transcription()` juga membersihkan
  action items.

**Frontend — dimodifikasi**

- `src/types.ts` — tipe `ActionItem`, `ActionItemListDetail`, status, source ref,
  opsi speaker, `ActionItemUpdate`.
- `src/api.ts` — `startActionItems`, `fetchActionItems`, `deleteActionItems`,
  `updateActionItem`, `deleteActionItem`.
- `src/components/MeetingDetail.tsx` — bagian **Action Items** lengkap.
- `src/styles.css` — styling daftar/form action item.

**Dokumentasi**

- `docs/SPRINT8.md` (file ini), `README.md`, `docs/ARCHITECTURE.md`,
  `docs/README.md`.

---

## 3. Database & migrasi

Tiga tabel baru dibuat otomatis lewat `Base.metadata.create_all` pada startup:

| Tabel | Isi |
|---|---|
| `action_items` | satu baris per item: `title`, `description`, `assignee_speaker_id` (nullable FK `speakers.id`), `assignee_text`, `deadline_text`, `due_date`, `status`, `start_seconds`, `end_seconds`, `provider`, `model`, `is_mock`, `is_manually_edited`, timestamp, FK `meeting_id` |
| `action_item_sources` | PK komposit `(action_item_id, segment_id)`, `sequence`; FK sungguhan ke `action_items.id` dan `transcript_segments.id` |
| `action_item_jobs` | satu baris per meeting: `status`, `provider`, `model`, `error`, timestamp, FK unik `meeting_id` |

Sifat migrasi:

- **Tidak ada** `DROP TABLE`, `ALTER TABLE ... DROP`, atau recreate tabel lama.
- `apply_additive_migrations()` tidak diubah; masih hanya menambah
  `transcript_segments.speaker_id` + index secara idempoten.
- Tidak ada kolom baru di `meetings`, `meeting_summaries`, `transcript_segments`,
  `speakers`, atau tabel STT/diarisasi.
- `test_additive_schema_keeps_old_tables` mengunci keberadaan seluruh tabel lama
  dan ketiadaan kolom action item di `meeting_summaries`.

---

## 4. Struktur data & kontrak

Field konseptual action item:

- identitas: `id`, `meeting_id`;
- konten: `title`, `description`;
- penanggung jawab: `assignee_speaker_id` **atau** `assignee_text` (keduanya
  nullable; keduanya boleh null);
- deadline: `deadline_text` (frasa asli) dan/atau `due_date` (tanggal eksplisit
  `YYYY-MM-DD`);
- sumber wajib: `segment_ids[]`, `start_seconds`, `end_seconds`;
- status item: `OPEN` / `COMPLETED` / `CANCELLED`;
- status job: `NOT_STARTED` / `PROCESSING` / `COMPLETED` / `FAILED`;
- provenance aman: `provider`, `model`, `is_mock`, `is_manually_edited`,
  `created_at`, `updated_at`.

Status job dan status item sengaja dipisah: `ActionItemJob` mengikuti konvensi
Sprint 4/5/7, sedangkan status item adalah status bisnis yang diubah pengguna.

---

## 5. Workflow LLM & Structured Outputs

Alur `POST /api/v1/meetings/{id}/action-items`:

1. `prepare_action_items()` (di request thread):
   - cek meeting ada (`404`);
   - cek duplikat job `PROCESSING` (`409`);
   - cek tidak ada STT/diarisasi `PROCESSING` (`409`);
   - cek transkrip `COMPLETED` dan segmen tidak kosong (`409`);
   - validasi konfigurasi provider (`503` bila belum diisi);
   - render prompt dan cek `LLM_MAX_INPUT_CHARACTERS` (`422`);
   - buat/perbarui `ActionItemJob` menjadi `PROCESSING`, commit.
2. Endpoint mengembalikan `202 Accepted`, lalu menjadwalkan
   `run_action_items()` lewat `BackgroundTasks`.
3. Task membuka `SessionLocal()` sendiri:
   - memuat ulang meeting, job, segmen, speaker;
   - memanggil provider LLM yang sama dengan ringkasan namun dengan schema
     `action_items`;
   - memvalidasi respons, lalu menulis dalam satu transaksi;
   - status job `COMPLETED` atau `FAILED`, error aman disimpan di `job.error`.

Detail provider:

- Satu endpoint `POST {LLM_API_BASE_URL}/responses`, header
  `Authorization: Bearer ...`, dan
  `text.format={type:"json_schema", name:"action_items", schema:..., strict:true}`.
- Kode HTTP untuk ringkasan dan action items kini lewat satu helper
  `_request_json()`; tidak ada SDK atau dependency baru.
- Backend tetap mem-parsing `output_text`, menolak refusal, `incomplete`,
  non-JSON, field asing, dan error HTTP/timeout sebagai `LlmError`.
- Model pada hasil diambil dari field `model` respons bila tersedia; jika tidak,
  jatuh ke `settings.LLM_MODEL` (kompatibel dengan test Sprint 7).

Prompt eksplisit melarang: mengarang tugas dari ide/saran, memilih pembicara
hanya karena ia mengucapkan kalimat, menerjemahkan bebas frasa deadline,
mengasumsikan tanggal dari waktu server, dan memakai pengetahuan luar.

Array `action_items: []` adalah hasil **valid**: job `COMPLETED` tanpa item.

---

## 6. Validasi referensi sumber

Validasi berlapis (semua terjadi sebelum penulisan):

1. **Parser provider** (`parse_action_items_payload`): top-level harus objek
   dengan tepat `action_items` array; tiap item harus memiliki tepat sembilan field
   yang diizinkan; `title` non-kosong; `segment_ids` minimal satu; timestamp
   finite, non-negatif, `end >= start`; `due_date` `YYYY-MM-DD` atau `null`;
   string opsional kosong dinormalisasi jadi `null`.
2. **Workflow** (`_validate_result`):
   - setiap `segment_id` harus ada di segmen meeting yang sama — referensi
     lintas meeting ditolak;
   - duplikat `segment_id` dalam satu item ditolak;
   - waktu dilaporkan dibandingkan dengan `min(start)` / `max(end)` segmen
     nyata dengan toleransi 0,5 detik;
   - waktu yang lolos **diganti dengan nilai database**, bukan dipercaya dari AI;
   - `assignee_speaker_label` harus persis cocok dengan label speaker milik
     meeting; label duplikat/ambig dihapus dari pemetaan sehingga tidak bisa
     dipilih; label tidak dikenal ditolak.
3. Kegagalan apa pun → `LlmInvalidResultError`, job `FAILED`, **tidak ada item
   yang disimpan**. Data lama tidak berubah.

Frontend hanya menerima `segment_ids`, `start_seconds`, `end_seconds` dari
backend; tombol waktu memanggil `handleSeek()` pada `<audio ref>` yang sama.

---

## 7. API

| Method | Path | Status | Catatan |
|---|---|---|---|
| POST | `/api/v1/meetings/{id}/action-items` | 202 | generate / retry / regenerate |
| GET | `/api/v1/meetings/{id}/action-items` | 200 | status + items + opsi speaker |
| DELETE | `/api/v1/meetings/{id}/action-items` | 200 | hapus semua item + job |
| PATCH | `/api/v1/meetings/{id}/action-items/{item_id}` | 200 | edit field/status |
| DELETE | `/api/v1/meetings/{id}/action-items/{item_id}` | 200 | hapus satu item |

Kode error konsisten: `404` meeting/item tidak ditemukan (termasuk lintas
meeting), `409` duplikat job / job aktif / transkrip belum ada / STT atau
diarisasi masih jalan, `422` field invalid atau field asing / speaker lintas
meeting / transkrip terlalu panjang, `503` provider belum terkonfigurasi. Error
provider pada background task disimpan di `job.error`, bukan dibocorkan mentah.

GET aman dipanggil berulang untuk polling dan mengembalikan array `items`
kosong bila belum ada hasil. Item/speaker dari meeting lain selalu tampak
sebagai `404`/`422`, tidak pernah ikut tersimpan.

---

## 8. Frontend

Bagian **Action Items** ditambahkan di `MeetingDetail.tsx` setelah AI Summary:

- tombol **Generate Action Items** / **Regenerate Action Items**, **↻ Refresh**,
  dan **Hapus Semua Action Items** dengan konfirmasi;
- polling otomatis setiap 1,5 detik (maksimal 80 kali) selama status
  `PROCESSING`;
- ringkasan metadata: status ekstraksi, provider, model, jumlah item;
- peringatan `[MOCK]` bila hasil berasal dari provider simulasi;
- tiap item menampilkan judul, deskripsi, penanggung jawab (label speaker atau
  teks eksplisit), frasa deadline + tanggal, status, penanda `✎ diedit manual`,
  dan tombol waktu sumber;
- tombol **Edit**, **✓ Selesai**, **Batalkan**, **Buka lagi**, **Hapus**;
- form edit: judul, deskripsi, pilihan speaker meeting ini, teks penanggung
  jawab, frasa deadline, tanggal, status;
- `handleSeek()` dan `<audio ref>` yang sudah ada dipakai ulang — **tidak ada**
  elemen audio baru dan tidak ada unduhan ulang.

Tidak ada dependencies frontend baru; build dan type-check lolos.

---

## 9. Aturan perubahan manual & regenerasi

- POST tidak pernah menghapus item lebih awal. Semua validasi selesai sebelum
  transaksi penulisan dimulai.
- Saat regenerasi berhasil, **hanya item AI yang belum pernah disunting**
  (`is_manually_edited=false`) yang dihapus dan diganti hasil baru.
- Item dengan `is_manually_edited=true` dipertahankan apa adanya (id, judul,
  status, dan referensinya tidak berubah).
- PATCH apa pun — termasuk perubahan status saja — menandai item sebagai
  `is_manually_edited=true`.
- Hapus satu item bersifat permanen untuk item itu; regenerate berikutnya tidak
  mengembalikannya secara otomatis (model dapat mengekstrak ulang dari transkrip
  bila memang ada).
- Regenerasi gagal → job `FAILED`, seluruh item lama masih tampil.
- DELETE semua menghapus item + source + job, tetapi transkrip, speaker, dan
  audio tidak tersentuh.

---

## 10. Pengujian backend

`backend\tests\test_sprint8.py`: **43 test**, semuanya memakai provider mock dan
database/storage isolasi (`s2_db`, `s2_client`). Tidak ada panggilan cloud.

Cakupan:

- ekstraksi valid + persistensi, hasil kosong valid, null assignee/deadline;
- deadline tekstual vs `due_date`, format tanggal invalid ditolak;
- pemetaan speaker valid dan label speaker invalid ditolak;
- `assignee_text` tanpa mapping;
- referensi segmen lintas meeting, referensi kosong, timestamp mismatch,
  normalisasi waktu dari database;
- JSON invalid, field asing, error provider (timeout/generic);
- kontrak OpenAI action items: URL, Bearer header, schema `action_items`,
  `strict=true`, tidak ada secret di response;
- edit judul/deskripsi/speaker/assignee/deadline/tanggal, clear field,
  semua status, status invalid, field asing;
- speaker dan item lintas meeting ditolak;
- hapus satu / hapus semua;
- conflict tanpa transkrip, STT/diarisasi aktif, duplikat job, delete saat job
  aktif;
- restart recovery;
- regenerasi aman + kegagalan regenerasi menjaga item lama;
- hapus transkrip membersihkan action items;
- ringkasan dan action items hidup berdampingan; skema aditif.

Hasil: `43 passed, 1 warning` untuk file Sprint 8 dan
**195 passed, 1 warning** untuk seluruh suite.

---

## 11. Frontend build & type-check

Perintah: `npm run build` (`tsc -b && vite build`) di `frontend`.

Hasil terakhir: sukses, 41 modules transformed, `✓ built in 1.26s`. Tidak ada
error TypeScript. Tidak ada test frontend baru; verifikasi UI diserahkan ke
pengujian manual di bawah.

---

## 12. Regresi Sprint 1–7

Seluruh test Sprint 1–7 tetap dijalankan tanpa perubahan semantik:

- 152 test baseline tetap lolos (total kini 195);
- test kontrak OpenAI Sprint 7 masih lolos meski `_request_json()` kini dipakai
  bersama — nama format `meeting_summary`, schema lama, dan model dari response
  dipertahankan;
- test `test_summary_tables_are_additive` dan test skema Sprint 6 tetap lolos;
- ringkasan dan action items dapat dibuat pada meeting yang sama dan saling
  independen saat dihapus;
- chord STT/diarisasi, edit transkrip, dan speaker manager tidak diubah.

---

## 13. Cloud vs mock

- **Mock (`LLM_PROVIDER=mock`)**: hasil ditandai `[MOCK]`, `provider="mock"`,
  `model="mock-1"`, `is_mock=true`. UI menampilkan peringatan. Dipakai untuk
  seluruh test otomatis dan pengembangan lokal.
- **Cloud (`LLM_PROVIDER=openai`)**: kontrak Responses API + Structured
  Outputs diimplementasikan per dokumentasi resmi yang diperiksa 23 Nov 2026,
  tetapi **belum diuji live** karena tidak ada `LLM_API_KEY` di lingkungan ini.
- Tidak ada klaim keberhasilan cloud. Kredensial, prompt, header Authorization,
  dan response mentah providers tidak pernah dikirim ke endpoint `/config`,
  disimpan di DB, atau ditampilkan di UI. Hanya `llm_provider`,
  `llm_configured`, `provider`, `model`, dan `is_mock` yang diekspos.

---

## 14. Batasan

- Ekstraksi bergantung pada kualitas transkrip dan model; validasi backend
  menjamin referensi valid, bukan interpretasi semantik yang sempurna.
- Tidak ada inferensi tugas dari komitmen implisit; bila model tetap
  menyertakannya, pengguna harus menghapusnya manual.
- `due_date` hanya diisi untuk tanggal eksplisit tidak ambigu; "besok" tetap
  menjadi `deadline_text` dengan `due_date=null`.
- Tidak ada riwayat edit penuh, undo, edit massal, pengingat, email, kalender,
  ekspor PDF, autentikasi, atau multi-user.
- Seluruh transkrip dikirim sekali jalan dan dibatasi
  `LLM_MAX_INPUT_CHARACTERS`; belum ada chunking/map-reduce.
- Background task bersifat in-process; setelah restart job `PROCESSING` ditandai
  `FAILED` dan harus dicoba ulang.
- Tidak ada pencocokan/merge semantik antar versi saat regenerasi; item manual
  dipertahankan apa adanya.

---

## 15. Panduan pengujian manual

1. Pastikan backend & frontend berjalan. Untuk mencoba tanpa API key, set
   `STT_PROVIDER=mock`, `DIARIZATION_PROVIDER=mock`, `LLM_PROVIDER=mock`.
2. Buat meeting, unggah/rekam audio, jalankan transkripsi sampai `COMPLETED`.
3. Buka detail meeting → bagian **Action Items** → klik **Generate Action
   Items**. Perhatikan status `PROCESSING` berubah otomatis menjadi
   `COMPLETED`; pesan `[MOCK]` harus muncul.
4. Klik tombol waktu pada sebuah item — audio harus seek ke segmen sumber pada
   player yang sama (tidak ada player kedua).
5. Klik **Edit**, ubah judul/deskripsi/penanggung jawab/deadline/status, lalu
   **Simpan**. Perhatikan penanda `✎ diedit manual`.
6. Klik **✓ Selesai**, **Batalkan**, **Buka lagi**; status harus berubah dan
   item tetap ditandai diedit manual.
7. Klik **Regenerate Action Items**. Item yang diedit manual harus tetap ada
   dengan isi sama; item AI lama boleh diganti.
8. Uji kegagalan dengan sengaja mematikan koneksi/menghapus API key lalu
   regenerate: job harus `FAILED`, item lama tetap tampil.
9. Klik **Hapus** pada satu item, lalu **Hapus Semua Action Items**; pastikan
   transkrip, speaker, dan audio masih ada.
10. Hapus transkripsi: action items harus ikut hilang; ringkasan juga hilang
    (perilaku Sprint 7), audio tetap ada.
11. Buka meeting lain dan coba PATCH/DELETE memakai item id dari meeting
    pertama — harus `404`/`422`.
12. Restart backend saat job `PROCESSING`: setelah hidup kembali, status harus
    `FAILED` dengan pesan bahwa proses terhenti karena aplikasi dimulai ulang.
