"""Konfigurasi aplikasi.

Semua nilai konfigurasi dibaca dari environment variables (atau file `.env`),
sehingga secret / setelan tidak perlu ditulis langsung di dalam kode.
"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Path absolut ke root proyek: backend/app/core/config.py -> naik 3 level.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Pengaturan aplikasi MeetNote AI."""

    # Nama aplikasi yang ditampilkan pada halaman utama / dokumentasi
    APP_NAME: str = "MeetNote AI"
    # Mode pengembangan (true = auto-reload di uvicorn). Default aman untuk rilis.
    DEBUG: bool = False
    # URL koneksi database SQLAlchemy (default: SQLite di folder backend)
    DATABASE_URL: str = "sqlite:///./meetnote.db"
    # Jalankan migrasi Alembic saat startup. Set false hanya untuk test suite
    # yang mengelola skema sendiri lewat Base.metadata.create_all().
    RUN_DB_MIGRATIONS: bool = True
    # Port server backend
    BACKEND_PORT: int = 8000
    # Origin frontend yang diizinkan, dipisah koma. Default: Vite dev server.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Sprint 2 — penyimpanan audio hasil rekaman.
    # Default: folder `storage/` di root proyek. Bisa ditimpa lewat .env.
    STORAGE_DIR: str = str(_PROJECT_ROOT / "storage")
    # Batas ukuran satu file rekaman (25 MB). Bisa ditimpa lewat .env.
    MAX_AUDIO_FILE_BYTES: int = 25 * 1024 * 1024

    # Sprint 4 — Speech-to-text. API key HANYA dibaca di backend.
    # `mock` tersedia untuk test/pengembangan lokal dan menghasilkan teks
    # berawalan [MOCK] — bukan hasil transkripsi sungguhan.
    STT_PROVIDER: str = "openai"
    # SecretStr menyembunyikan nilai saat settings di-repr/log.
    STT_API_KEY: SecretStr = SecretStr("")
    STT_API_BASE_URL: str = "https://api.openai.com/v1"
    STT_MODEL: str = "whisper-1"
    STT_TIMEOUT_SECONDS: float = 120.0
    # Batas dokumen provider OpenAI untuk file audio (25 MB).
    STT_MAX_FILE_BYTES: int = 25 * 1024 * 1024
    # Fixture khusus provider `mock` untuk acceptance UI tanpa provider live.
    # MOCK_STT_TEXT menghasilkan satu segmen tanpa timestamp;
    # MOCK_STT_SEGMENTS_JSON berisi array JSON [{text,start_seconds,end_seconds}].
    # Keduanya diabaikan oleh provider selain `mock`.
    MOCK_STT_TEXT: str = ""
    MOCK_STT_SEGMENTS_JSON: str = ""

    # Fase 1 — STT lokal (faster-whisper). Tidak ada API key; dependency
    # opsional dan di-import secara lazy agar CI tetap ringan. Default mock
    # dipakai untuk test; pilih `faster_whisper` pada deployment on-prem.
    STT_LOCAL_MODEL: str = "small"
    STT_DEVICE: str = "cpu"
    STT_COMPUTE_TYPE: str = "int8"
    STT_LANGUAGE: str = "id"
    STT_VAD: bool = True
    STT_WORD_TIMESTAMPS: bool = True
    STT_MODEL_DIR: str = str(_PROJECT_ROOT / "models" / "faster-whisper")
    # whisper.cpp memakai server OpenAI-compatible; audio harus WAV 16-bit mono.
    WHISPER_CPP_BASE_URL: str = "http://127.0.0.1:8080/v1"
    WHISPER_CPP_MODEL: str = "whisper.cpp"

    # Fase 1 — normalisasi Bahasa Indonesia.
    INDONESIAN_VOCAB_PATH: str = str(
        _PROJECT_ROOT / "config" / "indonesian-vocab.txt"
    )

    # Sprint 5 — Speaker diarization. API key HANYA dibaca di backend.
    # `mock` menghasilkan label [MOCK] di provider dan dipakai oleh test.
    DIARIZATION_PROVIDER: str = "deepgram"
    DIARIZATION_API_KEY: SecretStr = SecretStr("")
    DIARIZATION_API_BASE_URL: str = "https://api.deepgram.com/v1"
    # Model STT Deepgram; kompatibel dengan diarize_model (Whisper tidak).
    DIARIZATION_MODEL: str = "nova-3"
    # `latest`/`v1`/`v2` sesuai dokumentasi Deepgram. Jangan pakai diarize=true.
    DIARIZATION_DIARIZE_MODEL: str = "latest"
    DIARIZATION_TIMEOUT_SECONDS: float = 180.0
    # Batas file terdokumentasi Deepgram: 2 GB.
    DIARIZATION_MAX_FILE_BYTES: int = 2 * 1024 * 1024 * 1024
    # Ambang pemetaan: overlap harus >= rasio ini dari durasi segmen.
    DIARIZATION_MIN_OVERLAP_RATIO: float = 0.5
    # Ambang detik tambahan; 0 berarti hanya butuh rasio di atas + overlap > 0.
    DIARIZATION_MIN_OVERLAP_SECONDS: float = 0.0
    # Fase 1 — diarisasi pyannote opsional. Token HF tidak pernah masuk Git.
    PYANNOTE_MODEL: str = "pyannote/speaker-diarization-community-1"
    PYANNOTE_TOKEN: SecretStr = SecretStr("")
    # Telemetri dimatikan secara eksplisit sebelum library di-import.
    PYANNOTE_METRICS_ENABLED: bool = False

    # Sprint 7 — ringkasan AI. API key HANYA dibaca di backend.
    # `mock` menghasilkan ringkasan deterministik berawalan [MOCK] untuk test.
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_API_BASE_URL: str = "https://api.openai.com/v1"
    # Model harus mendukung Structured Outputs JSON schema (strict=true).
    LLM_MODEL: str = "gpt-4o-mini-2024-08-06"
    # Fase 1: default Bahasa Indonesia. Kosong = ikuti bahasa transkrip.
    LLM_OUTPUT_LANGUAGE: str = "Indonesia"
    LLM_TIMEOUT_SECONDS: float = 90.0
    # Batas karakter teks transkrip yang dikirim ke provider dalam satu request.
    LLM_MAX_INPUT_CHARACTERS: int = 24000

    # Muat nilai dari file .env jika ada. File .env tidak ikut ter-commit ke Git.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()