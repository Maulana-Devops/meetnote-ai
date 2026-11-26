# Metodologi Benchmark Fase 1 (Belum Ada Angka Publik)

Dokumen ini menjelaskan **cara mengukur**, bukan klaim mutu. Per 26 November
2026, **belum ada benchmark CER/WER/DER/latency yang dijalankan pada korpus
dengan consent**. Karena itu README dan dokumentasi lain tidak memuat angka
kualitas. Setiap angka harus diukur ulang di host dan korpus Anda sendiri.

## Status

| Metrik | Status saat ini |
| --- | --- |
| CER | Helper tersedia; angka lokal belum diterbitkan |
| WER | Helper tersedia; angka lokal belum diterbitkan |
| DER | Approximate frame-level DER tersedia; angka lokal belum diterbitkan |
| Latency | Diukur per permintaan `transcribe()`; angka lokal belum diterbitkan |

Hasil dari `STT_PROVIDER=mock` ditandai `[MOCK]` dan **hanya smoke test
pipeline**, bukan ukuran kualitas.

## Korpus

Gunakan hanya rekaman dan transkrip referensi yang Anda miliki haknya:

- rekaman audio asli (satu meeting = satu rekaman);
- transkrip referensi yang sudah ditinjau manusia;
- opsional: segmentasi referensi (`start_seconds`, `end_seconds`, `text`);
- opsional: giliran speaker referensi untuk DER.

Jangan memasukkan data pribadi, API key, token, path absolut, atau nama file
asli ke dalam laporan. Dalam contoh publik gunakan placeholder
`<USERPROFILE>`, `<folder-rekaman>`, dan `<rekaman-pengguna>`.

## Manifest

Satu baris JSON per rekaman. Contoh ada di
`backend/scripts/benchmark_manifest.example.jsonl`.

```json
{"audio_path": "<folder-rekaman>/<rekaman-pengguna>.wav", "reference_text": "Halo semua, kita mulai rapat.", "reference_segments": [{"text": "Halo semua, kita mulai rapat.", "start_seconds": 0, "end_seconds": 3}], "reference_diarization": [{"speaker": "A", "start_seconds": 0, "end_seconds": 3}]}
```

`audio_path` relatif terhadap folder manifest. `reference_diarization`
opsional; bila diisi, berikan juga `--diarization-provider`.

## Menjalankan

Dari root proyek, dengan interpreter backend yang sudah memuat dependency:

```powershell
& "<USERPROFILE>\path\ke\venv\Scripts\python.exe" backend\scripts\benchmark_asr.py `
  --manifest backend\scripts\benchmark_manifest.example.jsonl `
  --provider mock
```

Untuk provider lokal sungguhan (model/bobot harus tersedia di host):

```powershell
& "<USERPROFILE>\path\ke\venv\Scripts\python.exe" backend\scripts\benchmark_asr.py `
  --manifest <folder-rekaman>\manifest.jsonl `
  --provider faster_whisper `
  --diarization-provider pyannote `
  --output <folder-rekaman>\benchmark-result.json
```

Script tidak mengunduh model, tidak memakai API key, dan tidak menulis file
kecuali `--output` diberikan.

## Definisi

- **CER** — jarak edit karakter (whitespace diabaikan) dibagi jumlah karakter
  referensi. Tanda baca ikut dihitung.
- **WER** — jarak edit token `\w+` case-insensitive dibagi jumlah token
  referensi.
- **DER** — approximate frame-level diarisasi error rate dengan frame
  `0.1` detik, collar `0.25` detik, dan pemetaan speaker greedy berdasarkan
  overlap terbesar. Ini cukup untuk regression lokal, **bukan** pengganti
  evaluasi resmi pyannote. Nilainya dapat melebihi `1.0` bila banyak frame
  false alarm (sesuai definisi DER standar).
- **Latency** — `time.perf_counter()` sebelum/sesudah panggilan
  `provider.transcribe()` untuk satu berkas, termasuk pemuatan model pada
  panggilan pertama. Laporkan nilai rata-rata **dan** kondisi host.

Normalisasi teks sengaja dinonaktifkan pada perhitungan CER/WER
(`apply_eyd=False`) agar metrik mengukur keluaran provider apa adanya.
`source_ref` dan `language` tetap divalidasi pada setiap item.

## Yang wajib dicatat bila angka dipublikasikan

1. Tanggal pengukuran, versi MeetNote AI, dan versi dependency yang dipakai.
2. Nama model/bobot dan compute type (mis. `small`, `int8`, CPU).
3. Jumlah rekaman, total durasi, dan ringkasan komposisi korpus (tanpa data pribadi).
4. Parameter `--frame-seconds` dan `--collar-seconds` bila DER dilaporkan.
5. Host/CPU/RAM serta apakah model sudah di-cache.
6. Caveat bahwa angka hanya berlaku untuk konfigurasi dan korpus tersebut.

Lihat juga kontrak dan helper di `backend/app/services/indonesian/metrics.py`
serta pengujian di `backend/tests/test_fase1.py`.
