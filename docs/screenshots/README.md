# Bukti visual MeetNote AI

Folder ini menyimpan tangkapan layar (SS) sungguhan dari aplikasi yang
berjalan, bukan gambar yang digenerate.

## Status saat ini

Tujuh berkas sudah ada: `01-dashboard.png`, `02-new-meeting.png`,
`03-recording.png`, `04-transcript.png`, `05-summary.png`, `06-export.png`,
dan `08-diagnostics.png`. Semua berukuran 1440×1000 dan diambil dengan Chrome
headless dari `http://127.0.0.1:5173` (diagnostics dari API port 8000).

`07-error.png` tidak disediakan karena tidak ada meeting berstatus `FAILED`
pada saat pengambilan. Bukti tertulis MAT-25 ada di
`../MANUAL_ACCEPTANCE_TEST.md` dan `../SPRINT13.md`.

## Daftar berkas

| Nama file | Isi |
| --- | --- |
| `01-dashboard.png` | Dashboard berisi daftar meeting dan status backend |
| `02-new-meeting.png` | Form pembuatan meeting baru |
| `03-recording.png` | Panel **Rekaman** pada detail meeting (berkas tersimpan) |
| `04-transcript.png` | Dua segmen `[MOCK]` beserta penanda waktu |
| `05-summary.png` | AI Summary dan action item |
| `06-export.png` | Panel ekspor TXT/PDF |
| `08-diagnostics.png` | Respons API `/health/diagnostics` (0 orphan, 0 temp file) |

## Cara menambahkan SS lain

1. Simpan gambar dengan nama yang jelas di folder ini, misalnya
   `07-error.png`.
2. Tambahkan baris di `README.md` bagian **Bukti visual**:

   ```markdown
   | Error provider | Pesan error ramah | ![Error](docs/screenshots/07-error.png) |
   ```

3. Commit dan push. Gambar akan tampil langsung di halaman GitHub.

## Catatan privasi

Sebelum menyimpan SS, pastikan tidak ada API key, token, email pribadi, atau
data rapat sensitif yang terlihat di layar. Seluruh bukti tertulis di repository
sudah memakai placeholder `<USERPROFILE>` dan hasil `[MOCK]`.
