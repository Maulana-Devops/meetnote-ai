"""Aturan format audio yang diterima backend.

Frontend memilih format memakai ``MediaRecorder.isTypeSupported()`` untuk
rekaman langsung, dan memakai MIME + ekstensi untuk file lokal. Backend tetap
menjadi sumber validasi utama.

Catatan: pemeriksaan signature di sini sengaja sederhana. Signature yang tidak
dikenali tidak ditolak (misalnya payload hasil MediaRecorder yang sudah diuji
pada Sprint 2), jadi ini **bukan** validasi konten yang sempurna.
"""

from pathlib import Path

# MIME type dasar -> ekstensi file yang dipakai untuk nama file di storage.
ALLOWED_AUDIO_TYPES: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}

# `.mp4` diterima sebagai ekstensi asli, tetapi file disimpan sebagai `.m4a`.
EXTRA_ALLOWED_EXTENSIONS: set[str] = {".mp4"}

ALLOWED_EXTENSIONS: set[str] = set(ALLOWED_AUDIO_TYPES.values()) | EXTRA_ALLOWED_EXTENSIONS


def normalize_content_type(content_type: str | None) -> str:
    """Ambil MIME type dasar, buang parameter seperti `;codecs=opus`."""
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def extension_for_content_type(content_type: str | None) -> str | None:
    """Kembalikan ekstensi aman untuk MIME type, atau None jika tidak didukung."""
    return ALLOWED_AUDIO_TYPES.get(normalize_content_type(content_type))


def is_allowed_extension(filename: str) -> bool:
    """Cek ekstensi nama file asli (hanya untuk validasi, bukan untuk path)."""
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def detect_content_mime(content: bytes) -> str | None:
    """Deteksi MIME dari beberapa signature audio umum.

    Mengembalikan None jika signature tidak dikenali. Tidak menjamin bahwa
    seluruh isi file benar-benar audio yang valid.
    """
    if len(content) >= 4 and content[:4] == b"\x1a\x45\xdf\xa3":  # EBML (WebM/MKV)
        return "audio/webm"
    if content[:4] == b"OggS":
        return "audio/ogg"
    if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
        return "audio/wav"
    if content[:3] == b"ID3" or (
        len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0
    ):
        return "audio/mpeg"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return "audio/mp4"
    return None


def signature_conflicts(content: bytes, declared_content_type: str) -> bool:
    """True hanya jika signature dikenali dan berbeda ekstensinya dengan MIME."""
    detected = detect_content_mime(content)
    if detected is None:
        return False

    declared_ext = extension_for_content_type(declared_content_type)
    detected_ext = extension_for_content_type(detected)
    return bool(declared_ext and detected_ext and declared_ext != detected_ext)