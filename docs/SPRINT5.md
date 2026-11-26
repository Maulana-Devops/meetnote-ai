# Sprint 5 — Speaker Diarization (Label Anonim)

## 1. Tujuan & ruang lingkup

Sprint 5 menambahkan diarisasi untuk **rekaman dan transkrip yang sudah ada**.
Backend mengirim file audio yang tersimpan ke provider diarisasi, menerima
speaker turns bertimestamp, lalu memetakan giliran tersebut ke segmen transkrip
yang sudah ada. Hasilnya hanya berupa label anonim `Speaker 1`, `Speaker 2`, …
pada segmen; teks dan timestamp asli transkrip tidak diubah.

Termasuk: provider abstraction terpisah dari STT, model `Speaker` dan
`DiarizationJob`, endpoint POST/GET/DELETE, pekerjaan background, status,
mapping temporal, UI, pengujian mock, dan dokumentasi.

Tidak termasuk: identitas dunia nyata, pengenalan wajah/suara personal,
summarization AI, action items, transkripsi real-time, penulisan ulang teks,
Redis/Celery/RabbitMQ/Docker/microservice, atau perubahan perilaku Sprint 1–4.

## 2. Audit awal & baseline

Sebelum implementasi:

- Dokumen dibaca: `README.md`, `docs/ARCHITECTURE.md`, `docs/SPRINT1.md` …
  `docs/SPRINT4.md`.
- Kode diperiksa: `Meeting`, `AudioAsset`, `TranscriptSegment`,
  `TranscriptionJob`, STT abstraction, `services/transcription.py`, endpoint
  transcription/recording, router, config, storage, schemas, `app/main.py`,
  test fixtures, dan frontend `MeetingDetail.tsx`/`api.ts`/`types.ts`.
- Backend baseline: `python -m pytest -q` → **59 passed, 1 warning**.
- Frontend baseline: `npm run build` → **sukses**, 38 modules transformed,
  `built in 3.00s`.
- Warning hanya `DeprecationWarning` Starlette/anyio (`anyio.abc.BlockingPortal`).

Sprint 4 dinyatakan selesai dan menjadi baseline. Semua perubahan Sprint 5
dibiarkan **uncommitted** sesuai permintaan.

## 3. Keputusan provider & verifikasi dokumentasi resmi

Provider nyata yang dipilih: **Deepgram Listen API**. Alasan: dokumentasi resmi
batch diarisasi lengkap dan stabil. Dokumentasi lama AssemblyAI yang dicoba
menghasilkan `404`, sehingga tidak dipakai sebagai dasar implementasi.

Verifikasi dilakukan 23 Nov 2026 pada:

- `https://developers.deepgram.com/reference/listen-file`
- `https://developers.deepgram.com/docs/diarization`
- `https://developers.deepgram.com/docs/utterances`
- `https://developers.deepgram.com/docs/supported-audio-formats`
- `https://developers.deepgram.com/docs/pre-recorded-audio`
- `https://developers.deepgram.com/reference/authentication`

Kontrak yang dipakai:

| Item | Nilai |
| --- | --- |
| Endpoint | `POST https://api.deepgram.com/v1/listen` |
| Autentikasi | `Authorization: Token {DIARIZATION_API_KEY}` |
| Body | audio biner mentah dari storage aplikasi (di-stream per chunk) |
| Content-Type | `audio/{ext}` dari MIME tervalidasi aplikasi |
| Query | `model=nova-3`, `diarize_model=latest`, `utterances=true` |
| Deprecated | `diarize=true` **tidak dikirim**; jangan digabung dengan `diarize_model` |
| Output | `results.utterances[]` atau fallback `results.channels[].alternatives[].words[]` |
| Referensi speaker | integer Deepgram mulai dari `0`, diubah ke `Speaker 1…n` |
| Timestamp | waktu relatif audio pada utterance/word transkrip, bukan identitas |
| Format terdokumentasi | MP3, MP4/AAC/M4A, WAV, FLAC, PCM, Ogg, Opus, WebM, dll. |
| Batas file | 2 GB (diimplementasikan sebagai `DIARIZATION_MAX_FILE_BYTES`) |
| Timeout default | 180 detik; Deepgram dapat mengembalikan `504` untuk audio > ~10 menit |

Kontrak di atas diuji sebagai unit test tanpa jaringan: URL, query, header,
auth `Token`, streaming body, timeout, parsing utterance, fallback word, dan
sanitasi error 401.

Tidak ada kredensial Deepgram sungguhan yang tersedia. Karena itu:

- provider `deepgram` diimplementasikan sesuai dokumentasi, tetapi **belum
  diverifikasi live ke cloud**;
- seluruh test otomatis memakai `DIARIZATION_PROVIDER=mock`;
- provider mock melaporkan `provider="mock"` dan UI menampilkan peringatan
  `[MOCK]`, sehingga tidak pernah disajikan sebagai hasil sungguhan.

## 4. Arsitektur & struktur file

Jalur baru berdiri di samping jalur STT; keduanya memakai pola yang sama
(abstraction → registry → workflow → endpoint), tetapi statusnya terpisah.

```text
Browser (React)
  │ POST /meetings/{id}/diarization        → 202, job PROCESSING
  │ GET  /meetings/{id}/diarization        ← status + speaker (polling)
  │ DELETE /meetings/{id}/diarization      ← speaker + job saja
  ▼
FastAPI /api/v1/diarizations.py
  ▼
services/diarization/workflow.py ── BackgroundTasks (in-process)
  ├─ services/diarization/registry.py
  │    ├─ MockDiarizationProvider   (test/lokal, [MOCK])
  │    └─ DeepgramDiarizationProvider (httpx → /v1/listen)
  ├─ services/diarization/base.py    (protocol + DiarizationTurn/Result)
  ├─ services/diarization/errors.py  (error bertipe + status HTTP aman)
  └─ mapping temporal → TranscriptSegment.speaker_id
  ▼
SQLite: speakers, diarization_jobs, transcript_segments.speaker_id
```

File baru/utama:

```text
backend/app/
├── api/v1/diarizations.py
├── database/migrations.py
├── models/diarization.py
├── schemas/diarization.py
├── services/diarization/
│   ├── __init__.py
│   ├── base.py
│   ├── deepgram_provider.py
│   ├── errors.py
│   ├── mock.py
│   ├── registry.py
│   └── workflow.py
└── tests/test_sprint5.py
```

File yang dimodifikasi: `models/meeting.py`, `models/transcript.py`,
`models/__init__.py`, `schemas/transcription.py`, `schemas/config.py`,
`api/v1/router.py`, `api/v1/config.py`, `api/v1/recordings.py`,
`api/v1/transcriptions.py`, `core/config.py`, `main.py`,
`services/transcription.py`, `tests/conftest.py`, `.env.example`,
`frontend/src/{api.ts,types.ts,styles.css}`, dan `MeetingDetail.tsx`.

## 5. Konfigurasi & keamanan

Variabel backend baru:

```dotenv
DIARIZATION_PROVIDER=deepgram          # deepgram | mock
DIARIZATION_API_KEY=                   # rahasia, backend saja
DIARIZATION_API_BASE_URL=https://api.deepgram.com/v1
DIARIZATION_MODEL=nova-3
DIARIZATION_DIARIZE_MODEL=latest       # latest | v1 | v2
DIARIZATION_TIMEOUT_SECONDS=180
DIARIZATION_MAX_FILE_BYTES=2147483648
DIARIZATION_MIN_OVERLAP_RATIO=0.5
DIARIZATION_MIN_OVERLAP_SECONDS=0
```

- `DIARIZATION_API_KEY` adalah `SecretStr`. Tidak ada variabel `VITE_DIARIZATION_*`.
- `GET /api/v1/config` hanya mengembalikan `diarization_provider` dan
  `diarization_configured` (boolean), bukan key.
- Pesan error provider disanitasi: tidak memuat API key, header `Authorization`,
  atau response body mentah.
- File audio tetap berada di `STORAGE_DIR`; DB hanya menyimpan `storage_path`
  relatif dan frontend hanya memakai endpoint playback.
- Rekaman/transkripsi/diarisasi harus dilakukan dengan sepengetahuan dan
  persetujuan peserta. Aplikasi mengingatkan, tetapi tidak menjamin kepatuhan.

## 6. Model data & migrasi aditif

Tabel baru:

- `speakers`: `id`, `meeting_id`, `speaker_label`, `display_name` (opsional,
  NULL), `created_at`. Unik per `(meeting_id, speaker_label)`.
- `diarization_jobs`: `id`, `meeting_id` (unique), `status`, `provider`,
  `model`, `error`, `turns_count`, `mapped_segments`, `created_at`,
  `updated_at`.

Perubahan pada tabel lama:

- `transcript_segments.speaker_id` nullable dengan FK ke `speakers.id`
  (`ON DELETE SET NULL`). Baris lama tetap bernilai NULL dan valid.

Migrasi `apply_additive_migrations()` dijalankan saat startup:

- `CREATE TABLE IF NOT EXISTS` untuk tabel baru lewat `Base.metadata.create_all`;
- `ALTER TABLE transcript_segments ADD COLUMN speaker_id VARCHAR(36)` hanya bila
  kolom belum ada;
- `CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_id`.

Tidak ada tabel yang dijatuhkan/dibuat ulang, tidak ada `DROP`, tidak ada
Alembic/dependency baru, dan data produksi tidak dihapus.

## 7. Status & transisi

Status disimpan di `DiarizationJob`, **terpisah** dari `TranscriptionJob` dan
`MeetingStatus`:

```text
NOT_STARTED → PROCESSING → COMPLETED
                         └→ FAILED
```

- Meeting tidak berpindah status saat diarisasi; transisi Sprint 4
  `UPLOADED → TRANSCRIBING → TRANSCRIBED` tetap dipertahankan.
- `GET` sebelum pernah diarisasi mengembalikan `NOT_STARTED` dengan speaker [].
- Retry dari `FAILED` atau `COMPLETED` menghapus hasil lama, lalu membuat job
  baru; retry saat `PROCESSING` ditolak (`409`).
- Saat restart, `recover_stuck_diarizations()` menandai job `PROCESSING` yang
  tertinggal sebagai `FAILED` dengan pesan yang bisa dicoba ulang.
- `current.status === 'DIARIZING'` di UI hanya dipakai sebagai pelindung tambahan;
  sumber kebenaran tetap endpoint diarisasi.

## 8. Endpoint API

| Method | Path | Fungsi |
| --- | --- | --- |
| POST | `/api/v1/meetings/{id}/diarization` | Validasi + mulai job background, `202` |
| GET | `/api/v1/meetings/{id}/diarization` | Status, provider/model, speaker, jumlah segmen |
| DELETE | `/api/v1/meetings/{id}/diarization` | Hapus speaker + job; transkrip/audio tetap |

Validasi POST: meeting ada, audio ada dan file nyata, format/ukuran didukung,
provider terkonfigurasi, transkrip `COMPLETED` dan memiliki segmen, belum ada
job `PROCESSING`. DELETE ditolak (`409`) bila diarisasi atau transkripsi sedang
`PROCESSING`.

Perubahan endpoint lama:

- DELETE rekaman ditolak (`409`) saat diarisasi `PROCESSING`;
- DELETE transkrip ditolak (`409`) saat diarisasi `PROCESSING`;
- `clear_transcription()` ikut membatalkan diarisasi agar tidak ada speaker
  yatim setelah transkrip dihapus/dibuat ulang;
- DELETE rekaman tetap menghapus transkrip dan sekarang juga diarisasi.

## 9. Workflow background & pencegahan duplikat

`POST` memanggil `prepare_diarization()` di thread request untuk validasi dan
membuat job `PROCESSING`, lalu menambahkan `run_diarization()` ke FastAPI
`BackgroundTasks`. Response `202` dikirim sebelum provider selesai.

`run_diarization()`:

1. membuka `SessionLocal()` sendiri;
2. memuat audio + segmen yang sudah ada;
3. memanggil provider (mock/deepgram);
4. memvalidasi semua speaker turns;
5. membuat label anonim deterministik;
6. memetakan segmen memakai overlap temporal;
7. menyimpan `Speaker`, `speaker_id`, dan statistik job;
8. pada kegagalan apa pun, hanya job yang menjadi `FAILED`.

Duplikat dicegah oleh pengecekan `PROCESSING` sebelum membatalkan hasil lama.
Satu job per meeting juga dijaga oleh constraint unik `diarization_jobs.meeting_id`.

## 10. Label speaker & aturan pemetaan

Label dibuat dari referensi provider:

- referensi numerik (`"0"`, `"1"`, `"10"`) diurutkan sebagai angka;
- `Speaker 1`, `Speaker 2`, … selalu unik per meeting;
- `display_name` dibiarkan NULL — tidak ada identitas dunia nyata.

Pemetaan tiap segmen:

1. `overlap` = irisan `[start, end]` segmen dan turn;
2. overlap dijumlahkan per referensi speaker (mendukung overlapping speech);
3. pemenang harus memiliki overlap `>= DIARIZATION_MIN_OVERLAP_RATIO * durasi`
   dan `>= DIARIZATION_MIN_OVERLAP_SECONDS`;
4. dua referensi dengan overlap terbaik sama → **ambiguous**, segmen dibiarkan
   tanpa label;
5. segmen tanpa timestamp asli atau durasi nol → tanpa label;
6. segmen yang tidak bertemu turn mana pun → tanpa label;
7. teks dan timestamp segmen tidak pernah ditulis ulang.

Default ambang: rasio `0.5`, detik `0`. Artinya overlap harus lebih dari nol dan
minimal setengah durasi segmen. Nilai ini bisa diubah lewat environment variable.

Contoh: segmen `0–6s` dengan turn `0–3s` dan `3–6s` menghasilkan overlap 3s vs
3s → ambiguous → `speaker_id = NULL`, bukan tebakan.

## 11. Frontend

Halaman detail meeting kini memiliki bagian **Diarisasi Pembicara**:

- tombol **Diarize Speakers** hanya muncul bila rekaman dan transkrip siap;
- tombol dinonaktifkan saat memproses/menghapus untuk mencegah dobel submit;
- status `PROCESSING` ditampilkan sebagai notice dan di-poll tiap 1,5 detik
  sampai status final, lalu segmen diambil ulang;
- **↻ Refresh** untuk penyegaran manual; tombol retry memakai tombol Diarize
  yang sama setelah gagal;
- **Hapus Diarisasi** meminta konfirmasi `window.confirm`;
- metadata menampilkan status, provider, model, jumlah speaker, dan jumlah
  segmen yang dipetakan;
- peringatan `[MOCK]` tampil bila provider mock dipakai;
- di samping tiap segmen tampil badge label speaker atau `Speaker ?` untuk
  kondisi unassigned/ambiguous;
- Delete Recording dinonaktifkan saat diarisasi berjalan.

Tidak ada dependency frontend baru; tipe dan fungsi API ditambahkan di
`types.ts` dan `api.ts`.

## 12. Penanganan error

| Kondisi | Respons |
| --- | --- |
| Meeting/rekaman/file audio tidak ada | `404` |
| Transkrip belum selesai / sudah ada job `PROCESSING` | `409` |
| Format tidak didukung provider | `415` |
| Ukuran melebihi batas provider | `413` |
| Konfigurasi/kredensial kurang | `503` |
| Provider 401/403, 429, timeout, 5xx | `502`/`429`/`504` saat validasi; saat background → job `FAILED` |
| DB/storage gagal | `500`, atau job `FAILED` di background |

Semua pesan yang disimpan di `DiarizationJob.error` aman untuk ditampilkan ke UI.
Kegagalan diarisasi tidak menghapus transkrip maupun audio.

## 13. Pengujian

`backend/tests/test_sprint5.py` memakai DB SQLite dan `STORAGE_DIR` isolasi dari
fixture `s2_db`/`s2_client`, provider mock yang disuntik via monkeypatch, dan
fake HTTP client untuk kontrak Deepgram. Cakupan:

- sukses satu/multiple speaker dan label unik deterministik;
- relasi `Speaker` ↔ segmen tersimpan di DB;
- urutan numerik `1, 2, 10` bukan `1, 10, 2`;
- no overlap, di bawah ambang, ambiguous tie, overlapping speech, timestamp
  hilang, durasi nol;
- timestamp negatif, `end < start`, referensi speaker kosong, respons kosong;
- meeting/audio/transkrip tidak ada, format tidak didukung, file hilang;
- duplikat `409`, provider error/timeout → `FAILED`, retry sukses;
- database error saat prepare → `500`, restart recovery;
- DELETE diarisasi mempertahankan teks/timestamp/audio;
- DELETE rekaman dan transkrip diblok saat `PROCESSING`;
- transkripsi ulang dan DELETE rekaman membersihkan diarisasi;
- konfigurasi publik tanpa secret dan `SecretStr` tersembunyi di `repr`;
- kontrak permintaan/respons Deepgram (tanpa jaringan).

Hasil akhir:

- `python -m pytest -q` → **95 passed, 1 warning** (Sprint 1–5, warning hanya
  deprecation Starlette/anyio);
- `npm run build` → **sukses**, 38 modules transformed, `built in 1.81s`.

Tidak ada test frontend otomatis karena infrastruktur belum ada; build/type-check
dipakai sebagai gerbang kualitas.

## 14. Keterbatasan & status live

- **Diarisasi cloud Deepgram belum diuji live** karena tidak ada API key
  sungguhan. Kontrak API diverifikasi dari dokumentasi resmi dan diuji dengan
  fake HTTP client, bukan panggilan jaringan.
- Provider mock adalah satu-satunya provider yang dipakai test otomatis dan
  ditandai eksplisit `[MOCK]`.
- Label hanya anonim; aplikasi tidak mengenali atau mengklaim identitas dunia
  nyata. `display_name` sengaja kosong.
- Timestamp yang dipakai adalah waktu transkrip/utterance dari provider,
  bukan bukti identitas pembicara.
- Overlapping speech dan transisi cepat bisa menghasilkan `Speaker ?` bila
  aturan ambang/ambiguitas tidak terpenuhi — ini disengaja agar tidak mengarang.
- Background task masih in-process: hilang saat restart dan tidak cocok untuk
  multi-worker. Tidak ada Redis/Celery/RabbitMQ/Docker/microservice.
- Audio > ~10 menit berisiko `504` dari Deepgram meskipun batas file 2 GB.
- Belum ada autentikasi, kolaborasi, PostgreSQL, summarization AI, action items,
  atau deployment produksi.
- Rekaman/transkripsi/diarisasi wajib dengan sepengetahuan dan persetujuan
  peserta; pengguna bertanggung jawab terhadap kepatuhan hukum setempat.
