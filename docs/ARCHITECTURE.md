# Arsitektur MeetNote AI (Sprint 10)

Aplikasi tetap menggunakan pola **modular monolith**: satu backend FastAPI dan
satu frontend React yang berkomunikasi lewat REST API JSON. Sprint 4 menambah
transkripsi; Sprint 5 menambah diarisasi anonim; Sprint 6 menambah koreksi
transkrip dan speaker; Sprint 7 menambah ringkasan AI dari transkrip tersimpan;
Sprint 8 menambah ekstraksi dan pengelolaan action items dengan provider LLM dan
sumber transkrip yang SAMA; Sprint 9 memperkuat reliability/integritas; Sprint 10
menambah export notulen TXT/PDF read-only dari data yang sudah tersimpan, tanpa
mengubah fondasi Sprint 1–9.

```text
Browser (React + Vite)
    │ 1. POST /meetings                          → Meeting (PENDING)
    │ 2a. MediaRecorder → Blob  (rekam langsung)
    │ 2b. FilePicker / DragDrop → File (lokal)
    │     └─ POST /meetings/{id}/recording
    │ 3. POST /meetings/{id}/transcription       → 202, job PROCESSING
    │ 4. GET  /meetings/{id}/transcription       ← status + segmen (polling UI)
    │ 5. POST /meetings/{id}/diarization         → 202, job PROCESSING
    │ 6. GET  /meetings/{id}/diarization         ← status + speaker (polling UI)
    │ 7. DELETE /meetings/{id}/diarization       ← speaker + job saja
    │ 8. PATCH /meetings/{id}/transcript/{seg}   ← teks segmen (Sprint 6)
    │ 9. PATCH /meetings/{id}/transcript/{seg}/speaker ← speaker manual
    │10. PATCH /meetings/{id}/speakers/{spk}     ← display_name (Sprint 6)
    │11. POST /meetings/{id}/summary            → 202, job PROCESSING (Sprint 7)
    │12. GET  /meetings/{id}/summary            ← status + ringkasan (polling UI)
    │13. DELETE /meetings/{id}/summary          ← ringkasan + job saja
    │14. POST /meetings/{id}/action-items       → 202, job ekstraksi (Sprint 8)
    │15. GET  /meetings/{id}/action-items       ← status + items + opsi speaker
    │16. PATCH/DELETE /.../action-items/{item}  ← edit/status/hapus satu item
    │17. DELETE /meetings/{id}/action-items     ← action items + job saja
    │18. GET /meetings/{id}/export/txt          ← notulen TXT (attachment)
    │19. GET /meetings/{id}/export/pdf          ← notulen PDF (attachment)
    ▼
FastAPI ── routers /api/v1 ── schemas (Pydantic)
    │                         ├─ Meeting / AudioAsset (SQLAlchemy ORM)
    │                         ├─ TranscriptSegment / TranscriptionJob
    │                         ├─ Speaker / DiarizationJob
    │                         ├─ MeetingSummary / SummaryJob
    │                         ├─ ActionItem / ActionItemSource / ActionItemJob
    │                         ├─ SQLite (meetnote.db)
    │                         └─ core/audio + core/storage (validasi & path aman)
    │
    ├─ services/transcription.py ── BackgroundTasks (in-process)
    │       └─ services/stt/registry.py
    │             ├─ MockSttProvider            (test / lokal, teks [MOCK])
    │             ├─ OpenAISttProvider          (httpx → /audio/transcriptions)
    │             ├─ FasterWhisperSttProvider   (Fase 1, lokal, lazy import)
    │             └─ WhisperCppSttProvider      (Fase 1, server OpenAI-compatible)
    │
    ├─ services/diarization/workflow.py ── BackgroundTasks (in-process)
    │       ├─ services/diarization/registry.py
    │       │    ├─ MockDiarizationProvider       (test / lokal, [MOCK])
    │       │    ├─ DeepgramDiarizationProvider   (httpx → /v1/listen)
    │       │    └─ PyannoteDiarizationProvider   (Fase 1, opt-in, lazy import)
    │       └─ mapping temporal → TranscriptSegment.speaker_id
    │
    ├─ services/summary/workflow.py ── BackgroundTasks (in-process)
    │       ├─ services/llm/registry.py
    │       │    ├─ MockLlmProvider        (test / lokal, [MOCK])
    │       │    └─ OpenAiLlmProvider      (httpx → /responses, json_schema strict)
    │       └─ validasi output + referensi → meeting_summaries
    │
    └─ services/action_items/workflow.py ── BackgroundTasks (in-process)
            ├─ services/llm/registry.py (provider + schema SAMA dengan ringkasan)
            ├─ validasi output + referensi + speaker + deadline
            └─ action_items + action_item_sources + action_item_jobs
    ▼
storage/meetings/{meeting_id}/recording-{uuid}.{ext}
```

## Backend

- `app/main.py` – entry point, CORS, lifespan (`create_all` + migrasi aditif +
  recovery keempat job macet: STT, diarisasi, ringkasan, action items)
- `app/api/v1/health.py` – health check
- `app/api/v1/config.py` – konfigurasi publik (audio, STT, diarisasi, LLM;
  tanpa secret)
- `app/api/v1/meetings.py` – daftar & pembuatan meeting
- `app/api/v1/recordings.py` – upload, metadata, playback, hapus rekaman;
  menolak hapus saat transkripsi/diarisasi `PROCESSING`
- `app/api/v1/transcriptions.py` – POST/GET/DELETE transkripsi; menolak hapus
  saat diarisasi `PROCESSING`
- `app/api/v1/diarizations.py` – POST/GET/DELETE diarisasi
- `app/api/v1/transcript_edits.py` – PATCH Sprint 6: teks segmen, speaker
  segmen, dan nama tampilan speaker (endpoint tipis, tanpa provider)
- `app/api/v1/summaries.py` – POST/GET/DELETE Sprint 7; POST = generate/retry/
  regenerate, GET aman untuk polling, DELETE hanya ringkasan + job
- `app/api/v1/action_items.py` – POST/GET/DELETE + PATCH/DELETE per item;
  DELETE semua tidak menyentuh transkrip/speaker/audio
- `app/api/v1/export.py` – GET TXT/PDF; hanya membaca data tersimpan, memakai
  `io.BytesIO`, mengembalikan attachment dengan nama file aman; tidak ada AI,
  audio, temp file, atau mutasi DB
- `app/core/config.py` – settings dari environment variable (`STT_*`,
  `DIARIZATION_*`, `LLM_*`, API key sebagai `SecretStr`)
- `app/core/audio.py` – daftar MIME/ekstensi + deteksi signature sederhana
- `app/core/storage.py` – helper path aman & nama file generated
- `app/database/session.py` – engine, `SessionLocal`, `Base`
- `app/database/migrations.py` – penambahan kolom `speaker_id` yang idempoten
- `app/models/meeting.py` – tabel `meetings` + relasi audio/transkrip/speaker
- `app/models/audio_asset.py` – tabel `audio_assets` (metadata saja)
- `app/models/transcript.py` – `transcript_segments` (termasuk `speaker_id`) +
  `transcription_jobs`; properti `speaker_display_name` (turunan relasi, bukan
  kolom)
- `app/models/diarization.py` – `speakers` + `diarization_jobs`
- `app/models/summary.py` – `meeting_summaries` + `summary_jobs`; status
  `NOT_STARTED/PROCESSING/COMPLETED/FAILED` terpisah dari job lain
- `app/models/action_item.py` – `action_items` (status `OPEN/COMPLETED/CANCELLED`,
  `is_manually_edited`, provenance aman), `action_item_sources` (FK segmen
  sungguhan per referensi), dan `action_item_jobs`
  (`NOT_STARTED/PROCESSING/COMPLETED/FAILED`)
- `app/schemas/` – kontrak `Meeting`, `Audio`, `Config`, `Transcription`,
  `Diarization`, `TranscriptEditing` (PATCH Sprint 6), `SummaryRead` +
  topik/keputusan (Sprint 7), dan `ActionItemRead`/`ActionItemUpdate` +
  opsi speaker (Sprint 8)
- `app/services/transcription.py` – validasi awal, job background, normalisasi;
  memanggil `clear_diarization()` saat transkrip dibersihkan
- `app/services/stt/base.py` – protocol `SttProvider` + `SttResult`/`SttSegment`,
  `language`, dan `source_ref` (`audio#t=<start>-<end>`)
- `app/services/stt/errors.py` – error bertipe + status HTTP yang aman
- `app/services/stt/registry.py` – pemilih provider dari `STT_PROVIDER`
- `app/services/stt/openai_provider.py` – implementasi API OpenAI via httpx
- `app/services/stt/mock.py` – provider deterministik untuk test
- `app/services/stt/faster_whisper_provider.py` – STT lokal Fase 1 (lazy import,
  `model_factory` injectable untuk contract test)
- `app/services/stt/whisper_cpp_provider.py` – fallback lokal via server
  OpenAI-compatible (WAV PCM 16-bit mono)
- `app/services/indonesian/` – kamus, normalisasi konservatif, dan metrik
  CER/WER/DER untuk benchmark lokal
- `app/services/diarization/base.py` – protocol `DiarizationProvider` +
  `DiarizationResult`/`DiarizationTurn`
- `app/services/diarization/errors.py` – error diarisasi bertipe + status HTTP aman
- `app/services/diarization/registry.py` – pemilih provider dari
  `DIARIZATION_PROVIDER`
- `app/services/diarization/deepgram_provider.py` – Deepgram Listen via httpx
- `app/services/diarization/pyannote_provider.py` – provider lokal Fase 1
  (opt-in, token HF dari environment, telemetri dimatikan)
- `app/services/diarization/mock.py` – provider mock deterministik
- `app/services/summary/prompts/id.py` – prompt ringkasan Bahasa Indonesia
  tanpa mengubah JSON Schema `overview`/`topics`/`decisions`
- `app/services/diarization/workflow.py` – validasi, background task, mapping,
  recovery, dan pembersihan hasil
- `app/services/transcript_editing.py` – aturan Sprint 6: validasi kepemilikan,
  panjang teks/nama, penolakan saat job aktif, commit hanya bila berubah, error
  500 generik; **tidak ada** pemanggilan STT/diarisasi maupun AI
- `app/services/llm/base.py` – protocol `LlmProvider`, `SummaryInput`,
  `SummaryResult`, prompt, JSON Schema strict, dan parser aman
- `app/services/llm/errors.py` – error LLM bertipe + status HTTP yang aman
- `app/services/llm/registry.py` – pemilih provider dari `LLM_PROVIDER`
- `app/services/llm/openai_provider.py` – Responses API `POST /responses`
  dengan `text.format.type=json_schema`, `strict=true`; parse `output_text`
- `app/services/llm/mock.py` – provider deterministik `[MOCK]` untuk test
- `app/services/summary/workflow.py` – validasi meeting/transkrip/job aktif,
  background task dengan `SessionLocal()`, validasi referensi segmen,
  penyimpanan ringkasan, delete, dan restart recovery
- `app/services/action_items/workflow.py` – validasi meeting/transkrip/job aktif,
  background task dengan `SessionLocal()`, validasi referensi/speaker/waktu,
  regenerasi aman (hanya item AI diganti), edit/status/delete, dan recovery
- `app/services/export.py` – snapshot `NotulenData` (read-only), render TXT UTF-8
  dan PDF via reportlab/Platypus, font TTF + sanitasi glyph, slug nama file;
  placeholder eksplisit untuk data kosong dan status job disertakan; provenance
  `audio#t=<start>-<end>` mengikuti segmen/topik/keputusan/action item tanpa
  menggantikan label waktu manusia

## Frontend

- `src/App.tsx` – dashboard + navigasi state-based (tanpa router)
- `src/api.ts` – pemanggilan API (create, upload, delete, config, playback,
  transcription + diarization start/get/delete, summary start/get/delete,
  action items start/get/delete + update/delete per item, `refreshMeeting`,
  `downloadExport(meetingId, format)`, plus helper `patchJson<T>()`)
- `src/hooks/useMediaRecorder.ts` – logika MediaRecorder, timer, cleanup
- `src/hooks/useAudioFile.ts` – validasi awal, durasi, preview file lokal
- `src/hooks/useLiveCaption.ts` – caption browser `id-ID` opsional saat merekam;
  tidak dikirim ke server dan bukan sumber notulen
- `src/utils/contrast.ts` – preferensi kontras tinggi di `localStorage` dan
  class `high-contrast` pada `<html>`
- `src/components/NewMeeting.tsx` – form + dua sumber audio (rekam / upload)
- `src/components/AudioUploader.tsx` – file picker, dropzone, preview, upload
- `src/components/MeetingList.tsx` – daftar meeting + metadata audio
- `src/components/MeetingDetail.tsx` – putar rekaman, transkrip, diarisasi,
  ringkasan AI, action items, refresh, hapus, panel Ekspor Notulen (TXT/PDF
  dengan loading/error dan pencegahan klik ganda), serta satu `<audio ref>`
  untuk seek timestamp transkrip, referensi ringkasan, maupun sumber action item
- `src/utils/export.ts` – parser `Content-Disposition`, fallback nama file aman,
  dan `saveBlob()` yang mencabut object URL; diuji dengan `node:test` bawaan
  Node.js (`npm test`) tanpa framework/dependency baru
- `src/components/TranscriptEditor.tsx` – daftar segmen berurutan (Sprint 6)
- `src/components/TranscriptSegmentItem.tsx` – per segmen: timestamp klik,
  Edit/Save/Cancel teks, pilih speaker; validasi & pencegahan dobel submit
- `src/components/SpeakerManager.tsx` – daftar speaker + baris editor nama,
  Save/Cancel/Pakai label, feedback sukses/error (Sprint 6)
- `src/components/StatusBadge.tsx` – badge status meeting/transkrip/diarisasi/
  ringkasan/action item
- `src/styles.css` – styling responsif, badge speaker, daftar speaker,
  kontrol editor Sprint 6, daftar ringkasan + tombol sumber Sprint 7,
  daftar action item + form edit Sprint 8

## Keputusan desain

- **Satu endpoint upload:** `POST /meetings/{id}/recording` dipakai ulang untuk
  rekaman MediaRecorder dan file lokal; kontraknya sama.
- **Satu rekaman per meeting:** `AudioAsset` tetap `uselist=False`.
- **File vs database:** binary audio di filesystem, metadata + path relatif di
  SQLite. Teks transkrip dan hasil diarisasi disimpan di SQLite.
- **Nama file generated:** input pengguna tidak pernah dipakai sebagai path.
- **Validasi berlapis:** frontend untuk UX, backend sebagai sumber keputusan.
- **Operasi file aman:** upload `.part` → `os.replace`; hapus `.delete` +
  rollback. `resolve_storage_path()` mencegah path traversal.
- **Tanpa router library:** navigasi cukup tiga state.
- **Provider abstraction terpisah:** STT, diarisasi, dan LLM masing-masing punya
  protocol, errors, registry, dan implementasi vendor di folder `services/`.
  Endpoint/UI tidak bergantung pada vendor.
- **Mock eksplisit:** `STT_PROVIDER=mock` menghasilkan teks `[MOCK]`;
  `DIARIZATION_PROVIDER=mock` melaporkan `provider="mock"`;
  `LLM_PROVIDER=mock` menghasilkan ringkasan `[MOCK]` dan action item `[MOCK]`
  dengan `is_mock=true`. UI menampilkan peringatan `[MOCK]` untuk semuanya.
- **Status dipisah:** `TranscriptionJob`, `DiarizationJob`, `SummaryJob`, dan
  `ActionItemJob` punya siklus `NOT_STARTED/PROCESSING/COMPLETED/FAILED` sendiri.
  Status action item (`OPEN/COMPLETED/CANCELLED`) adalah status bisnis per item,
  bukan status job.
  `MeetingStatus` Sprint 4 tidak diubah oleh diarisasi maupun ringkasan;
  konstanta lama `COMPLETED` tetap ada untuk kompatibilitas.
- **Transisi utama:** `UPLOADED → TRANSCRIBING → TRANSCRIBED` untuk transkripsi;
  diarisasi tidak mengubah status meeting.
- **Hapus selektif:** DELETE transkrip menghapus segmen + job + ringkasan + action
  items (referensinya jadi invalid); DELETE diarisasi menghapus speaker + job +
  `speaker_id`, tetapi transkrip/audio tetap ada. DELETE rekaman tetap menghapus
  keduanya lewat `clear_transcription()`. DELETE action items hanya menyentuh
  `action_items`, `action_item_sources`, dan `action_item_jobs`.
- **Perlindungan job aktif (Sprint 9):** hapus rekaman/transkrip/diarisasi/
  ringkasan/action items ditolak (`409`) bila job terkait **atau job dependen**
  masih `PROCESSING`. Ringkasan maupun action items juga ditolak saat
  transkripsi/diarisasi masih berjalan.
- **Konkurensi (Sprint 9):** `job_guard.job_lock` mengunci `(jenis job, meeting)`
  di dalam proses; `run_token` unik per percobaan dicek ulang sebelum save dan
  di `_mark_failed`, sehingga task lama tidak menimpa job baru. Klaim baris
  existing memakai `UPDATE ... WHERE status != PROCESSING`. Lintas-proses masih
  bergantung pada UNIQUE + `busy_timeout` (bukan antrean distributed).
- **Background in-process:** FastAPI `BackgroundTasks` dipakai untuk keempat job.
  Task membuka `SessionLocal()` sendiri, menyimpan hasil/error. Tidak ada
  Redis/Celery/RabbitMQ/Docker/microservice.
- **Retry provider (backoff + jitter):** `services/provider_retry.py` mengulang
  hanya error sementara (429, timeout, gangguan server/respons provider) untuk
  STT, diarisasi, ringkasan, dan action items. Error konfigurasi, autentikasi,
  format tidak didukung, dan validasi hasil tidak diulang. Default 3 attempts,
  backoff 1s→2s→4s dengan batas 8s dan jitter 0.5–1.0. Percobaan gagal hanya
  dicatat sebagai kategori error; pesan akhir `job.error` tetap sama seperti
  sebelumnya. `run_token` dicek ulang setelah retry sehingga task lama tidak
  menimpa job baru. Set `PROVIDER_RETRY_ATTEMPTS=1` untuk mematikan retry.
- **Restart recovery:** `recover_stuck_transcriptions()`,
  `recover_stuck_diarizations()`, `recover_stuck_summaries()`, dan
  `recover_stuck_action_items()` menandai job `PROCESSING` yang tertinggal
  sebagai `FAILED`, mengosongkan `run_token`, dan idempoten. Tidak ada job
  `COMPLETED` yang diubah, tidak ada hasil/file yang dihapus, dan tidak ada
  klaim resume-from-checkpoint. Tiap recovery diisolasi agar gagalnya satu
  jenis tidak membatalkan yang lain.
- **Urutan deterministik:** segmen diurutkan `start_seconds`, `end_seconds`,
  lalu urutan terima; `sequence` 1..n disimpan di DB.
- **Tanpa timestamp palsu:** provider tanpa timestamp menghasilkan segmen 0/0
  dengan `has_timestamps=false`; UI menampilkan label eksplisit.
- **Label anonim:** referensi numerik provider diurutkan sebagai angka, lalu
  diberi `Speaker 1..n`. Tidak ada klaim identitas dunia nyata.
- **Mapping konservatif:** overlap terbesar per referensi, ambang rasio default
  0.5, tie dianggap ambiguous dan dibiarkan NULL. Ini mencegah label rekaan.
- **Koreksi tanpa provider (Sprint 6):** tiga endpoint PATCH langsung menulis
  kolom yang sudah ada lewat satu service. Tidak ada job baru, STT ulang,
  penulisan ulang AI, atau perubahan kontrak provider.
- **Kepemilikan di level query:** segmen/speaker selalu dicari dengan
  `meeting_id` + id objek. Objek dari meeting lain sengaja terlihat seperti
  "tidak ditemukan" (`404`) agar tidak bocor.
- **Validasi di satu tempat:** aturan panjang/kosong ada di service, bukan
  tersebar di endpoint dan UI. Frontend memakai batas yang sama hanya sebagai
  umpan balik cepat; backend tetap sumber keputusan.
- **Commit seminimal mungkin:** nilai yang identik dengan data lama tidak
  di-commit. Kegagalan transaksi di-`rollback` dan dikembalikan sebagai `500`
  dengan pesan generik.
- **Nama = catatan pengguna:** `display_name` tidak pernah ditebak dari audio;
  nilai `null` berarti "pakai label anonim". `speaker_label` bersifat immutable.
- **Tidak ada kolom provenance:** Sprint 6 sengaja tidak menambah penanda
  "manual vs otomatis" maupun tabel audit. Alasan lengkap ada di
  `docs/SPRINT6.md` bagian 9.
- **Ringkasan hanya dari transkrip (Sprint 7):** workflow mengambil segmen dari
  `transcript_segments` yang sudah tersimpan, mengurutkannya, lalu mengirim ID,
  waktu, dan `speaker_display_name`/`speaker_label` ke LLM. Tidak ada akses ke
  audio atau pengetahuan luar.
- **Structured Outputs + validasi ulang:** provider OpenAI memakai
  `text.format.type="json_schema"` dengan `strict=true`, tetapi backend tetap
  mem-parsing JSON dan memvalidasi aturan bisnis. Refusal, response incomplete,
  HTTP error, timeout, dan JSON invalid ditangani sebagai `LlmError`.
- **Referensi bersumber:** setiap topik/keputusan wajib membawa `segment_ids`,
  `start_seconds`, dan `end_seconds`. ID harus milik meeting yang sama; waktu
  dibandingkan dengan toleransi 0,5 detik lalu **diganti dengan nilai database**
  sebelum disimpan. Referensi invalid = error output AI, bukan data yang disimpan.
- **Regenerasi aman:** ringkasan lama tidak dihapus saat POST. Baris
  `MeetingSummary` baru ditulis hanya setelah seluruh hasil tervalidasi; bila
  gagal, job `FAILED` dan ringkasan lama tetap tampil.
- **Hapus transkrip membersihkan ringkasan & action items:**
  `clear_transcription()` memanggil `clear_summary()` dan `clear_action_items()`
  agar tidak ada referensi menggantung. Audio dan speaker tidak dihapus oleh
  DELETE ringkasan maupun DELETE action items.
- **Batas input server-side:** `LLM_MAX_INPUT_CHARACTERS` dihitung dari prompt
  akhir di request thread; kelebihan menghasilkan `422` sebelum job dibuat.
  Belum ada chunking/map-reduce.
- **Action items hanya dari transkrip (Sprint 8):** provider LLM yang SAMA
  dipanggil dengan JSON Schema strict `action_items` (bukan provider/SDK baru).
  Prompt meminta hanya tindakan yang dinyatakan eksplisit; backend tidak pernah
  menyimpulkan tugas dari komitmen atau kalimat di luar transkrip.
- **Larangan mengarang:** assignee hanya diisi bila label speaker dapat dipetakan
  ke speaker meeting yang sama, atau sebagai teks eksplisit. `due_date` hanya
  diisi untuk tanggal `YYYY-MM-DD` yang tidak ambigu; frasa relatif tetap menjadi
  `deadline_text`. Label speaker ganda/ambig dibiarkan tanpa pemetaan.
- **Referensi action item:** `segment_ids` wajib, harus milik meeting yang sama,
  dan waktu `start_seconds`/`end_seconds` diverifikasi dengan toleransi 0,5 detik
  lalu diganti nilai database. Referensi invalid membuat job `FAILED` tanpa
  menyimpan item apa pun. Array `action_items` kosong adalah hasil valid.
- **Regenerasi aman (Sprint 8):** posting ulang tidak menghapus item lama lebih
  awal. Validasi terjadi sebelum satu transaksi penulisan. Hanya item yang belum
  pernah diedit (`is_manually_edited=false`) yang diganti; item edit pengguna
  dipertahankan apa adanya. Regenerasi gagal = job `FAILED`, data lama utuh.
- **Export read-only (Sprint 10):** export memakai satu snapshot `NotulenData`
  dari query SQLAlchemy, lalu merender di memori. Tidak ada provider AI, tidak
  ada `commit()`, tidak ada akses ke `STORAGE_DIR`, dan tidak ada file
  sementara. UUID divalidasi FastAPI, judul dislug menjadi ASCII untuk nama file,
  error internal menjadi 500 generik dengan kategori exception saja di log.
  Data kosong ditandai `Belum tersedia.` dan status job tetap ditampilkan agar
  export parsial tidak disalahartikan sebagai hasil lengkap.
- **Reliability & integritas (Sprint 9):** SQLite menjalankan
  `PRAGMA foreign_keys=ON` + `busy_timeout=5000` pada setiap koneksi. Error 500
  tidak pernah membocorkan SQL/path absolut. Logging `meetnote` memakai JSON
  satu baris berisi job ID, meeting ID, jenis job, provider, model, status,
  durasi, dan `error_category` (nama kelas saja) — tanpa API key, header,
  audio, atau transkrip. `GET /api/v1/health/diagnostics` melaporkan status FK
  dan anomali storage secara read-only; tidak ada orphan file yang dihapus
  otomatis. Retry transcription/diarization tetap membersihkan hasil lama di
  `prepare_*` karena referensi segmen pada ringkasan/action items, tetapi kini
  ditolak bila job dependen masih aktif.

## Migrasi database

Sprint 4 hanya menambah tabel `transcript_segments` dan `transcription_jobs`.
Sprint 5 menambah tabel `speakers` dan `diarization_jobs` lewat `create_all`,
serta kolom opsional `transcript_segments.speaker_id`.
**Sprint 6 tidak menambah tabel, kolom, atau indeks apa pun** — endpoint edit
memakai `transcript_segments.text`, `transcript_segments.speaker_id`, dan
`speakers.display_name` yang sudah ada. `apply_additive_migrations()` tidak
disentuh, dan `test_no_new_database_columns_for_sprint6` mengunci himpunan kolom
tersebut. Sprint 7 hanya menambah dua tabel baru lewat `Base.metadata.create_all`:
`meeting_summaries` dan `summary_jobs`. Tabel lama tidak dijatuhkan/dibuat ulang,
`apply_additive_migrations()` tetap hanya menambah `speaker_id` + index, dan
`test_summary_tables_are_additive` mengunci absennya kolom action item. Sprint 8
juga hanya menambah tabel baru lewat `Base.metadata.create_all`: `action_items`,
`action_item_sources`, dan `action_item_jobs`. Tabel lama tidak dijatuhkan/dibuat
ulang, dan `test_additive_schema_keeps_old_tables` mengunci keberadaan semua
tabel lama dan ketiadaan kolom action item di `meeting_summaries`. Sprint 9
menambah kolom nullable `run_token` pada keempat tabel job dan unique index
`uq_audio_asset_meeting` lewat migrasi aditif; duplikat lama tidak dihapus
(index dilewati dan dicatat). `backend/main.py` kini hanya membungkus
`app.main:app` supaya semua cara menjalankan memakai lifespan yang sama.

`apply_additive_migrations()` melakukan:

1. cek apakah `transcript_segments` ada;
2. `ALTER TABLE ... ADD COLUMN speaker_id VARCHAR(36)` hanya bila kolom belum ada;
3. `CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_id`;
4. `ALTER TABLE ... ADD COLUMN run_token VARCHAR(36)` untuk empat tabel job bila
   belum ada (Sprint 9);
5. `CREATE UNIQUE INDEX uq_audio_asset_meeting` bila tidak ada duplikat lama
   (Sprint 9).

Tidak ada `DROP TABLE`, tidak ada recreasi tabel, dan tidak ada penghapusan
data. Fase 0 menambahkan Alembic baseline `0001`: database baru dibuat dari
baseline yang setara dengan model saat ini, sedangkan database lama di-`stamp`
setelah migrasi aditif dijalankan. Tidak ada perubahan data pengguna.
FK baru otomatis ada pada database baru; pada database lama SQLite tidak
mendukung `ALTER TABLE ADD CONSTRAINT`, sehingga integritas tetap dijaga di
level ORM (`clear_diarization()` melepaskan `speaker_id` sebelum speaker
dihapus). Sejak Sprint 9, `PRAGMA foreign_keys=ON` dinyalakan per koneksi
sehingga cascade/SET NULL benar-benar dijalankan SQLite pada database yang
mempunyai constraint tersebut.

## Alasan pilihan

- SQLite cukup untuk fondasi dan tidak butuh server tambahan.
- UUID dipakai untuk ID meeting, file, segmen, dan speaker.
- Pydantic Settings memisahkan konfigurasi (storage, batas ukuran, STT,
  diarisasi, LLM) dari kode; semua API key adalah `SecretStr`.
- `GET /api/v1/config` menghindari hard-coded angka di frontend; kini juga
  memberi tahu apakah STT/diarisasi/LLM tersedia tanpa membocorkan kredensial.
- `httpx` dipakai eksplisit sebagai HTTP client provider; tidak ada SDK baru.
- OpenAI Responses API dipilih karena Structured Outputs `json_schema` strict
  didukung langsung; model `gpt-4o-mini-2024-08-06` menjadi default.
- `whisper-1` dipilih untuk STT karena mendukung segmen bertimestamp lewat
  `verbose_json` + `timestamp_granularities[]=segment`.
- Deepgram dipilih untuk diarisasi karena dokumentasi batch-nya jelas:
  `diarize_model` + `utterances=true`, auth `Token`, body biner, batas 2 GB.
- Tidak ada dependency baru di frontend maupun backend untuk Sprint 5, 6, 7,
  maupun 8 (httpx sudah tersedia sejak Sprint 4). Sprint 8 memakai ulang
  `services/llm/`, registri, dan konfigurasi `LLM_*` yang sama. Sprint 10
  menambah `reportlab` (generator PDF) dan `pypdf` (test-only parser) di backend;
  keduanya pure-Python. Frontend tetap tanpa dependency testing karena memakai
  `node:test` bawaan Node.js. Evaluasi lengkap ada di `docs/SPRINT10.md` bagian 3.
- Sprint 6 sengaja tidak memakai tabel audit atau kolom provenance: biaya
  migrasi dan risiko regresi lebih besar daripada manfaat yang dibutuhkan UI.
- Sprint 11 tidak menambah dependency maupun komponen arsitektur. Validasi
  memakai `pytest` dan `node:test` yang sudah ada. Hardening rilis dilakukan
  lewat konfigurasi: `DEBUG` default `false`, `CORS_ALLOWED_ORIGINS` dapat
  diatur, method/header CORS dibatasi, dan polling frontend mengikuti timeout
  provider terbesar. Detail ada di `docs/SPRINT11.md`.

## Sprint 11 — validasi integrasi

- Alur penuh Sprint 1–10 diuji dari pembuatan meeting sampai ekspor TXT/PDF
  dengan provider mock; data hasil edit pengguna ikut diverifikasi di dokumen.
- Reliability diuji untuk job aktif, retry, restart/recovery, kegagalan
  provider, transkripsi ulang, dan konsistensi DB/storage.
- Audit read-only menyimpulkan tidak ada `BLOCKER` baru untuk rilis lokal.
- Temuan `AUTH-01` dan `CONC-01` tetap `DEFERRED`: keduanya menjadi prasyarat
  deployment publik, bukan perubahan arsitektur sprint ini.
- Status akhir tiap temuan dan bukti `path:line` ada di `docs/SPRINT11.md` bagian
  12.

## Sprint 12 — repository & packaging

- Tidak ada komponen arsitektur, dependency, endpoint, atau migrasi baru.
- Packaging memakai struktur yang sudah ada: backend + `requirements.txt`,
  frontend + `package.json`/`package-lock.json`, dan folder `docs/`.
- Saat sprint repository masih tanpa Git; setelah lanjutan Phase A/B repository
  diinisialisasi dan remote SSH terdaftar. Detail di `docs/SPRINT13.md`.
- Backup/restore menangani dua artefak yang terpisah: `backend/meetnote.db` dan
  `storage/meetings/`. Hubungannya lewat `audio_assets.storage_path` relatif.
- Checklist manual 26 skenario tidak dijalankan dalam sprint ini dan tetap
  berstatus `NOT TESTED`.

## Sprint 13 — acceptance gate

- Persetujuan `git init` saat sprint ditolak dan dihormati; setelahnya
  disetujui, commit awal dibuat, dan kode di-push lewat SSH. Operasi Git lanjutan
  tetap memerlukan persetujuan eksplisit.
- Acceptance otomatis MAT-02/MAT-03/MAT-26 memakai `api_test.db` dan
  `backend/test_storage`; DB/audio pengguna tidak disentuh.
- Pada akhir Sprint 13, MAT-25 `BLOCKED` tanpa persetujuan live provider.
  Lanjutan Phase A/B 24–26 Nov membuktikan seluruh 26 skenario lewat mock
  terkontrol: **PASS 26 / FAIL 0 / BLOCKED 0 / NOT TESTED 0**.
- Pembaruan lanjutan Phase A/B 24–26 Nov: seluruh 26 skenario telah dibuktikan,
  termasuk MAT-25 lewat kegagalan mock terkontrol tanpa live provider. Ringkasan
  terkini ada di `docs/MANUAL_ACCEPTANCE_TEST.md` bagian 5.
- Arsitektur, dependency, endpoint, dan schema tidak berubah. Detail ada di
  `docs/SPRINT13.md`.

## Fase 0 — fondasi mutu setelah acceptance

Perubahan ini tidak mengubah endpoint bisnis maupun perilaku mock PASS 26/26:

- **Alembic `0001_baseline.py`** menjadi satu-satunya jalur skema baru.
  `run_migrations()` membedakan database kosong, database lama tanpa
  `alembic_version`, dan database yang sudah termigrasi. `apply_additive_migrations()`
  tetap dipertahankan sebagai jalur kompatibilitas dan dipanggil sebelum
  `stamp head` pada database lama. `scripts/verify_migrations.py` menguji kedua
  jalur pada direktori temporer; data pengguna tidak pernah disentuh.
- **Logging JSON + request ID** ditambahkan di `app/core/logging.py`. Middleware
  menulis `X-Request-ID` ke response dan `/health/diagnostics` mengembalikan
  nilai yang sama.
- **CI** menjalankan backend `pytest`, verifikasi `alembic history`, frontend
  `build`/`test`, dan `backend/scripts/check_secrets.py`. Dependabot memantau
  `pip`, `npm`, dan GitHub Actions.
- **Docker Compose** memisahkan volume `/data` untuk DB dan audio. Lingkungan
  development PowerShell manual tetap didokumentasikan di `INSTALLATION.md`;
  deployment container ada di `DEPLOYMENT_ONPREM.md`.
- Tata kelola repo: `LICENSE` (MIT), `CONTRIBUTING.md`, `CODEOWNERS`, dan
  `SECURITY.md`.

Test suite tetap mengelola skema sendiri dengan `RUN_DB_MIGRATIONS=false` agar
tabel `alembic_version` tidak mengganggu `create_all()`/`drop_all()` fixture.

## Batasan arsitektur saat ini

- Belum ada autentikasi/otorisasi; endpoint terbuka untuk siapa pun yang bisa
  mengakses backend.
- Background task tidak bertahan saat restart; job yang tertinggal ditandai
  `FAILED` dan harus dicoba ulang, serta tidak bisa diskalakan ke banyak worker
  tanpa antrean yang benar. Sprint 9 menutup race dalam satu proses dan
  menambah `busy_timeout`, tetapi bukan pengganti antrean distributed.
- `os.replace` pada upload bersifat atomic untuk visibility, belum crash-durable
  (`fsync` tidak dipakai). File `.part`/orphan hasil crash hanya dilaporkan
  read-only oleh `/api/v1/health/diagnostics`, tidak dihapus otomatis.
- Export TXT/PDF tersedia, tetapi hanya sebagai snapshot satu format utuh;
  belum ada pilih bagian, bahasa lain, watermark, atau tanda tangan digital.
  Glyph di luar font Bitstream Vera pada PDF diganti `?` (TXT tetap Unicode penuh).
- Seluruh transkrip dikirim sekali jalan dan dibatasi
  `LLM_MAX_INPUT_CHARACTERS`; belum ada strategi chunking/map-reduce.
- STT cloud, diarisasi Deepgram, ringkasan OpenAI, dan ekstraksi action items
  belum diverifikasi dengan API key sungguhan; test otomatis memakai mock + HTTP
  client palsu.
- Diarisasi memakai timestamp transkrip/utterance provider, bukan pengenalan
  identitas biometrik; hasil bisa `Speaker ?` bila aturan overlap tidak terpenuhi.
- Sprint 6 tidak menyimpan asal penugasan speaker, riwayat edit, atau undo;
  menjalankan ulang diarisasi membangun ulang speaker sehingga koreksi manual
  dan nama tampilan ikut hilang (perilaku Sprint 5 yang dipertahankan).
- Edit ditolak (`409`) saat job transkripsi/diarisasi masih `PROCESSING` agar
  koreksi tidak ditimpa pekerjaan latar belakang.
- Nama tampilan adalah catatan pengguna, bukan hasil pengenalan identitas.
- Rekaman, transkripsi, dan diarisasi harus dilakukan dengan sepengetahuan dan
  persetujuan peserta; aplikasi hanya mengingatkan, bukan menjamin kepatuhan.
