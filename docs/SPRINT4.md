# Sprint 4 — Speech-to-Text untuk Rekaman yang Sudah Ada

## 1. Tujuan & ruang lingkup

Sprint 4 menambahkan kemampuan mengubah rekaman yang sudah tersimpan menjadi
teks dengan timestamp. Fokusnya adalah **rekamanที่ sudah ada** (bukan
transkripsi real-time), provider abstraction, penyimpanan segmen di SQLite,
REST API, pekerjaan background sederhana, dan UI pada halaman detail meeting.

Tidak diubah: alur rekam/upload Sprint 2–3, playback, penghapusan rekaman,
daftar meeting, dan kontrak endpoint lama.

## 2. Audit awal & baseline

Sebelum menulis kode Sprint 4, dilakukan audit:

- Dokumen dibaca: `README.md`, `docs/ARCHITECTURE.md`, `docs/SPRINT1.md`,
  `docs/SPRINT2.md`, `docs/SPRINT3.md`.
- Kode diperiksa: model `Meeting`/`AudioAsset`, endpoint meeting/recording,
  `core/config.py`, `database/session.py`, schema Pydantic, router,
  `app/main.py`, `tests/conftest.py`, dan frontend `MeetingDetail.tsx`/`api.ts`.
- Baseline backend: `python -m pytest -q` → **33 passed, 1 warning**.
- Baseline frontend: `npm run build` → **sukses**, 38 modules transformed.

Warning yang muncul hanya deprecation Starlette/anyio, bukan kegagalan.

## 3. Keputusan provider & verifikasi API

Provider default: **OpenAI Transcription API** (`STT_PROVIDER=openai`).

Dokumentasi resmi diverifikasi pada 23 Nov 2026
(`https://platform.openai.com/docs/api-reference/audio/createTranscription`
dan halaman guide speech-to-text):

| Item | Nilai yang dipakai |
| --- | --- |
| Endpoint | `POST {STT_API_BASE_URL}/audio/transcriptions` |
| Autentikasi | `Authorization: Bearer {STT_API_KEY}` |
| Body | `multipart/form-data` |
| Field wajib | `file`, `model` |
| Field tambahan | `response_format=verbose_json`, `timestamp_granularities[]=segment` |
| Model default | `whisper-1` |
| Batas file | 25 MB |
| Format input | `flac`, `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `ogg`, `wav`, `webm` |

Nama model yang dipakai adalah **`whisper-1`**.
Granularitas `segment` didokumentasikan untuk `whisper-1`; model lain tidak
dijamin mengembalikan `segments`. Bila respons hanya berisi `text`, aplikasi
menyimpan **satu segmen dengan timestamp 0/0** dan menandai
`has_timestamps=false`, lalu UI menampilkan label “Tanpa timestamp asli” —
bukan timestamp rekaan.

Tidak ada API key sungguhan yang tersedia selama pengembangan. Oleh karena itu:

- Provider `openai` diimplementasikan sesuai dokumentasi, tetapi **tidak diuji
  live** ke cloud.
- Provider `mock` dipakai oleh seluruh test otomatis. Semua teks mock diawali
  `[MOCK]` supaya tidak tertukar dengan transkrip sungguhan.
- Tidak ada klaim bahwa transkripsi cloud telah berhasil dijalankan.

## 4. Arsitektur & struktur file

```text
backend/app/
├── api/v1/
│   ├── config.py            # + stt_provider, stt_configured (tanpa secret)
│   ├── router.py            # + transcriptions router
│   ├── recordings.py        # hapus rekaman ikut membersihkan transkrip
│   └── transcriptions.py    # POST/GET/DELETE /meetings/{id}/transcription
├── models/
│   ├── meeting.py           # + TRANSCRIBED, relasi transkrip
│   └── transcript.py        # TranscriptSegment + TranscriptionJob
├── schemas/
│   ├── config.py            # + field STT publik
│   └── transcription.py     # TranscriptionRead, TranscriptSegmentRead
├── services/
│   ├── transcription.py     # workflow + background task
│   └── stt/
│       ├── base.py          # protocol SttProvider + SttResult/SttSegment
│       ├── errors.py        # error bertipe + status HTTP aman
│       ├── registry.py      # pemilih provider dari STT_PROVIDER
│       ├── mock.py          # provider deterministik untuk test
│       └── openai_provider.py
└── main.py                  # create_all + recover_stuck_transcriptions()
```

Lapisan API tidak mengetahui detail vendor. Semua detail httpx, multipart, dan
parsing respons berada di `services/stt/openai_provider.py`.

## 5. Konfigurasi & keamanan

Environment variable baru (backend saja):

| Variable | Default | Fungsi |
| --- | --- | --- |
| `STT_PROVIDER` | `openai` | `openai` atau `mock` |
| `STT_API_KEY` | kosong | Kredensial provider; **rahasia** |
| `STT_API_BASE_URL` | `https://api.openai.com/v1` | Base URL API |
| `STT_MODEL` | `whisper-1` | Model transcription |
| `STT_TIMEOUT_SECONDS` | `120` | Timeout request provider |
| `STT_MAX_FILE_BYTES` | `26214400` | Batas dokumen provider (25 MB) |

Keamanan:

- `STT_API_KEY` hanya dibaca oleh Pydantic Settings di backend dan disimpan
  sebagai `SecretStr`, sehingga nilai tidak muncul bila `settings` di-repr/log.
- Tidak ada variabel `VITE_STT_*`; frontend tidak pernah menerima API key.
- `GET /api/v1/config` hanya mengembalikan `stt_provider` (nama) dan
  `stt_configured` (boolean), bukan nilai kredensial.
- Pesan error provider tidak menyertakan header `Authorization`, URL dengan
  query secret, atau response mentah.
- Saat `STT_API_KEY` kosong, POST ditolak dengan `503` sebelum job dibuat.

Contoh sudah ditambahkan ke `backend/.env.example` dan `.env.example` root.
File `frontend/.env.example` sengaja tidak diubah.

## 6. Model & keputusan migrasi

Dua tabel **baru** dibuat:

### `transcript_segments`

| Kolom | Tipe | Catatan |
| --- | --- | --- |
| `id` | String(36) | UUID string, primary key |
| `meeting_id` | String(36) | FK → `meetings.id`, cascade |
| `text` | Text | Teks dari provider, bukan buatan aplikasi |
| `start_seconds` | Float | `>= 0` |
| `end_seconds` | Float | `>= start_seconds` |
| `sequence` | Integer | Urutan deterministik (1..n) |
| `created_at` | DateTime | `server_default=func.now()` |

Constraint: unik `(meeting_id, sequence)` + index `(meeting_id, sequence)`.
Tidak ada kolom speaker/diarization.

### `transcription_jobs`

Satu baris per meeting berisi status proses, nama provider, model, flag
`has_timestamps`, dan pesan error yang aman. Status job dipisahkan dari
`meetings.status` agar error tetap bisa dibaca setelah status meeting berubah.

Keputusan migrasi:

- **Tidak ada ALTER TABLE** pada `meetings` atau `audio_assets`.
- Konstanta `MeetingStatus.TRANSCRIBED` ditambahkan di Python; konstanta lama
  `COMPLETED` dipertahankan untuk kompatibilitas.
- `Base.metadata.create_all()` sudah dipanggil di lifespan `app/main.py` setelah
  `app.models` di-import. Karena perubahannya hanya tabel baru, `create_all`
  cukup dan data lama tidak disentuh.
- **Alembic tidak ditambahkan**: belum ada migrasi bersifat destruktif/perubahan
  kolom, dan menambahkan kerangka migrasi akan menjadi dependency serta
  kompleksitas baru. Jika sprint berikutnya mengubah kolom lama, Alembic perlu
  dievaluasi ulang.
- Test menjatuhkan tabel di `api_test.db` milik test; database produksi
  `meetnote.db` dan folder `storage/` tidak pernah dihapus.

## 7. Status & transisi

Status Meeting (sesuai konvensi string yang sudah ada):

```text
UPLOADED ──► TRANSCRIBING ──► TRANSCRIBED
                  └──────────► FAILED
```

Status job internal:

```text
NOT_STARTED ──► PROCESSING ──► COMPLETED
                     └────────► FAILED
```

Mapping:

- Sukses: `job=COMPLETED`, `meeting=TRANSCRIBED`.
- Gagal: `job=FAILED`, `meeting=FAILED`, `error` diisi pesan aman.
- `COMPLETED` pada `MeetingStatus` tetap ada untuk kode lama, tetapi tidak
  dipakai sebagai status sukses Sprint 4.
- Hapus transkrip atau hapus rekaman mengembalikan meeting ke `UPLOADED`
  (atau `PENDING` saat rekaman dihapus).
- Saat aplikasi restart, job yang masih `PROCESSING`/meeting `TRANSCRIBING`
  ditandai `FAILED` oleh `recover_stuck_transcriptions()`.

## 8. Endpoint API

| Method | Path | Fungsi | Sukses |
| --- | --- | --- | --- |
| POST | `/api/v1/meetings/{id}/transcription` | Validasi + mulai background task | `202` + status `PROCESSING` |
| GET | `/api/v1/meetings/{id}/transcription` | Status, error, full text, segmen | `200` |
| DELETE | `/api/v1/meetings/{id}/transcription` | Hapus segmen + job; audio tetap | `200` |

Contoh respons GET setelah sukses:

```json
{
  "meeting_id": "…",
  "status": "COMPLETED",
  "meeting_status": "TRANSCRIBED",
  "provider": "openai",
  "model": "whisper-1",
  "has_timestamps": true,
  "error": null,
  "full_text": "…",
  "segments": [
    {
      "id": "…",
      "meeting_id": "…",
      "text": "…",
      "start_seconds": 0.0,
      "end_seconds": 2.4,
      "sequence": 1,
      "created_at": "…"
    }
  ],
  "updated_at": "…"
}
```

Kode error utama: `400` file kosong, `404` meeting/rekaman/file tidak ada,
`409` transkripsi sedang berjalan, `413` file melebihi batas, `415` format
tidak didukung, `500` kegagalan database, `503` konfigurasi belum lengkap,
`502`/`504` kegagalan provider (umumnya tercatat pada job saat background).

## 9. Workflow background & pencegahan duplikat

`POST` hanya melakukan validasi cepat, menghapus transkrip lama, membuat job
`PROCESSING`, lalu menjadwalkan `run_transcription()` lewat FastAPI
`BackgroundTasks`. Response `202` dikirim sebelum provider dipanggil.

Task background:

- Membuka `SessionLocal()` sendiri karena session request sudah ditutup.
- Membaca ulang meeting, job, dan `AudioAsset` dari database.
- Memanggil provider melalui registry.
- Memvalidasi teks/timestamp, mengurutkan segmen, lalu menyimpannya.
- Mengubah status menjadi `COMPLETED`/`TRANSCRIBED`, atau `FAILED` dengan pesan
  aman bila apa pun gagal.

Pencegahan duplikat:

- POST yang melihat job `PROCESSING` atau meeting `TRANSCRIBING` → `409`.
- Tombol Transcribe di UI ikut dinonaktifkan saat proses berjalan.
- DELETE transkrip saat masih `PROCESSING` → `409`.
- DELETE rekaman saat transkripsi masih `PROCESSING` → `409`, sehingga audio
  tidak bisa dihapus dari bawah job yang sedang berjalan. UI juga menonaktifkan
  tombol `Delete Recording` pada kondisi ini.
- `db.flush()` dipanggil setelah menghapus job lama sebelum menyisipkan job
  baru, agar unique constraint `transcription_jobs.meeting_id` tidak tertabrak
  saat retry.

Keterbatasan: `BackgroundTasks` berjalan **di dalam proses FastAPI**. Task
yang sedang berjalan akan hilang jika server dimatikan/di-restart. Tidak ada
Redis, Celery, RabbitMQ, Docker, atau microservice. Setiap kali startup,
`recover_stuck_transcriptions()` menandai job yang macet sebagai `FAILED` agar
pengguna bisa mencoba lagi lewat tombol Transcribe.

## 10. Frontend

Halaman `MeetingDetail` kini memiliki:

- Tombol **Transcribe** (dinonaktifkan tanpa rekaman atau saat proses berjalan).
- Status “Memproses…” + indikator `PROCESSING` dengan polling GET tiap 1,5 detik
  (maksimal ~2 menit) sampai `COMPLETED`/`FAILED`.
- Tombol **↻ Refresh** untuk menyegarkan status/segmen secara manual.
- Daftar segmen dengan timestamp `m:ss` / `h:mm:ss`, urutan `sequence`, dan
  label “Tanpa timestamp asli” bila provider tidak mengirim timestamp.
- Badge status transkripsi, provider/model, dan jumlah segmen.
- Tombol **Hapus Transkrip** dengan `window.confirm`; audio tidak ikut terhapus.
- Error yang jelas untuk 409/config/provider, lalu direset saat mencoba lagi
  atau berpindah meeting.
- Catatan bahwa rekaman harus dibuat dengan sepengetahuan dan persetujuan
  semua peserta.

Alur lama tetap bekerja: merekam, mengunggah, memutar, menghapus rekaman,
menambah rekaman, dan kembali ke dashboard. Saat rekaman dihapus, UI juga
mengosongkan transkrip karena backend membersihkan data terkait.

Tidak ada dependensi frontend baru dan tidak ada test framework frontend baru.

## 11. Penanganan error

| Skenario | Perlakuan |
| --- | --- |
| Meeting tidak ada | `404` sebelum job dibuat |
| AudioAsset tidak ada | `404` “Rekaman belum tersedia” |
| File audio hilang dari storage | `404` saat POST; `FAILED` bila hilang setelah task mulai |
| File kosong | `400`, tidak diproses |
| Format/ekstensi tidak didukung | `415`, status tetap `UPLOADED` |
| File > batas | `413` |
| `STT_API_KEY`/config kosong atau provider salah | `503`, tanpa job macet |
| Kredensial ditolak (401/403) | error aman tersimpan di job `FAILED` |
| Timeout | Job `FAILED` dengan pesan timeout (provider dipanggil di background) |
| Rate limit (429) | pesan “coba lagi nanti” di job `FAILED` |
| Provider 5xx / respons bukan JSON | job `FAILED` dengan ringkasan aman |
| Respons kosong / timestamp negatif / akhir < awal | `FAILED`, segmen tidak disimpan |
| Permintaan ganda | `409` |
| Transaksi DB gagal | `rollback`, `500`, status tidak dibiarkan `TRANSCRIBING` |

Tidak ada transkrip fiktif. Provider mock pun memberi awalan `[MOCK]`.

## 12. Pengujian

Backend:

```powershell
cd backend
python -m pytest -q
```

Hasil akhir: **59 passed, 1 warning** (33 lama + 26 baru). Warning tetap
deprecation Starlette/anyio.

Cakupan test Sprint 4 meliputi:

- sukses satu segmen dan banyak segmen;
- sorting deterministik dengan urutan provider dibalik;
- teks tanpa timestamp tidak diberi timestamp palsu;
- GET berulang konsisten dan kondisi `NOT_STARTED`;
- timestamp negatif dan `end < start`;
- transisi `UPLOADED → TRANSCRIBING → TRANSCRIBED`;
- meeting tidak ada, rekaman tidak ada, file hilang;
- duplikat `409`, retry setelah gagal;
- konfigurasi kosong, auth, timeout, rate limit, error server, respons kosong;
- format tidak didukung dan kegagalan transaksi database;
- hapus transkrip tanpa menghapus audio;
- hapus rekaman ikut membersihkan transkrip;
- `/api/v1/config` tidak membocorkan `STT_API_KEY`, dan `SecretStr` menyamarkan
  kunci bila `settings` di-repr/log.

Frontend:

```powershell
cd frontend
npm run build
```

Hasil akhir: **sukses**, type-check + Vite build berhasil (38 modules
transformed). Tidak ada panggilan jaringan ke provider sungguhan dalam test.

## 13. Keterbatasan & tidak termasuk Sprint 4

- Transkripsi cloud **belum diuji live** karena tidak ada API key sungguhan.
- Hanya transkripsi dari rekaman yang sudah ada; belum real-time.
- Tanpa diarisasi/identifikasi pembicara, summarization AI, atau action items.
- Tanpa autentikasi/otorisasi, kolaborasi, PostgreSQL, Docker, atau deployment.
- Tanpa sistem antrean; background task hilang saat restart (lihat bagian 9).
- Batas ukuran mengikuti dokumentasi provider (25 MB) dan batas aplikasi.
- Kualitas dan bahasa hasil sepenuhnya bergantung pada provider/model.
- Rekaman wajib dilakukan dengan kesadaran dan persetujuan peserta; aplikasi
  hanya mengingatkan, bukan menggantikan kewajiban hukum/etika tersebut.
