# Sprint 1 — Project Foundation

## Tujuan
Membangun fondasi aplikasi MeetNote AI sebelum fitur-fitur AI ditambahkan.

## Sudah tercapai
- [x] FastAPI application + konfigurasi via environment variables
- [x] Koneksi SQLite dengan SQLAlchemy dan auto-create tabel saat start
- [x] Model `Meeting` (UUID, title, status, created_at, updated_at)
- [x] Status awal `UPLOADED`
- [x] Endpoint `GET /api/v1/health`
- [x] Endpoint `GET /api/v1/meetings` (dummy list untuk dashboard)
- [x] Dashboard React + TypeScript (New Meeting, daftar meeting, empty state)
- [x] Konfigurasi API base URL via `VITE_API_BASE_URL`
- [x] Test backend (health, inisialisasi DB, model Meeting)
- [x] Build frontend berhasil

## Tidak termasuk Sprint 1
AI API, speech-to-text, diarisasi pembicara, perekaman audio, upload audio,
login/autentikasi, PostgreSQL, Docker, deployment, dan antrean pekerjaan.