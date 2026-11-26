# Panduan Instalasi Lokal — Windows PowerShell

Panduan ini ditujukan untuk rilis lokal/internal MeetNote AI. Semua perintah
menggunakan **Windows PowerShell**. Tidak ada perintah yang mengasumsikan Linux
atau mengubah Windows Execution Policy.

## 1. Prasyarat

Versi terverifikasi pada lingkungan pengembangan:

| Komponen | Versi | Catatan |
| --- | --- | --- |
| Python | 3.12.10 | Kompatibel dengan Python 3.12.x |
| Node.js | 24.22.1 | Disarahkan Node.js 24.x |
| npm | 11.19.1 | Menyertai Node.js 24 |
| Browser | Chrome/Edge/Firefox/Safari terbaru | Perlu `MediaRecorder` untuk rekaman langsung |
| Mikrofon | Terhubung | Hanya untuk rekaman langsung |

Git **tidak diperlukan** untuk menjalankan aplikasi. Repository sudah
diinisialisasi dan memiliki remote SSH, tetapi operasi Git lanjutan tetap
memerlukan persetujuan eksplisit. Untuk deployment on-prem satu perintah, lihat
`docs/DEPLOYMENT_ONPREM.md`; panduan PowerShell manual di bawah tetap berlaku.

## 2. Struktur yang dipakai saat instalasi

```text
meetnote-ai/
├── backend/
│   ├── app/
│   ├── tests/
│   ├── .env.example
│   ├── main.py
│   └── requirements.txt
├── docs/
├── frontend/
│   ├── src/
│   ├── tests/
│   ├── .env.example
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.ts
└── storage/
```

## 3. Instalasi backend

Dari root proyek:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Jika aktivasi venv diblokir oleh kebijakan sistem, **jangan** mengubah Execution
Policy. Selalu panggil interpreter venv secara langsung:

```powershell
.\.venv\Scripts\python.exe main.py
```

Semua dependency backend **wajib** sudah dipatok eksak di `requirements.txt`.
Dependency model (Fase 1) bersifat opsional dan dipasang manual sesuai bagian
berikut. Jangan menjalankan upgrade dependency massal.

## 4. Konfigurasi backend

File `backend/.env` dibuat dari `.env.example` dan berisi placeholder. Isi sesuai
kebutuhan:

- Untuk mencoba alur tanpa API key:

```powershell
notepad .env
```

Lalu set:

```text
DEBUG=false
STT_PROVIDER=mock
DIARIZATION_PROVIDER=mock
LLM_PROVIDER=mock
```

Hasil akan ditandai `[MOCK]` dan bukan hasil AI sungguhan.

- Untuk provider sungguhan, isi `STT_API_KEY`, `DIARIZATION_API_KEY`, dan/atau
  `LLM_API_KEY` **hanya di `backend/.env`**. Jangan pernah menaruhnya di frontend
  atau variabel `VITE_*`, dan jangan menempelkan nilainya ke chat.
- `CORS_ALLOWED_ORIGINS` berisi daftar origin yang diizinkan, dipisah koma.
  Default: `http://localhost:5173,http://127.0.0.1:5173`.
- Jika menjalankan `npm run preview` (port 4173), tambahkan
  `http://localhost:4173` ke `CORS_ALLOWED_ORIGINS`.
- Set `DEBUG=true` hanya jika ingin auto-reload saat development.

### Opsi Bahasa Indonesia tanpa API key (Fase 1)

Untuk memakai STT lokal pada host sendiri, pasang dependency opsional lalu
ubah `backend/.env`:

```powershell
.\.venv\Scripts\python.exe -m pip install faster-whisper
notepad .env
```

```dotenv
STT_PROVIDER=faster_whisper
STT_LANGUAGE=id
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_VAD=true
STT_WORD_TIMESTAMPS=true
STT_MODEL_DIR=../models/faster-whisper
```

Model/bobot diunduh pada pemakaian pertama ke folder model (bukan ke Git).
Jika memakai `whisper.cpp`, jalankan server OpenAI-compatible-nya lalu set
`STT_PROVIDER=whisper_cpp`, `WHISPER_CPP_BASE_URL`, dan `WHISPER_CPP_MODEL`;
audionya harus WAV PCM 16-bit mono.

Diarisasi lokal `DIARIZATION_PROVIDER=pyannote` juga opsional. Pasang
`pyannote-audio` manual, terima conditions model di Hugging Face, lalu isi
`PYANNOTE_TOKEN` **hanya di `backend/.env`**. Jangan menempelkan token ke chat,
file publik, atau variabel `VITE_*`. Telemetri dimatikan dengan
`PYANNOTE_METRICS_ENABLED=false`.

Belum ada angka CER/WER/DER/latency yang diterbitkan; lihat
`docs/BENCHMARK_METHOD.md` sebelum mengklaim kualitas.

## 5. Menjalankan backend

Dari folder `backend`:

```powershell
.\.venv\Scripts\python.exe main.py
```

Alternatif dengan uvicorn langsung:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend berjalan di `http://localhost:8000`.

Endpoint yang bisa dicek:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/health/diagnostics
Invoke-RestMethod http://localhost:8000/api/v1/config
```

- `/health` mengembalikan status aplikasi.
- `/health/diagnostics` mengembalikan status FK SQLite dan audit storage
  read-only.
- `/config` mengembalikan nama provider dan status `configured`, bukan secret.

Dokumentasi interaktif tersedia di `http://localhost:8000/docs`.

## 6. Lokasi data backend

| Data | Lokasi relatif terhadap root proyek |
| --- | --- |
| Database utama | `backend/meetnote.db` |
| Database test API | `backend/api_test.db` |
| Database test lain | `backend/test.db` |
| Audio produksi | `storage/meetings/<meeting_id>/` |
| Audio test | `backend/test_storage/meetings/<meeting_id>/` |
| Hasil build frontend | `frontend/dist/` |

Database dan storage test dibuat/dipakai oleh test suite. Jangan menghapusnya
secara manual saat aplikasi atau test sedang berjalan.

## 7. Instalasi frontend

Terminal terpisah, dari root proyek:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

`npm ci` digunakan karena `package-lock.json` tersedia dan sinkron dengan
`package.json`. Jangan menjalankan `npm update` atau mengubah dependency tanpa
alasan teknis dan pengujian ulang.

Frontend berjalan di `http://localhost:5173`.

Isi `frontend/.env`:

```text
VITE_API_BASE_URL=http://localhost:8000
```

## 8. Build produksi frontend

```powershell
cd frontend
npm run build
```

Hasil build ada di `frontend/dist/`. Untuk mencoba hasil build:

```powershell
npm run preview
```

`preview` biasanya memakai `http://localhost:4173`; pastikan origin tersebut masuk
`CORS_ALLOWED_ORIGINS` di backend.

## 9. Menjalankan test

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend:

```powershell
cd frontend
npm test
npm run build
```

Baseline Sprint 12: backend `229 passed, 1 warning`, frontend `7 pass, 0 fail`,
dan build sukses. Detail ada di `docs/SPRINT12.md`.

## 10. Troubleshooting

| Gejala | Penyebab umum | Tindakan |
| --- | --- | --- |
| `Activate.ps1` ditolak | Execution Policy | Jangan diubah. Pakai `.\.venv\Scripts\python.exe` |
| Port 8000 sudah dipakai | Backend lain | Tutup proses lama atau ubah `BACKEND_PORT` di `.env` |
| Port 5173 sudah dipakai | Frontend lain | Tutup proses lama atau jalankan Vite dengan port lain |
| CORS error di browser | Origin tidak terdaftar | Tambahkan origin ke `CORS_ALLOWED_ORIGINS`, restart backend |
| `/health` sukses, provider ditolak | API key kosong | Isi variabel `*_API_KEY` di backend atau pakai provider `mock` |
| Frontend blank | Build/TypeScript error | Jalankan `npm run build` lalu perbaiki error yang muncul |
| `npm ci` gagal | Lockfile/package.json tidak sinkron | Jangan `npm update`; laporkan ketidaksesuaian |
| Rekaman tidak mulai | Izin mikrofon ditolak | Izinkan mikrofon untuk origin yang dipakai |
| Database terkunci | Proses backend/test masih jalan | Hentikan proses sebelum backup/restore manual |
| Tidak ada auto-reload | `DEBUG=false` | Set `DEBUG=true` untuk development saja |
| Audio tidak bisa diputar | Format browser | Gunakan WebM/Opus atau WAV |

Untuk prosedur backup dan restore, lihat `docs/BACKUP_RESTORE.md`. Untuk daftar
pemeriksaan manual, lihat `docs/MANUAL_ACCEPTANCE_TEST.md`.
