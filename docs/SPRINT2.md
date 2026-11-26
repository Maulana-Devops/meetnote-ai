# Sprint 2 — Live Audio Recording

## Tujuan
Pengguna dapat membuat meeting dan merekam percakapan langsung dari mikrofon
browser, memutar preview, lalu menyimpan rekaman ke backend.

## Sudah tercapai
- [x] `POST /api/v1/meetings` (status awal `PENDING`)
- [x] `GET /api/v1/meetings` (kini menyertakan `has_recording` & `recording`)
- [x] Model `AudioAsset` + relasi satu-ke-satu dengan `Meeting`
- [x] `POST /api/v1/meetings/{id}/recording` (multipart/form-data)
- [x] `GET /api/v1/meetings/{id}/recording` (metadata)
- [x] `GET /api/v1/meetings/{id}/recording/play` (FileResponse aman)
- [x] Validasi MIME type, ekstensi, ukuran (env `MAX_AUDIO_FILE_BYTES`)
- [x] Nama file generated UUID, path traversal dicegah
- [x] Rollback file jika metadata gagal disimpan
- [x] 404 meeting/rekaman tidak ditemukan, 409 rekaman duplikat
- [x] UI New Meeting: form, recorder, pause/resume, durasi, preview, hapus, save
- [x] MediaRecorder memilih format via `isTypeSupported()`
- [x] Object URL preview dibersihkan saat unmount / replace
- [x] Dashboard menampilkan status & metadata audio
- [x] Test backend Sprint 1 + Sprint 2 lulus
- [x] `npm run build` berhasil

## Perubahan status
- Meeting baru lewat API: `PENDING`.
- Setelah rekaman tersimpan: `UPLOADED`.
- Model default `UPLOADED` dipertahankan untuk kompatibilitas data Sprint 1.

## Lokasi file
- Audio: `storage/meetings/{meeting_id}/recording-{uuid}.{ext}`
- Metadata: tabel `audio_assets` (SQLite `backend/meetnote.db`)

## Format & batas
- Frontend: webm/opus → ogg/opus → mp4 → wav (sesuai dukungan browser).
- Backend: `audio/webm`, `audio/ogg`, `audio/wav`, `audio/mpeg`, `audio/mp4`.
- Batas default 25 MB, diatur via `MAX_AUDIO_FILE_BYTES`.

## Tidak termasuk
Speech-to-text, Whisper, diarisasi, summarization AI, action items, upload file
lokal, auth, kolaborasi, PostgreSQL, Docker, deployment.

## Catatan pengujian
Test memakai `backend/api_test.db` dan `backend/test_storage/` (diabaikan Git),
database produksi tidak tersentuh. Batas ukuran saat test = 1 MB agar cepat.
