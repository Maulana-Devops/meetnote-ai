# Kebijakan Keamanan

## Melaporkan kerentanan

Jangan membuka issue publik untuk kerentanan. Gunakan **GitHub Security
Advisories** pada repository ini dan pilih laporkan secara privat, atau hubungi
pemilik repository melalui kanal privat yang tersedia di profil GitHub.

Sertakan:

- versi/kommit yang terdampak;
- langkah reproduksi;
- dampak yang mungkin terjadi;
- saran perbaikan bila ada.

## Yang tidak dianggap kerentanan

- Hasil provider `mock` yang berlabel `[MOCK]` dan tidak memakai API key.
- Dokumentasi yang sengaja memakai placeholder seperti `<USERPROFILE>`.
- Konfigurasi tanpa secret pada `.env.example`.

## Praktik yang diwajibkan proyek

- Secret hanya di lingkungan deployment; tidak pernah di Git atau frontend.
- Pemeriksaan OWASP Top 10 2025 sebelum endpoint sensitif diekspos ke jaringan.
- Semua perubahan skema database lewat Alembic dan tidak menghapus data pengguna.
- Backup dan restore tetap membutuhkan konfirmasi eksplisit.

## Versi yang didukung

Rilis `0.1.x` saat ini mendapat perbaikan keamanan. Versi yang lebih lama
mungkin tidak mendapat patch.
