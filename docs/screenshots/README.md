# Bukti visual MeetNote AI

Folder ini dipakai untuk menyimpan tangkapan layar (SS) yang menjadi bukti
bahwa aplikasi benar-benar berjalan, bukan hanya dokumentasi tertulis.

## Status saat ini

Belum ada file gambar di folder ini. Tabel di `README.md` bagian **Bukti visual**
masih berisi `Placeholder`. File `.gitkeep` hanya menjaga folder tetap ada di Git.

## Nama file yang direncanakan

| Nama file | Isi |
| --- | --- |
| `01-dashboard.png` | Dashboard berisi daftar meeting |
| `02-new-meeting.png` | Form pembuatan meeting dan panel rekaman |
| `03-recording.png` | Indikator rekaman, status `paused`, dan timer (MAT-05/06) |
| `04-transcript.png` | Dua segmen `[MOCK]` beserta waktu (MAT-10) |
| `05-summary.png` | Ringkasan dan action item (MAT-15/19) |
| `06-export.png` | Panel ekspor TXT/PDF (MAT-21/22) |
| `07-error.png` | Pesan error ramah dari kegagalan mock (MAT-25) |
| `08-diagnostics.png` | Diagnostics storage tanpa orphan/temp file |

## Cara menambahkan

1. Simpan SS dengan nama persis seperti di tabel, misalnya
   `docs/screenshots/01-dashboard.png`.
2. Di `README.md` bagian **Bukti visual**, ganti baris placeholder untuk file
   itu dengan tag Markdown:

   ```markdown
   | `docs/screenshots/01-dashboard.png` | Dashboard daftar meeting | ![Dashboard](docs/screenshots/01-dashboard.png) |
   ```

3. Commit dan push perubahan. Gambar akan tampil langsung di halaman GitHub.

## Catatan privasi

Sebelum menyimpan SS, pastikan tidak ada API key, token, email pribadi, atau
data rapat sensitif yang terlihat di layar. Seluruh bukti tertulis di repository
sudah memakai placeholder `<USERPROFILE>` dan hasil `[MOCK]`.
