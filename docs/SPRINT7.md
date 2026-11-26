# Sprint 7 — AI Summarization

Dokumen ini merangkum implementasi ringkasan AI untuk rapat yang **hanya**
menggunakan transkrip yang sudah tersimpan. Sprint 7 tidak mengubah kontrak
Sprint 1–6 dan tidak menambah dependency baru.

## 1. Audit & baseline

Sebelum implementasi:

- backend: `125 passed, 1 warning` (warning deprecation Starlette/anyio);
- frontend: `npm run build` sukses;
- Sprint 1–3: meeting, audio, storage, playback;
- Sprint 4: transkripsi + `TranscriptSegment`, `TranscriptionJob`, provider STT;
- Sprint 5: diarisasi + `Speaker`, `DiarizationJob`, provider Deepgram;
- Sprint 6: edit teks segmen, nama tampilan speaker, penugasan speaker, seek audio;
- tidak ada kolom provenance Sprint 6 — `speaker_display_name` dan
  `speaker_label` sudah cukup untuk input LLM;
- tidak ada commit/push; seluruh perubahan Sprint 7 tetap uncommitted.

Kontrak OpenAI diperiksa dari dokumentasi resmi Structured Outputs dan OpenAPI
spesifikasi (23 Nov 2026): `POST {base}/responses` dengan
`text.format.type="json_schema"`, `name`, `schema`, dan `strict=true`. Aplikasi
tetap harus menangani refusal, incomplete response, HTTP error, dan aturan
bisnis sendiri.

## 2. Daftar file

**Baru — backend**

- `app/services/llm/__init__.py`
- `app/services/llm/base.py`
- `app/services/llm/errors.py`
- `app/services/llm/registry.py`
- `app/services/llm/mock.py`
- `app/services/llm/openai_provider.py`
- `app/services/summary/__init__.py`
- `app/services/summary/workflow.py`
- `app/models/summary.py`
- `app/schemas/summary.py`
- `app/api/v1/summaries.py`
- `tests/test_sprint7.py`

**Diubah — backend**

- `app/core/config.py` — pengaturan `LLM_*`.
- `app/models/__init__.py`, `app/models/meeting.py` — model + relasi baru.
- `app/schemas/__init__.py`, `app/schemas/config.py` — skema ringkasan + info
  provider LLM publik.
- `app/api/v1/config.py`, `app/api/v1/router.py` — endpoint config + router.
- `app/main.py` — `recover_stuck_summaries()` di lifespan.
- `app/services/transcription.py` — `clear_transcription()` ikut memanggil
  `clear_summary()`.
- `tests/conftest.py` — default env `LLM_PROVIDER=mock` untuk isolasi test.
- `.env.example` (root dan `backend/`) — contoh variabel `LLM_*`.

**Frontend**

- `src/types.ts` — `SummaryDetail`, `SummaryTopic`, `SummaryDecision`,
  `SummarySourceRef`, `SummaryStatus`, field LLM di `AppConfig`.
- `src/api.ts` — `startSummary`, `fetchSummary`, `deleteSummary`.
- `src/components/MeetingDetail.tsx` — section **AI Summary**, polling, refresh,
  regenerate, delete + confirm, source ref yang memakai `handleSeek`.
- `src/styles.css` — styling ringkasan dan tombol sumber.

**Dokumentasi**

- `docs/SPRINT7.md` (dokumen ini), `docs/README.md`, `docs/ARCHITECTURE.md`,
  `README.md`.

## 3. Arsitektur provider LLM

Provider mengikuti pola yang sama dengan STT/diarisasi:

```text
services/llm/
├── base.py             # protocol LlmProvider + dataclass + prompt + JSON schema
├── errors.py           # LlmError dan subclass + http_status aman
├── registry.py         # create_provider() / is_llm_configured()
├── mock.py             # MockLlmProvider ([MOCK], is_mock=True)
└── openai_provider.py  # OpenAiLlmProvider (httpx → /responses)
```

Antarmuka minimal:

```python
class LlmProvider(Protocol):
    name: str
    @property
    def model(self) -> str: ...
    def validate_configuration(self) -> None: ...
    def summarize(self, data: SummaryInput) -> SummaryResult: ...
```

`SummaryInput` memuat judul meeting, daftar `SummaryInputSegment` (id, teks,
waktu, speaker display name), dan bahasa output opsional. `SummaryResult` memuat
`overview`, `topics`, `decisions`, `provider`, `model`, dan `is_mock`.

Workflow menyimpan seam `workflow._create_provider = create_provider` sehingga
test dapat menyuntik provider seperti pola `_create_provider` Sprint 4/5.

### Kontrak OpenAI

Request:

```http
POST {LLM_API_BASE_URL}/responses
Authorization: Bearer <LLM_API_KEY>
Content-Type: application/json
```

```json
{
  "model": "...",
  "input": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "meeting_summary",
      "schema": { "...": "..." },
      "strict": true
    }
  }
}
```

Respons dibaca dari `output[].content[].type == "output_text"` (fallback
`output_text`). Sebelum dipakai, backend memeriksa status refusal/incomplete,
JSON parse, struktur field, dan aturan bisnis. Tidak ada prompt-only JSON trust.

## 4. Konfigurasi environment

| Variable | Default | Keterangan |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai` atau `mock` |
| `LLM_API_KEY` | kosong | `SecretStr`, backend saja, jangan pakai `VITE_` |
| `LLM_API_BASE_URL` | `https://api.openai.com/v1` | endpoint Responses ditambah `/responses` |
| `LLM_MODEL` | `gpt-4o-mini-2024-08-06` | model dengan Structured Outputs |
| `LLM_OUTPUT_LANGUAGE` | kosong | kosong = ikuti bahasa transkrip |
| `LLM_TIMEOUT_SECONDS` | `90` | timeout httpx |
| `LLM_MAX_INPUT_CHARACTERS` | `24000` | batas prompt akhir, bukan batas file audio |

`GET /api/v1/config` hanya mengembalikan `llm_provider` dan `llm_configured`.
API key, Authorization header, prompt mentah, dan response mentah tidak pernah
muncul di frontend, config endpoint, log, atau pesan error.

## 5. Database & migrasi

Dua tabel baru, keduanya additif dan dibuat oleh `create_all`:

### `meeting_summaries`

`id`, `meeting_id` (FK unik), `overview`, `topics` (JSON), `decisions` (JSON),
`provider`, `model`, `is_mock`, `created_at`, `updated_at`.

### `summary_jobs`

`id`, `meeting_id` (FK unik), `status`, `provider`, `model`, `error`,
`created_at`, `updated_at`.

Status: `NOT_STARTED`, `PROCESSING`, `COMPLETED`, `FAILED`.

Tidak ada `DROP TABLE`, `recreate`, atau perubahan pada `audio_assets`,
`transcript_segments`, `speakers`, `transcription_jobs`, dan `diarization_jobs`.
`apply_additive_migrations()` tidak diubah. Tidak ada kolom action item,
assignee, atau deadline.

## 6. Endpoint API

| Method | Path | Respons |
| --- | --- | --- |
| `POST` | `/api/v1/meetings/{id}/summary` | `202` + status `PROCESSING`/final |
| `GET` | `/api/v1/meetings/{id}/summary` | `200` + status/ringkasan terakhir |
| `DELETE` | `/api/v1/meetings/{id}/summary` | `200` + jumlah baris terhapus |

- `POST` dipakai untuk generate, retry setelah `FAILED`, dan regenerate setelah
  `COMPLETED`. Ringkasan lama tidak dihapus lebih dulu.
- `404`: meeting tidak ada.
- `409`: meeting belum punya transkrip selesai, job ringkasan ganda, hapus saat
  proses, atau STT/diarisasi masih `PROCESSING`.
- `422`: prompt melebihi `LLM_MAX_INPUT_CHARACTERS`.
- `503`: konfigurasi provider belum valid.
- `502`/`504`: kegagalan/timeout provider saat background; dibaca lewat `error`
  pada `GET`.

## 7. Workflow

1. `prepare_summary()` memvalidasi meeting, ketiadaan job STT/diarisasi aktif,
   transkrip `COMPLETED` + segmen ada, konfigurasi provider, batas karakter, dan
   duplikat job.
2. Job `PROCESSING` dibuat/diset; ringkasan lama sengaja dipertahankan.
3. Endpoint menjadwalkan `run_summary(meeting_id)` lewat `BackgroundTasks` dan
   mengembalikan `202`.
4. `run_summary()` membuka `SessionLocal()` sendiri, mengambil segmen terurut,
   menyusun prompt, memanggil provider, dan mem-parsing hasil.
5. `_validate_references()` memastikan tiap `segment_ids` ada di meeting yang
   sama, tidak duplikat, dan waktu cocok (toleransi 0,5 detik). Waktu yang
   disimpan selalu berasal dari database.
6. Hanya setelah valid, `MeetingSummary` ditulis dan job `COMPLETED`.
7. Kegagalan apa pun hanya mengubah job jadi `FAILED` lewat sesi baru
   (`_mark_failed()`); audio, transkrip, speaker, dan ringkasan lama aman.
8. `recover_stuck_summaries()` dipanggil saat startup untuk menandai job
   `PROCESSING` yang tertinggal setelah restart sebagai `FAILED`.
9. `clear_transcription()` memanggil `clear_summary()` agar referensi tidak
   menggantung saat transkrip dihapus.

## 8. Struktur output

```json
{
  "overview": "1–3 kalimat ringkas dari transkrip.",
  "topics": [
    {
      "title": "Topik",
      "detail": "Ringkasan singkat.",
      "segment_ids": ["...uuid..."],
      "start_seconds": 0.0,
      "end_seconds": 2.0
    }
  ],
  "decisions": [
    {
      "text": "Keputusan eksplisit.",
      "segment_ids": ["...uuid..."],
      "start_seconds": 2.0,
      "end_seconds": 4.0
    }
  ]
}
```

Aturan konten:

- hanya fakta dari transkrip; tanpa pengetahuan umum/rekaan;
- tanpa identitas, jabatan, assignee, atau deadline dunia nyata;
- speaker memakai `display_name` bila ada, else `speaker_label`;
- proposal/diskusi tidak diubah menjadi keputusan;
- tidak ada keputusan eksplisit → `decisions: []`;
- bahasa mengikuti transkrip kecuali `LLM_OUTPUT_LANGUAGE` diisi;
- tidak ada field action item/assignee/deadline dalam schema maupun UI.

## 9. Frontend

Bagian **AI Summary** pada `MeetingDetail.tsx` menyediakan:

- tombol **Generate Summary** / **Regenerate Summary** dan **↻ Refresh**;
- **Hapus Ringkasan** dengan `window.confirm`;
- status badge, provider, model, jumlah topik/keputusan, error, dan notice;
- peringatan `[MOCK]` bila `is_mock=true`;
- tampilan **Overview**, **Topics**, **Decisions** beserta daftar kosong yang
  jelas;
- tombol waktu `▶ m:ss` pada setiap topik/keputusan yang memanggil
  `handleSeek(start_seconds)`. Ini memakai satu `<audio ref>` yang sama dengan
  transkrip — tidak ada elemen audio kedua dan tidak ada request unduhan baru;
- polling 1,5 detik maksimal 80 kali selama `PROCESSING`.

Safe provider/model info berasal dari ringkasan yang disimpan, bukan dari API key.

## 10. Test backend

`tests/test_sprint7.py` menambah 27 test dengan provider mock, DB/storage isolasi,
dan HTTP client palsu. Cakupan:

- sukses + persist setelah refresh;
- penggunaan `display_name` dan fallback `Speaker N`;
- normalisasi waktu dari database;
- `decisions: []`;
- regenerasi gagal mempertahankan ringkasan lama, lalu retry sukses;
- duplikat `PROCESSING` (`409`);
- konflik saat STT/diarisasi berjalan (`409`);
- meeting tidak ada (`404`) dan transkrip belum ada (`409`);
- transkrip terlalu panjang (`422`);
- referensi segmen asing / waktu salah / field `decisions` hilang → `FAILED`,
  tidak disimpan;
- error auth, timeout, rate limit, provider generik;
- provider tidak dikenal → `503`, job tidak dibuat;
- delete ringkasan + delete transkrip membersihkan data terkait;
- restart recovery;
- tabel aditif dan ketiadaan kolom action item;
- config endpoint menyembunyikan secret;
- request strict JSON schema + mapping error/refusal OpenAI tanpa secret.

Hasil: **152 passed, 1 warning** untuk seluruh backend.

## 11. Frontend build & type-check

```powershell
cd frontend
npm run build
```

`tsc -b && vite build` sukses. Tidak ada infrastruktur test frontend otomatis;
quality gate tetap type-check + production build.

## 12. Regresi Sprint 1–6

Seluruh 125 test lama tetap lolos tanpa perubahan kontrak STT/diarisasi/edit.
Pemeriksaan khusus:

- endpoint upload/playback/delete rekaman tidak berubah;
- status `UPLOADED → TRANSCRIBING → TRANSCRIBED` tidak berubah;
- diarisasi tetap anonim dan `speaker_label` immutable;
- PATCH Sprint 6 tetap menulis kolom lama;
- seek transkrip dan seek ringkasan memakai `audioRef` yang sama;
- `conftest.py` hanya menambah default `LLM_*` untuk isolasi test.

## 13. Status cloud vs mock

- **Mock:** seluruh alur Sprint 7 terverifikasi otomatis dengan `[MOCK]` dan
  `is_mock=true`.
- **OpenAI:** kontrak `/responses` + strict `json_schema` diimplementasikan dan
  diuji dengan response/HTTP client palsu. **Belum diuji live** karena tidak ada
  API key saat pengembangan. Jangan mengklaim keberhasilan cloud.
- STT OpenAI dan Deepgram juga tetap mock-only dalam test otomatis, seperti
  Sprint 4/5.

Untuk mencoba mock: set `LLM_PROVIDER=mock` di `backend/.env`, lalu restart
backend. Untuk cloud: isi `LLM_API_KEY`, pastikan model mendukung Structured
Outputs, dan jangan pernah menaruh key di `frontend/.env`.

## 14. Keterbatasan

- Ringkasan dibuat dalam satu request; bila melebihi
  `LLM_MAX_INPUT_CHARACTERS`, user mendapat `422` (belum ada chunking).
- Tidak ada action item, assignee, deadline, ekspor PDF, auth/multi-user,
  Celery/Redis, microservice, local LLM, atau penyimpanan riwayat versi.
- Background task in-process; restart membuat job `PROCESSING` jadi `FAILED`.
- Validasi waktu memakai toleransi 0,5 detik; nilai yang disimpan tetap dari DB.
- Akurasi final bergantung pada kualitas transkrip dan model cloud; aturan
  "hanya dari transkrip" ditegakkan lewat prompt + schema + validasi backend,
  bukan jaminan semantik mutlak.

## 15. Panduan pengujian manual

1. Jalankan backend dan frontend seperti di `README.md`.
2. Set `STT_PROVIDER=mock`, `DIARIZATION_PROVIDER=mock`, `LLM_PROVIDER=mock`
   di `backend/.env` bila tanpa API key.
3. Buat meeting, unggah/rekam audio, klik **Transcribe**, tunggu selesai.
4. Opsional: klik **Diarize Speakers**, lalu ubah satu `display_name`.
5. Klik **Generate Summary**; status berubah otomatis setelah polling.
6. Periksa **Overview**, **Topics**, **Decisions**; pastikan tidak ada action
   item/assignee/deadline dan peringatan `[MOCK]` muncul.
7. Klik tombol `▶ m:ss` pada topik/keputusan; player yang sama harus bergerak ke
   waktu tersebut tanpa memuat ulang audio.
8. Klik **Regenerate Summary**; pastikan ringkasan lama masih tampil sampai hasil
   baru selesai.
9. Klik **↻ Refresh**; refresh browser halaman detail — ringkasan tetap ada.
10. Klik **Hapus Ringkasan** + konfirmasi; transkrip/audio tetap ada.
11. Uji konflik: hapus ringkasan, jalankan transkripsi, lalu coba generate —
    harus `409`; generate dua kali cepat juga `409`.
12. Hapus transkrip; ringkasan ikut hilang, audio tetap ada.
13. Untuk cloud, ganti ke `openai` dengan API key valid dan ulangi langkah 5–10;
    catat bahwa jalur ini belum terverifikasi dalam Sprint 7.
