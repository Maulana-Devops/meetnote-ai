"""Prompt ringkasan Bahasa Indonesia dengan skema tetap Fase 1.

Skema Structured Outputs tidak diubah (`overview`, `topics`, `decisions`)
supaya kompatibel dengan data lama. Prompt ini meminta model mengisi bagian
**Keputusan**, **Tindak lanjut**, **PIC**, **Tenggat**, dan **Catatan penting**
hanya dari fakta yang tertulis di transkrip, dengan referensi segmen yang
sudah ada. Ekstraksi action item terstruktur tetap memakai pipeline Sprint 8.
"""

from __future__ import annotations

from ...llm.base import SYSTEM_PROMPT, SummaryInput

SUMMARY_SYSTEM_PROMPT_ID = """Kamu adalah asisten yang membuat ringkasan rapat HANYA dari transkrip berbahasa Indonesia yang diberikan.

Aturan mutlak:
1. Gunakan Bahasa Indonesia yang jelas, ringkas, dan baku (EYD V). Jangan memakai pengetahuan umum, menebak, atau menambahkan informasi.
2. Jangan pernah menciptakan atau menebak identitas dunia nyata, jabatan, PIC, atau tenggat. Bila transkrip memakai label pembicara, pakai persis label itu.
3. `overview` memakai urutan tetap berlabel: Keputusan; Tindak lanjut; PIC; Tenggat; Catatan penting. Sertakan hanya bagian yang memang ada buktinya di transkrip; bagian tanpa bukti tulis "Belum tersedia." Jangan mengarang.
4. `topics`: topik yang benar-benar dibahas, dengan judul, detail singkat, dan referensi segmen pendukung. Jika transkrip menyebut tindak lanjut/PIC/tenggat, tulis di `detail` dengan awalan "Tindak lanjut:", "PIC:", atau "Tenggat:" persis sesuai bunyi transkrip.
5. `decisions`: HANYA keputusan akhir yang dinyatakan eksplisit dan disepakati/ditegaskan. Usulan, rencana, dan pernyataan satu pihak BUKAN keputusan. Jika tidak ada, kembalikan [].
6. Setiap topic dan decision WAJIB memiliki segment_ids (minimal satu), start_seconds, dan end_seconds. Salin ID segmen persis dari input; gunakan waktu terkecil/terbesar dari segmen yang dirujuk. Waktu tetap diverifikasi aplikasi terhadap database.
7. Jangan menerjemahkan istilah organisasi dari kamus. Jangan mengubah angka, tanggal, atau nama yang tertulis.
8. Keluarkan HANYA objek JSON sesuai schema. Jangan memasukkan catatan, markdown, atau teks di luar JSON.
"""


_INDONESIAN_LANGUAGES = {
    "id", "id-id", "ind", "indonesia", "indonesian", "bahasa indonesia",
}


def is_indonesian(language: str | None) -> bool:
    """True bila permintaan ringkasan memakai Bahasa Indonesia."""
    normalized = (language or "").strip().casefold()
    return normalized in _INDONESIAN_LANGUAGES or normalized.startswith("id-")


def build_summary_system_prompt(
    data: SummaryInput,
    *,
    default_language: str | None = None,
) -> str:
    """Pilih prompt Indonesia hanya bila bahasa output memang Indonesia."""
    language = (data.output_language or default_language or "").strip()
    return SUMMARY_SYSTEM_PROMPT_ID if is_indonesian(language) else SYSTEM_PROMPT


__all__ = [
    "SUMMARY_SYSTEM_PROMPT_ID",
    "build_summary_system_prompt",
    "is_indonesian",
]
