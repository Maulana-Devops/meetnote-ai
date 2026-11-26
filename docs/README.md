# Dokumentasi proyek MeetNote AI

- [Sprint 1 — Project Foundation](SPRINT1.md)
- [Sprint 2 — Live Audio Recording](SPRINT2.md)
- [Sprint 3 — Audio File Upload & Recording Management](SPRINT3.md)
- [Sprint 4 — Speech-to-Text untuk Rekaman yang Sudah Ada](SPRINT4.md)
- [Sprint 5 — Speaker Diarization (Label Anonim)](SPRINT5.md)
- [Sprint 6 — Edit Transkrip & Kelola Speaker](SPRINT6.md)
- [Sprint 7 — AI Summarization](SPRINT7.md)
- [Sprint 8 — Action Items Management](SPRINT8.md)
- [Sprint 9 — Pipeline Reliability & Data Integrity](SPRINT9.md)
- [Sprint 10 — Export Notulen (TXT & PDF)](SPRINT10.md)
- [Sprint 11 — Validasi Integrasi & Kesiapan Rilis](SPRINT11.md)
- [Sprint 12 — Repository Setup, Release Packaging & Manual Acceptance](SPRINT12.md)
- [Sprint 13 — Git Initialization Gate & Manual Acceptance](SPRINT13.md)
- [Panduan Instalasi Lokal](INSTALLATION.md)
- [Deployment On-Prem](DEPLOYMENT_ONPREM.md)
- [Prosedur Backup & Restore](BACKUP_RESTORE.md)
- [Manual Acceptance Testing](MANUAL_ACCEPTANCE_TEST.md)
- [Arsitektur](ARCHITECTURE.md)
- [Metodologi Benchmark Fase 1](BENCHMARK_METHOD.md)

## Pembaruan setelah acceptance

- **Fase 0 — Fondasi mutu:** Alembic baseline, CI GitHub Actions, Dependabot,
  logging JSON + request ID, Docker Compose, `LICENSE`, `CONTRIBUTING.md`,
  `CODEOWNERS`, dan `SECURITY.md`. Ringkasan ada di `README.md` bagian
  "Fondasi mutu (Fase 0)".
- **Fase 1 — Bahasa Indonesia & provider (terimplementasi, belum ada angka
  publik):** STT lokal `faster-whisper` (CPU/int8), fallback `whisper.cpp`,
  diarisasi `pyannote` opsional, kamus organisasi + normalisasi konservatif,
  prompt ringkasan Indonesia, caption browser `id-ID`, toggle kontras, dan
  satu contract test untuk mock/local. Metodologi ada di
  [BENCHMARK_METHOD.md](BENCHMARK_METHOD.md); angka CER/WER/DER/latency
  **belum diterbitkan** karena belum diukur pada korpus dengan consent.
