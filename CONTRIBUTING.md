# Berkontribusi ke MeetNote AI

Terima kasih sudah ingin membantu. Proyek ini mengutamakan perubahan yang bisa
diverifikasi, aman untuk data pengguna, dan tetap bisa dijalankan tanpa API key.

## Sebelum mulai

- Baca `README.md`, `docs/ARCHITECTURE.md`, dan `docs/MANUAL_ACCEPTANCE_TEST.md`.
- Gunakan provider `mock` untuk pengembangan. Semua hasil mock berlabel `[MOCK]`.
- Jangan pernah menaruh API key, token, atau secret lain di repository, chat, atau
  variabel berprefiks `VITE_*`.
- Jangan menghapus atau menimpa database, audio, `storage/`, backup,
  `node_modules`, `dist`, atau `__pycache__`.
- Satu meeting = satu recording. Rekaman kedua hanya melalui delete-then-add atau
  meeting baru.

## Lingkungan lokal

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

```powershell
cd frontend
npm ci
npm test
npm run build
```

Pemeriksaan secret dan migrasi:

```powershell
python backend\scripts\check_secrets.py
python backend\scripts\verify_migrations.py
```

`verify_migrations.py` memakai database temporer dan tidak menyentuh DB/audio
milik pengguna.

## Aturan perubahan

1. Buat branch/topik kecil; satu perubahan untuk satu tujuan.
2. Tambah atau perbarui test. Contract test provider mock dan provider nyata
   harus memakai ekspektasi yang sama.
3. Perubahan skema database wajib lewat Alembic revision. Jangan menulis SQL
   yang menjatuhkan tabel atau menghapus kolom tanpa migrasi data yang jelas.
4. Perubahan UI harus tetap mendukung Bahasa Indonesia, navigasi keyboard, dan
   pembaca layar.
5. Dokumentasi publik memakai placeholder `<USERPROFILE>`, `<folder-rekaman>`,
   dan `<rekaman-pengguna>`. Jangan memasukkan path absolut atau nama file pribadi.
6. Operasi Git (commit/push) hanya dengan persetujuan eksplisit. Push memakai SSH.

## Definition of done

- CI hijau: backend `pytest`, frontend `build` + `test`, secret scan bersih.
- Acceptance mock PASS 26/26 tetap hijau.
- Tidak ada secret, data pengguna, atau file biner model masuk Git.
- Dokumentasi diperbarui bila perilaku/endpoint berubah.
